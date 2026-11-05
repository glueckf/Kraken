"""Budgeted evolutionary search for demo topologies.

Objective = quality (trade-offs, non-naivety, playability fit for the size tier),
hard constraints as penalties. Every candidate is evaluated by lab_worker.py in a
fresh process (engine state leaks across topologies inside one process).
Writes every evaluation to archive.jsonl; prints a compact per-tier summary.
"""
import json, os, random, subprocess, sys, tempfile, time, math
from concurrent.futures import ThreadPoolExecutor

SCR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCR))
os.environ["PYTHONHASHSEED"] = "0"
LETTERS = "ABCDEF"
TIERS = [9, 11, 13, 15, 17, 19, 22, 25]   # target node counts; 28+ rarely draws cleanly on the 1000x640 canvas
POP, OFFSPRING, GENS = 10, 14, int(os.environ.get("GENS", 22))
WORKERS = 8
MULTI_FRAC = 0.35   # share of leaves that must emit two event types
ARCHIVE = os.path.join(SCR, "archive.jsonl")


# ---------------------------------------------------------------- graph utils
def layers(parents, n):
    lay = {0: 0}
    changed = True
    while changed:
        changed = False
        for c in range(1, n):
            ps = [lay[p] for p in parents.get(c, []) if p in lay]
            if ps and lay.get(c, 99) > min(ps) + 1:
                lay[c] = min(ps) + 1
                changed = True
    return lay


def to_spec(cand):
    """cand: dict(n, parents{c:[p]}, letters{leaf:[idx]}) -> renumbered spec."""
    n, parents, letters = cand["n"], cand["parents"], cand["letters"]
    lay = layers(parents, n)
    children = {i: [] for i in range(n)}
    for c, ps in parents.items():
        for p in ps:
            children[p].append(c)
    is_leaf = {i: not children[i] for i in range(n)}
    # renumber: cloud, watchtowers by layer, then leaves -- readable ids. The
    # front end spreads each drawn row evenly in id order, so order within a
    # row by neighbour barycenter (a few up/down sweeps) to cut crossings and
    # edges running behind unrelated towers.
    row = {i: (99 if is_leaf[i] else lay.get(i, 99)) for i in range(1, n)}
    rows = {}
    for i in range(1, n):
        rows.setdefault(row[i], []).append(i)
    pos = {0: 0.5}
    for ids in rows.values():
        for k, i in enumerate(sorted(ids)):
            pos[i] = k / max(1, len(ids) - 1)
    for _ in range(4):
        for r in sorted(rows):
            ids = rows[r]
            key = {i: sum(pos[j] for j in parents[i] + children[i]) / len(parents[i] + children[i]) for i in ids}
            ids.sort(key=lambda i: (key[i], i))
            for k, i in enumerate(ids):
                pos[i] = k / max(1, len(ids) - 1) if len(ids) > 1 else 0.5
    order = [0] + [i for r in sorted(rows) for i in rows[r]]
    rn = {old: new for new, old in enumerate(order)}
    edges = {}
    for c, ps in parents.items():
        for p in ps:
            edges.setdefault(rn[p], []).append(rn[c])
    edges = {p: sorted(cs) for p, cs in sorted(edges.items())}
    leaves = {rn[l]: sorted(v) for l, v in letters.items()}
    rlay = {rn[i]: lay.get(i, 99) for i in range(n)}
    cp = {0: None}
    for i in range(1, n):
        cp[i] = 10 if rn_leaf(i, is_leaf) else max(8, 32 - 6 * lay.get(i, 1))
    cp = {rn[i]: v for i, v in cp.items()}
    return dict(edges=edges, leaves=leaves, cp=cp), rlay


def rn_leaf(i, is_leaf):
    return is_leaf[i]


