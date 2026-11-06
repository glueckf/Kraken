"""Search for bigger topologies (19-25 nodes, 7-11 watchtowers) that keep
placement trade-offs. Prototype, nothing from it ships yet: results and the
open problem in demo/BACKLOG.md item 37.

Why the normal search never finds them: with only six event types, a big
network's duplicated letters end up on leaves all over the tree, so every
operator needs a host that reaches every producer -- usually only the cloud
(archive: 527 "only N plans" and 371 "everything at the cloud" verdict
failures among 269 candidates with 7+ watchtowers, none of which moves an
operator between stages). Here a topology is two *regions* under one
cloud, each with its own block of letters (A-C / D-F, the way the queries
group them), so operators over one region's letters can stay inside it and
only cross-region joins need the cloud. A region is either
  - a passing 4-6 tower design from archive.jsonl that already moves
    operators between goals ("composite"; skipped when there is no local
    archive.jsonl from a topo_search.py run), or
  - a generated gateway / hub / deep-chain mesh ("regional").

Reuses topo_search.py (evaluation, validity, drawing gates, mutation,
MAP-Elites loop) with its own tiers, archive file, generator and a score
bonus for rules of thumb that lose at every goal. Same knobs as
topo_search.py (GENS, SEED env vars) plus WORKERS, ARCHIVE (default
archive_complex.jsonl, gitignored) and BEHIND.
"""
import json
import math
import os
import random
import sys

DESIGN = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DESIGN)
import topo_search as ts  # noqa: E402
import topology_lab as lab  # noqa: E402

ts.TIERS = [19, 21, 23, 25]
ts.ARCHIVE = os.environ.get("ARCHIVE", os.path.join(DESIGN, "archive_complex.jsonl"))
ts.WORKERS = int(os.environ.get("WORKERS", 7))
ts.POP, ts.OFFSPRING = 12, 12
BLOCKS = [[0, 1, 2], [3, 4, 5]]
BEHIND = float(os.environ.get("BEHIND", 0.30))


def layout_ok(spec):
    """topo_search.layout_ok with a looser cap on edges running behind an
    unrelated tower: two regions side by side share the drawn rows, and the
    front end spreads every row evenly, so a region's rows don't line up."""
    issues = lab.layout_issues(spec["edges"], spec["leaves"], min_visible=10)
    behind = {i.split(" runs")[0] for i in issues if "runs behind" in i}
    n_edges = sum(len(v) for v in spec["edges"].values())
    return len(issues) == sum("runs behind" in i for i in issues) and len(behind) <= BEHIND * n_edges


ts.layout_ok = layout_ok