def valid(cand):
    n, parents, letters = cand["n"], cand["parents"], cand["letters"]
    if n > 32:
        return False
    lay = layers(parents, n)
    if len(lay) != n:
        return False
    children = {i: 0 for i in range(n)}
    for c, ps in parents.items():
        if not ps or len(set(ps)) != len(ps) or c in ps:
            return False
        for p in ps:
            children[p] += 1
    leaves = {i for i in range(1, n) if children[i] == 0}
    if set(letters) != leaves:
        return False
    for c, ps in parents.items():
        if c in leaves:
            if any(p in leaves for p in ps):
                return False
            continue
        if any(lay[p] >= lay[c] for p in ps):   # drawing sanity for watchtowers
            return False
    prod = {k: 0 for k in range(6)}
    for l, idx in letters.items():
        if not idx or len(set(idx)) != len(idx):
            return False
        for k in idx:
            prod[k] += 1
    if any(v == 0 for v in prod.values()):
        return False
    if sum(1 for v in prod.values() if v > 1) != 3:
        return False
    if sum(1 for v in letters.values() if len(v) > 1) < max(2, math.ceil(MULTI_FRAC * len(letters))):
        return False
    spec, _ = to_spec(cand)
    return layout_ok(spec)


def layout_ok(spec):
    """Overlaps, hidden edges, towers in the leaf row: never. An edge passing
    behind an unrelated tower: tolerated for a few edges (dual-homed links
    have to cross the middle rows somewhere)."""
    issues = lab.layout_issues(spec["edges"], spec["leaves"], min_visible=10)
    behind = {i.split(" runs")[0] for i in issues if "runs behind" in i}
    n_edges = sum(len(v) for v in spec["edges"].values())
    return len(issues) == sum("runs behind" in i for i in issues) and len(behind) <= 0.15 * n_edges


# ---------------------------------------------------------------- generation
ARCHETYPES = ["layered", "spine", "wings", "mesh", "gateways", "dualhome", "dualhome"]