def _modules():
    path = os.path.join(DESIGN, "archive.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        r = json.loads(line)
        if r.get("fails") or not r.get("per_query"):
            continue
        c = r["cand"]
        wt = c["n"] - 1 - len(c["letters"])
        moves = sum(1 for m in r["per_query"].values() if m["stage_distinct_nodes"] >= 2)
        if moves and 4 <= wt <= 6 and c["n"] <= 14:
            out.append(dict(n=c["n"], parents={int(k): v for k, v in c["parents"].items()},
                            leaves=sorted(int(k) for k in c["letters"])))
    return out


MODULES = _modules()


def composite_cand(rng, target):
    for _ in range(400):
        a = rng.choice(MODULES)
        fit = [m for m in MODULES if abs(a["n"] + m["n"] - 1 - target) <= 1]
        if not fit:
            continue
        b = rng.choice(fit)
        parents, per, nid = {}, [], 1
        for m in (a, b):
            rn = {0: 0}
            for old in range(1, m["n"]):
                rn[old] = nid
                nid += 1
            for c, ps in m["parents"].items():
                parents[rn[c]] = [rn[p] for p in ps]
            per.append([rn[l] for l in m["leaves"]])
        letters = regional_letters(rng, per)
        if letters is None:
            continue
        cand = dict(n=nid, parents=parents, letters=letters, arche="composite")
        if ts.valid(cand):
            return cand
    raise RuntimeError("could not compose")


def regional_cand(rng, target):
    """Each region: a gateway and a hub head on layer 1, a mid node under
    the head (sometimes also the gateway), then a chain of deeper hubs.
    Leaves hang off the deeper hubs and often also off the gateway."""
    for _ in range(4000):
        n = target + rng.choice([-1, 0, 0, 1])
        W = max(7, min(11, round((n - 1) * rng.uniform(0.30, 0.42))))
        L = n - 1 - W
        if L < 8:
            continue
        sizes = [3, 3]
        for _ in range(W - 6):
            sizes[rng.randrange(2)] += 1
        if max(sizes) > 6:
            continue
        parents, nid = {}, 1
        regions = []
        for s in sizes:
            gw, head, mid = nid, nid + 1, nid + 2
            nid += 3
            parents[gw] = [0]
            parents[head] = [0]
            parents[mid] = [head, gw] if rng.random() < 0.5 else [head]
            towers, deep = [gw, head, mid], [mid]
            for _ in range(s - 3):
                p = [deep[-1] if rng.random() < 0.65 else rng.choice(deep)]
                alt = [w for w in towers if w not in p and w != gw]
                if rng.random() < 0.3 and alt:
                    p.append(rng.choice(alt))
                parents[nid] = p
                towers.append(nid)
                deep.append(nid)
                nid += 1
            regions.append(dict(gw=gw, towers=towers, deep=deep))
        lay = ts.layers(parents, nid)
        if any(lay.get(c, 99) <= min(lay.get(p, 99) for p in ps) for c, ps in parents.items()):
            continue
        leaf_ids = list(range(nid, n))
        rng.shuffle(leaf_ids)
        cut = rng.randint(4, len(leaf_ids) - 4)
        per = [leaf_ids[:cut], leaf_ids[cut:]]
        for r, ls in zip(regions, per):
            childless = [w for w in r["deep"] if not any(w in ps for ps in parents.values())]
            for j, l in enumerate(ls):
                prim = childless[j] if j < len(childless) else rng.choice(r["deep"])
                ps = [prim]
                if rng.random() < 0.6 or (j == len(ls) - 1 and not any(
                        r["gw"] in parents.get(x, []) for x in ls)):
                    ps.append(r["gw"])
                parents[l] = ps
        if any(not any(w in ps for ps in parents.values()) for w in range(1, nid)):
            continue
        letters = regional_letters(rng, per)
        if letters is None:
            continue
        cand = dict(n=n, parents=parents, letters=letters, arche="regional")
        if ts.valid(cand):
            return cand
    raise RuntimeError("could not generate")


def regional_letters(rng, per):
    """Region i gets letter block i; a duplicated letter's copies stay in
    its region. Exactly 3 duplicated letters (topology_lab's rule): one
    region holds two of them, the other one. A region with one duplicated
    letter can only have two two-letter leaves (dup + each single), so the
    other region makes up the rest of the 35% two-letter share."""
    L = sum(len(ls) for ls in per)
    need = max(2, math.ceil(ts.MULTI_FRAC * L))
    for _ in range(30):
        two = rng.randrange(2)          # region holding two duplicated letters
        dups = [rng.sample(BLOCKS[i], 2 if i == two else 1) for i in range(2)]
        cap = [len(per[i]) if i == two else min(2, len(per[i])) for i in range(2)]
        m_one = min(cap[1 - two], rng.randint(0, 2))
        m = [0, 0]
        m[1 - two] = m_one
        m[two] = need - m_one
        if m[two] > cap[two] or m[two] < 0:
            continue
        letters = {}
        ok = True
        for i, ls in enumerate(per):
            got = _fill(rng, ls, BLOCKS[i], dups[i], m[i])
            if got is None:
                ok = False
                break
            letters.update(got)
        if ok:
            return letters
    return None


def _fill(rng, ls, block, dups, m):
    singles = [k for k in block if k not in dups]
    for _ in range(30):
        slots = len(ls) + m
        pool = list(singles)
        while len(pool) < slots:
            pool.append(rng.choice(dups))
        if len(pool) != slots or any(pool.count(k) < 2 for k in dups):
            continue
        rng.shuffle(pool)
        cur = {l: [] for l in ls}
        for l, k in zip(ls, pool):
            cur[l].append(k)
        ok = True
        for k in pool[len(ls):]:
            cands = [l for l in ls if k not in cur[l] and len(cur[l]) < 2]
            if not cands:
                ok = False
                break
            cur[rng.choice(cands)].append(k)
        if ok:
            return {l: sorted(v) for l, v in cur.items()}
    return None


def mixed_cand(rng, target):
    return (composite_cand if MODULES and rng.random() < 0.6 else regional_cand)(rng, target)


ts.random_cand = mixed_cand
_base_score = ts.score


def score(res, n_nodes, target):
    s = _base_score(res, n_nodes, target)
    if not res.get("ok"):
        return s
    # rules of thumb that lose at every goal make for a harder puzzle
    for m in lab.playable(res["per_query"]).values():
        for a in ("0.2", "0.6", "0.9"):
            if all(g[a] > 0 for g in m["heuristic_gap"].values()):
                s += 0.5
    return s


ts.score = score

if __name__ == "__main__":
    ts.main()