def random_cand(rng, target):
    for _ in range(500):
        arche = rng.choice(ARCHETYPES)
        n = target + rng.choice([-1, 0, 0, 1])
        n = max(8, min(32, n))
        W = max(3, round((n - 1) * rng.uniform(0.35, 0.55)))
        L = n - 1 - W
        if L < 5:
            continue
        parents = {}
        wt = list(range(1, W + 1))
        if arche == "dualhome":
            # fast gateways straight under the cloud + slow aggregation chains;
            # leaves later get a chain node as primary and a gateway as second
            g = rng.randint(1, max(1, W // 3))
            for w in wt[:g]:
                parents[w] = [0]
            rest = wt[g:]
            chains = max(1, min(len(rest) // 2, rng.randint(1, 3)))
            heads = rest[:chains]
            for w in heads:
                parents[w] = [0]
            for i, w in enumerate(rest[chains:]):
                parents[w] = [rest[i]] if rng.random() < 0.7 else [rng.choice(rest[: chains + i])]
        elif arche == "spine":
            depth_nodes = max(2, W // 2)
            for i, w in enumerate(wt):
                if i < depth_nodes:
                    parents[w] = [0 if i == 0 else wt[i - 1]]
                else:
                    parents[w] = [rng.choice(wt[:depth_nodes])]
        elif arche == "gateways":
            g = max(2, W // 2)
            for i, w in enumerate(wt):
                parents[w] = [0] if i < g else [rng.choice(wt[max(0, i - 3):i])]
        else:
            depth = rng.choice([2, 3, 3, 4]) if W >= 4 else 2
            widths = [1] * depth
            for _ in range(W - depth):
                widths[rng.randrange(depth)] += 1
            if arche == "wings":
                widths[0] = min(widths[0], 2)
            idx = 0
            by_layer = []
            for d, wdt in enumerate(widths):
                layer_nodes = wt[idx: idx + wdt]
                idx += wdt
                for w in layer_nodes:
                    if d == 0:
                        parents[w] = [0]
                    else:
                        ps = [rng.choice(by_layer[d - 1])]
                        if arche == "mesh" and len(by_layer[d - 1]) > 1 and rng.random() < 0.6:
                            ps.append(rng.choice([x for x in by_layer[d - 1] if x != ps[0]]))
                        parents[w] = ps
                by_layer.append(layer_nodes)
        lay = layers(parents, W + 1)
        # leaves
        childless = [w for w in wt if not any(w in ps for ps in parents.values())]
        leaf_ids = list(range(W + 1, n))
        p2 = rng.uniform(0.25, 0.75)
        for j, l in enumerate(leaf_ids):
            if j < len(childless):
                prim = childless[j]
            else:
                deep = sorted(wt, key=lambda w: -lay.get(w, 0))
                prim = rng.choice(deep[: max(2, len(deep) // 2)] if rng.random() < 0.7 else wt)
            ps = [prim]
            if rng.random() < p2:
                others = [w for w in wt if w != prim and lay.get(w) != lay.get(prim)] or [w for w in wt if w != prim]
                if others:
                    ps.append(rng.choice(others))
            parents[l] = ps
        if any(not any(w in ps for ps in parents.values()) for w in wt):
            continue
        letters = assign_letters(rng, leaf_ids)
        if letters is None:
            continue
        cand = dict(n=n, parents=parents, letters=letters, arche=arche)
        if valid(cand):
            return cand
    raise RuntimeError("could not generate")


def try_random(rng, target):
    try:
        return random_cand(rng, target)
    except RuntimeError:
        return None


def assign_letters(rng, leaf_ids):
    L = len(leaf_ids)
    dup = rng.sample(range(6), 3)
    single = [k for k in range(6) if k not in dup]
    pairs = [(k,) for k in single]
    counts = {k: 2 for k in dup}
    total = 3 + 6
    while total < L + max(2, math.ceil(MULTI_FRAC * L)):
        counts[rng.choice(dup)] += 1
        total += 1
    pool = single + [k for k in dup for _ in range(counts[k])]
    rng.shuffle(pool)
    letters = {l: [] for l in leaf_ids}
    # one letter per leaf first, extra letters go to leaves without that letter
    for i, l in enumerate(leaf_ids):
        letters[l].append(pool[i])
    for k in pool[L:]:
        cands = [l for l in leaf_ids if k not in letters[l] and len(letters[l]) < 2]
        if not cands:
            return None
        letters[rng.choice(cands)].append(k)
    return {l: sorted(v) for l, v in letters.items()}


def mutate(rng, cand):
    for _ in range(200):
        c = json.loads(json.dumps(cand))
        c["parents"] = {int(k): v for k, v in c["parents"].items()}
        c["letters"] = {int(k): v for k, v in c["letters"].items()}
        n = c["n"]
        leaves = list(c["letters"])
        wt = [i for i in range(1, n) if i not in c["letters"]]
        op = rng.choice(["move_leaf", "add_p2", "drop_p2", "swap_letters", "move_letter",
                         "reparent_wt", "mesh_add", "mesh_drop", "swap_role"])
        if op == "move_leaf":
            l = rng.choice(leaves)
            c["parents"][l][0] = rng.choice(wt)
        elif op == "add_p2":
            l = rng.choice(leaves)
            c["parents"][l].append(rng.choice(wt))
        elif op == "drop_p2":
            l = rng.choice([x for x in leaves if len(c["parents"][x]) > 1] or leaves)
            if len(c["parents"][l]) > 1:
                c["parents"][l].pop(rng.randrange(len(c["parents"][l])))
        elif op == "swap_letters":
            a, b = rng.sample(leaves, 2)
            c["letters"][a], c["letters"][b] = c["letters"][b], c["letters"][a]
        elif op == "move_letter":
            a, b = rng.sample(leaves, 2)
            if c["letters"][a]:
                k = c["letters"][a].pop(rng.randrange(len(c["letters"][a])))
                if k not in c["letters"][b]:
                    c["letters"][b] = sorted(c["letters"][b] + [k])
        elif op == "reparent_wt":
            w = rng.choice(wt)
            c["parents"][w] = [rng.choice([0] + wt)]
        elif op == "mesh_add":
            w = rng.choice(wt)
            c["parents"][w].append(rng.choice([0] + wt))
        elif op == "mesh_drop":
            w = rng.choice(wt)
            if len(c["parents"][w]) > 1:
                c["parents"][w].pop()
        elif op == "swap_role":
            # turn one single-producer letter into a duplicated one and vice versa
            prod = {k: [l for l in leaves if k in c["letters"][l]] for k in range(6)}
            singles = [k for k in range(6) if len(prod[k]) == 1]
            dups = [k for k in range(6) if len(prod[k]) > 1]
            if singles and dups:
                s, d = rng.choice(singles), rng.choice(dups)
                for l in leaves:
                    c["letters"][l] = sorted(s if k == d else d if k == s else k for k in c["letters"][l])
        if valid(c):
            return c
    return cand


# ---------------------------------------------------------------- objective
import topology_lab as lab  # noqa: E402  (PYTHONHASHSEED already 0)


def score(res, n_nodes, target):
    """Quality only -- diversity is handled by the MAP-Elites cells and the
    final farthest-point pick, not by this number."""
    if not res.get("ok"):
        return -100.0
    fails = lab.verdict(res["per_query"])
    pq = lab.playable(res["per_query"])
    s = -6.0 * len(fails) - 1.0 * (len(res["per_query"]) - len(pq))
    for sid, m in pq.items():
        s += 3.0 * (m["stage_distinct_nodes"] >= 2) + 2.0 * (m["stage_distinct_nodes"] == 3)
        s += 1.0 * (m["stage_distinct_plans"] - 1)
        s += 0.5 * (min(m["pareto"], 4) - 1)
        s += 1.0 * (m["landscape_best_distinct"] >= 2)
        s += 0.5 * (min(m["off_cloud"]) >= 1)
        for h, gaps in m["heuristic_gap"].items():
            if all(v == 0 for v in gaps.values()):
                s -= 0.75
        # playability: host choices per operator scale with size tier
        cap = 3 + (target - 9) // 5        # 3 (small) .. 7 (largest)
        if m["max_hosts"] > cap:
            s -= 1.0 * (m["max_hosts"] - cap)
        if m["max_hosts"] < 2:
            s -= 2.0
        if m["truncated"]:
            s -= 3.0
    # complexity grows with size: more operators to place on bigger networks
    if pq:
        mean_subq = sum(m["subq"] for m in pq.values()) / len(pq)
        s -= 0.75 * abs(mean_subq - (2.75 + 2.0 * (target - 9) / 22))
    s -= 0.5 * abs(n_nodes - target)
    return s


_PART_RANK = ["same", "other", "FB|C", "FC|B", "F|BC", "F|B|C"]


def descriptor(cand, res):
    """MAP-Elites cell from what the topology *teaches*, not its shape:
    (size tier, richest goal split, does Fast use the cloud, what wins for
    Cheap). Each cell keeps its own elite, so the archive stays a pool of
    different lessons instead of converging on one best topology."""
    tier = min(TIERS, key=lambda t: abs(t - cand["n"]))
    les = lab.lesson(res["per_query"], res["sol"])
    if not les:
        return (tier, "none", False, "none")
    part = max((l["part"] for l in les.values()), key=_PART_RANK.index)
    fast_cloud = any(l["fast_cloud"] > 0 for l in les.values())
    cheap = [tuple(l["cheap_rule"]) for l in les.values()]
    cheap_tag = ("near" if all("near_sources" in c for c in cheap) else
                 "none" if all(not c for c in cheap) else "mixed")
    return (tier, part, fast_cloud, cheap_tag)


# ---------------------------------------------------------------- evaluation
def evaluate(cand):
    spec, lay = to_spec(cand)
    with tempfile.NamedTemporaryFile("w", suffix=".json", dir=SCR, delete=False) as f:
        json.dump(spec, f)
        path = f.name
    try:
        out = subprocess.run(
            [sys.executable, os.path.join(SCR, "lab_worker.py"), path],
            capture_output=True, text=True, timeout=180, cwd=os.path.join(SCR, "junk"))
        line = [l for l in out.stdout.splitlines() if l.startswith("{")]
        res = json.loads(line[-1]) if line else dict(ok=False, error=out.stderr[-300:])
    except subprocess.TimeoutExpired:
        res = dict(ok=False, error="timeout")
    finally:
        os.remove(path)
    return spec, res


def main():
    os.makedirs(os.path.join(SCR, "junk"), exist_ok=True)
    seed = int(os.environ.get("SEED", 7))
    rng = random.Random(seed)
    grid = {}   # cell -> (score, cand)
    arch = None
    t0 = time.time()

    def run_batch(cands):
        with ThreadPoolExecutor(WORKERS) as ex:
            futs = [(c, ex.submit(evaluate, c)) for c in cands]
            for c, f in futs:
                spec, res = f.result()
                if not res.get("ok"):
                    continue
                cell = descriptor(c, res)
                sc = score(res, c["n"], cell[0])
                rec = dict(cell=cell, score=round(sc, 3), cand=c, spec=spec,
                           fails=res.get("fails"), per_query=res.get("per_query"),
                           sol=res.get("sol"), error=res.get("error"))
                arch.write(json.dumps(rec) + "\n")
                arch.flush()
                if cell not in grid or sc > grid[cell][0]:
                    grid[cell] = (sc, c)

    # seed the grid from everything already evaluated (rescored under the
    # current objective), then top up with fresh random candidates
    if os.path.exists(ARCHIVE):
        for line in open(ARCHIVE):
            r = json.loads(line)
            if not r.get("per_query"):
                continue
            res = dict(ok=True, per_query=r["per_query"], sol=r["sol"])
            c = r["cand"]
            c["parents"] = {int(k): v for k, v in c["parents"].items()}
            c["letters"] = {int(k): v for k, v in c["letters"].items()}
            if not valid(c):   # stricter rules than when it was archived
                continue
            cell = descriptor(c, res)
            sc = score(res, c["n"], cell[0])
            if cell not in grid or sc > grid[cell][0]:
                grid[cell] = (sc, c)
        print(f"seeded {len(grid)} cells from archive", flush=True)
    arch = open(ARCHIVE, "a")
    run_batch([c for c in (try_random(rng, t) for t in TIERS for _ in range(POP)) if c])
    per_gen = OFFSPRING * len(TIERS)
    for g in range(GENS):
        jobs = []
        cells = list(grid)
        for _ in range(per_gen):
            if rng.random() < 0.12:
                c = try_random(rng, rng.choice(TIERS))
                if c:
                    jobs.append(c)
            else:
                # uniform over filled cells (MAP-Elites), slight bias to good ones
                a, b = rng.sample(cells, 2) if len(cells) > 1 else (cells[0], cells[0])
                parent = grid[a if grid[a][0] >= grid[b][0] else b][1]
                child = parent
                for _ in range(rng.choice([1, 1, 2, 3])):
                    child = mutate(rng, child)
                jobs.append(child)
        run_batch(jobs)
        good = sum(1 for s, _ in grid.values() if s > 0)
        best = {t: round(max([s for c, (s, _) in grid.items() if c[0] == t] or [-99]), 1) for t in TIERS}
        print(f"gen {g} t={time.time() - t0:.0f}s cells={len(grid)} good={good} best={best}", flush=True)


if __name__ == "__main__":
    main()
