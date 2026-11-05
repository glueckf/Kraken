"""Design lab for hand-curated topologies: scores a candidate network against
the demo's design goals *before* it goes into reef_topologies.py, using the
real engine (the same build_scenario() the exporter runs) plus an exhaustive
"player's-eye" sweep of every valid all-push placement.

Design goals checked (see demo/BACKLOG.md item 35):
  - not naive: every visible story query decomposes (>=2 subqueries), Kraken
    places operators in the fog (not everything at the cloud), and there is
    more than one sensible plan to choose from;
  - not too complex: a bounded number of valid hosts per operator, so a
    newcomer can finish a round in reasonable time;
  - trade-offs: Fast / Balanced / Cheap genuinely differ -- ideally in *where*
    operators go, not only in push vs pull -- and no single rule of thumb
    ("all at the cloud", "as close to the sources as possible", "just below
    the cloud") is best for every goal;
  - multiple sources: half of the six letters (3) have more than one producer.

A tree can't have placement trade-offs: any common ancestor of a query's
sources lies on their own route to the cloud, so latency is the same
wherever the operator goes. Placement trade-offs need sources that are
multi-homed -- a fast direct uplink plus a slower, local aggregation route --
so the cheap spot (combine early, near the sources) is off the fast path.

Usage (from the INES repo root, same venv as the exporter):
  uv run python ../INES-demo/demo/export/topology_lab.py <topology_id> [...]
evaluates already-registered reef_topologies.BUILDERS entries. Other scripts
import evaluate() and pass an ad-hoc spec dict(edges=..., leaves=..., cp=...).
"""
import os
import sys

if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

import itertools
import json
import math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import export_scenario as ex  # noqa: E402  (sets up sys.path for the engine)
import reef_topologies  # noqa: E402

VISIBLE_SCENARIOS = [s for s in ex.scenarios_def.SCENARIOS if s["id"] != "seq_and_pairs"]
# A query is playable on a topology when a newcomer can place it in
# reasonable time: 2..MAX_SUBQ operators. A topology needs MIN_PLAYABLE
# playable queries; one that decomposes further is dropped from that
# topology's query bar rather than failing the whole topology.
MIN_SUBQ, MAX_SUBQ, MIN_PLAYABLE = 2, 5, 3
LETTERS = "ABCDEF"
MAX_ENUM = 200_000


# ----------------------------------------------------------------------------
# Pure-graph helpers (no engine needed)
# ----------------------------------------------------------------------------
def graph_of(edges, leaves):
    n = max(max(edges, default=0), *(max(c) for c in edges.values())) + 1
    parents = {i: [] for i in range(n)}
    children = {i: list(edges.get(i, [])) for i in range(n)}
    for p, cs in edges.items():
        for c in cs:
            parents[c].append(p)
    # layer = shortest upward hop count to the cloud
    layer = {0: 0}
    frontier = [0]
    while frontier:
        nxt = []
        for p in frontier:
            for c in children[p]:
                if c not in layer:
                    layer[c] = layer[p] + 1
                    nxt.append(c)
        frontier = nxt
    desc = {}

    def d(i):
        if i not in desc:
            s = {i}
            for c in children[i]:
                s |= d(c)
            desc[i] = s
        return desc[i]

    for i in range(n):
        d(i)
    producers = {L: sorted(l for l, idx in leaves.items() if LETTERS.index(L) in idx) for L in LETTERS}
    return dict(n=n, parents=parents, children=children, layer=layer, desc=desc, producers=producers)


def structural_issues(edges, leaves):
    """Hard constraints that need no engine run."""
    g = graph_of(edges, leaves)
    issues = []
    n = g["n"]
    if n > 32:
        issues.append(f"{n} nodes > 32")
    if len(g["layer"]) != n:
        issues.append("unreachable nodes")
    leaf_ids = {i for i in range(n) if not g["children"][i]}
    for i in leaf_ids:
        if not leaves.get(i):
            issues.append(f"leaf {i} has no letter")
    for i in leaves:
        if i not in leaf_ids:
            issues.append(f"non-leaf {i} carries letters")
    for L in LETTERS:
        if not g["producers"][L]:
            issues.append(f"letter {L} has no producer")
    dup = sum(1 for L in LETTERS if len(g["producers"][L]) > 1)
    if dup != 3:
        issues.append(f"{dup} duplicated letters (want 3)")
    # drawing sanity: leaves sit in the bottom row, so only a watchtower's
    # own parents must all be drawn above it
    for c in range(1, n):
        if c in leaf_ids:
            continue
        for p in g["parents"][c]:
            if g["layer"].get(p, 99) >= g["layer"].get(c, 0):
                issues.append(f"edge {c}->{p} points sideways/down")
    return issues


# ---------------------------------------------------------------- drawing
# Mirrors web/src/reef.ts computeLayout/towerShape/cloudImageBox: what the
# audience actually sees. A topology the engine likes is still useless if a
# tower hides an edge or an edge runs behind an unrelated tower.
VB_W, VB_H, TOP_Y, BOTTOM_MARGIN, ROW_MARGIN = 1000, 640, 86, 92, 96


def drawing(edges, leaves):
    """{node: (x, y, box)} with box = (x0, y0, x1, y1) of the drawn artwork."""
    n = max(max(edges), *(max(c) for c in edges.values())) + 1
    lay, frontier = {0: 0}, [0]
    while frontier:
        nxt = []
        for p in frontier:
            for c in edges.get(p, []):
                if c not in lay:
                    lay[c] = lay[p] + 1
                    nxt.append(c)
        frontier = nxt
    max_layer = max(lay.values())
    rows = {}
    for i in range(n):
        rows.setdefault(max_layer if i in leaves else lay[i], []).append(i)
    step = (VB_H - BOTTOM_MARGIN - TOP_Y) / max_layer
    span = VB_W - 2 * ROW_MARGIN
    out = {}
    for row, ids in rows.items():
        ids.sort()
        y = TOP_Y + row * step
        leaf_r = min(24, span / (len(ids) - 1) * 0.42) if len(ids) > 1 else 24
        for k, i in enumerate(ids):
            x = VB_W / 2 if len(ids) == 1 else ROW_MARGIN + span * k / (len(ids) - 1)
            if i == 0:
                box = (x - 55.5, y - 75, x + 55.5, y + 30)
            elif i in leaves:
                box = (x - leaf_r, y - leaf_r, x + leaf_r, y + leaf_r)
            else:   # tower image: h = 3.3r, w = h*431/480, bottom at y + 0.85r (r = 30)
                box = (x - 44.5, y - 73.5, x + 44.5, y + 25.5)
            out[i] = (x, y, box)
    return out, rows, max_layer


def layout_issues(edges, leaves, min_visible=30.0, max_hidden=12.0):
    edges = {int(k): v for k, v in edges.items()}
    leaves = {int(k) for k in leaves}
    pos, rows, max_layer = drawing(edges, leaves)
    issues = [f"watchtower n{i} drawn in the leaf row" for i in rows[max_layer] if i not in leaves]
    inside = lambda pt, b: b[0] < pt[0] < b[2] and b[1] < pt[1] < b[3]
    ids = sorted(pos)
    for a, b in itertools.combinations(ids, 2):
        ba, bb = pos[a][2], pos[b][2]
        if ba[0] < bb[2] and bb[0] < ba[2] and ba[1] < bb[3] and bb[1] < ba[3]:
            issues.append(f"n{a} and n{b} overlap")
    for p, cs in edges.items():
        for c in cs:
            (ax, ay, _), (bx, by, _) = pos[p], pos[c]
            my = (ay + by) / 2
            pts = []
            for k in range(41):
                t = k / 40
                u = 1 - t
                pts.append((u ** 3 * ax + 3 * u * u * t * ax + 3 * u * t * t * bx + t ** 3 * bx,
                            u ** 3 * ay + 3 * u * u * t * my + 3 * u * t * t * my + t ** 3 * by))
            seg = [math.dist(pts[k], pts[k + 1]) for k in range(40)]
            visible = sum(s for k, s in enumerate(seg) if not any(inside(pts[k], pos[i][2]) for i in ids))
            if visible < min_visible:
                issues.append(f"edge n{p}-n{c} hidden behind artwork ({visible:.0f}px visible)")
            for i in ids:
                if i in (p, c):
                    continue
                hidden = sum(s for k, s in enumerate(seg) if inside(pts[k], pos[i][2]))
                if hidden > max_hidden:
                    issues.append(f"edge n{p}-n{c} runs behind n{i}")
    return issues


def wl_histogram(edges, leaves, iterations=3):
    """Weisfeiler-Lehman subtree features (undirected structure + letter
    multiplicity + depth), for graph-similarity between candidates."""
    g = graph_of(edges, leaves)
    labels = {}
    for i in range(g["n"]):
        if i == 0:
            labels[i] = "cloud"
        elif not g["children"][i]:
            labels[i] = "leaf%d" % len(leaves.get(i, []))
        else:
            labels[i] = "wt"
    hist = {}
    for it in range(iterations + 1):
        for lab in labels.values():
            hist[(it, lab)] = hist.get((it, lab), 0) + 1
        new = {}
        for i in range(g["n"]):
            up = sorted("u" + labels[p] for p in g["parents"][i])
            down = sorted("d" + labels[c] for c in g["children"][i])
            new[i] = str(hash((labels[i], tuple(up), tuple(down))))
        labels = new
    return hist


def cosine(a, b):
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ----------------------------------------------------------------------------
# Engine-backed evaluation
# ----------------------------------------------------------------------------
def _landscape(sc):
    """Every valid all-push placement (non-leaf hosts, Kraken's own candidate
    rule) with its cost/latency, via the exporter's reference scorer."""
    nodes = sc["topology"]["nodes"]
    non_leaf = [n["id"] for n in nodes if not n["is_leaf"]]
    children = {n["id"]: n["children"] for n in nodes}
    desc = {}

    def d(i):
        if i not in desc:
            s = {i}
            for c in children[i]:
                s |= d(c)
            desc[i] = s
        return desc[i]

    producers = sc["event_map"]["producers"]
    order = sc["processing_order"]
    proj = {p["name"]: p for p in sc["projections"]}
    hosts0 = {}
    for name in order:
        srcs = set()
        for prim in proj[name]["primitives"]:
            srcs |= set(producers.get(prim, []))
        hosts0[name] = [h for h in non_leaf if srcs <= d(h)]

    dist = sc["topology"]["distance_matrix"]
    local_rate = {L: {int(k): v for k, v in m.items()} for L, m in sc["event_map"]["local_rate_lookup"].items()}
    out_rate = {p["name"]: p["output_rate"] for p in sc["projections"]}
    deps_map = {p["name"]: p["deps"] for p in sc["projections"]}
    workload = {p["name"] for p in sc["projections"] if p["is_workload"]}

    points = []
    truncated = False

    def rec(i, pl):
        nonlocal truncated
        if len(points) >= MAX_ENUM:
            truncated = True
            return
        if i == len(order):
            c, l, _ = ex.ref_all_push(pl, dist, local_rate, out_rate, deps_map, order, workload)
            points.append((dict(pl), c, l))
            return
        name = order[i]
        for h in hosts0[name]:
            if all(pl[dep] in d(h) for dep in deps_map[name] if dep in pl):
                pl[name] = h
                rec(i + 1, pl)
                del pl[name]

    rec(0, {})
    return hosts0, points, truncated


def _score(c, l, cmin, cmax, lmin, lmax, alpha):
    cn = (c - cmin) / (cmax - cmin) if cmax > cmin else 0.0
    ln = (l - lmin) / (lmax - lmin) if lmax > lmin else 0.0
    return alpha * cn + (1 - alpha) * ln


def evaluate_scenario(sc):
    order = sc["processing_order"]
    hosts0, points, truncated = _landscape(sc)
    layer = {n["id"]: n["layer"] for n in sc["topology"]["nodes"]}
    cs = [p[1] for p in points]
    ls = [p[2] for p in points]
    cmin, cmax, lmin, lmax = min(cs), max(cs), min(ls), max(ls)

    # Pareto front of distinct (cost, latency) points
    uniq = sorted({(round(c, 3), round(l, 3)) for _, c, l in points})
    front = []
    for c, l in uniq:
        if not front or l < front[-1][1]:
            front.append((c, l))

    # rules of thumb a newcomer might apply
    def rule(pick):
        pl = {}
        for name in order:
            ok = [h for h in hosts0[name]
                  if all(pl[dep] in _desc_of(sc, h) for dep in pl_deps(sc, name) if dep in pl)]
            pl[name] = pick(ok)
        return pl

    heur = {
        "all_cloud": rule(lambda hs: 0),
        "near_sources": rule(lambda hs: max(hs, key=lambda h: (layer[h], -h))),
        "below_cloud": rule(lambda hs: min((h for h in hs if h != 0), key=lambda h: (layer[h], h), default=0)),
    }
    by_key = {tuple(sorted(p.items())): (c, l) for p, c, l in points}
    best = {}
    heur_rank = {}
    for alpha in (0.2, 0.6, 0.9):
        scored = sorted(_score(c, l, cmin, cmax, lmin, lmax, alpha) for _, c, l in points)
        bp = min(points, key=lambda x: _score(x[1], x[2], cmin, cmax, lmin, lmax, alpha))
        best[alpha] = bp[0]
        for hn, pl in heur.items():
            c, l = by_key[tuple(sorted(pl.items()))]
            s = _score(c, l, cmin, cmax, lmin, lmax, alpha)
            heur_rank.setdefault(hn, {})[str(alpha)] = round(s - scored[0], 4)  # 0 == optimal
    best_distinct = len({tuple(sorted(p.items())) for p in best.values()})

    stages = sc["kraken_stages"]
    st_pl = [tuple(sorted(s["placement"].items())) for s in stages]
    st_full = []
    for s in stages:
        edges = tuple(sorted((k, tuple(sorted(v["edges"].items()))) for k, v in s["per_placement"].items()))
        st_full.append((tuple(sorted(s["placement"].items())), edges))
    off_cloud = [sum(1 for v in s["placement"].values() if v != 0) for s in stages]
    return dict(
        subq=len(order),
        hosts={k: len(v) for k, v in hosts0.items()},
        max_hosts=max(len(v) for v in hosts0.values()),
        n_plans=len(points), truncated=truncated,
        pareto=len(front),
        landscape_best_distinct=best_distinct,
        heuristic_gap=heur_rank,
        stage_distinct_nodes=len(set(st_pl)),
        stage_distinct_plans=len(set(st_full)),
        stage_points=[(round(s["cost"], 1), round(s["latency"], 1)) for s in stages],
        stage_comm=[s["comm"] for s in stages],
        stage_nodes=[sorted(set(s["placement"].values())) for s in stages],
        off_cloud=off_cloud,
    )


def _desc_of(sc, h):
    cache = sc.setdefault("_desc", {})
    if h not in cache:
        children = {n["id"]: n["children"] for n in sc["topology"]["nodes"]}
        s, stack = set(), [h]
        while stack:
            x = stack.pop()
            if x not in s:
                s.add(x)
                stack.extend(children[x])
        cache[h] = s
    return cache[h]


def pl_deps(sc, name):
    return next(p["deps"] for p in sc["projections"] if p["name"] == name)


def run_engine(topology_id, spec=None, scenarios=VISIBLE_SCENARIOS):
    """Build every scenario for one topology through the real exporter.
    With `spec`, registers it as an ad-hoc reef_topologies builder first."""
    if spec is not None:
        reef_topologies.BUILDERS[topology_id] = reef_topologies._build(spec["edges"], spec["leaves"], spec["cp"])
    n = len(reef_topologies.BUILDERS[topology_id]()[1])
    topo = dict(id=topology_id, family=topology_id, label=topology_id, network_size=n,
                seed=None, kind="hand_curated")
    out = {}
    for s in scenarios:
        sc, mm = ex.build_scenario(s, topo)
        if mm:
            raise RuntimeError(f"{topology_id}/{s['id']}: reference mismatch {mm}")
        out[s["id"]] = sc
    return out


def evaluate(topology_id, spec=None, scenarios=VISIBLE_SCENARIOS):
    scs = run_engine(topology_id, spec, scenarios)
    return {sid: evaluate_scenario(sc) for sid, sc in scs.items()}, scs


def playable(per_query):
    return {sid: m for sid, m in per_query.items() if MIN_SUBQ <= m["subq"] <= MAX_SUBQ}


def verdict(per_query):
    """Pass/fail against the design goals (over the playable queries only),
    plus a list of what failed."""
    fails = []
    dropped = [sid for sid in per_query if sid not in playable(per_query)]
    per_query = playable(per_query)
    if len(per_query) < MIN_PLAYABLE:
        fails.append(f"only {len(per_query)} playable queries (dropped {dropped})")
    for sid, m in per_query.items():
        if max(m["off_cloud"]) == 0:
            fails.append(f"{sid}: Kraken keeps everything at the cloud")
        if m["n_plans"] < 4:
            fails.append(f"{sid}: only {m['n_plans']} plans")
        if m["max_hosts"] > 8:
            fails.append(f"{sid}: {m['max_hosts']} hosts for one operator")
    q = len(per_query)
    nodes_differ = sum(1 for m in per_query.values() if m["stage_distinct_nodes"] >= 2)
    plans_differ = sum(1 for m in per_query.values() if m["stage_distinct_plans"] >= 2)
    if nodes_differ < 2:
        fails.append(f"Fast/Balanced/Cheap place differently in only {nodes_differ}/{q} queries")
    if plans_differ < q:
        fails.append(f"stages identical (nodes and push/pull) in {q - plans_differ}/{q} queries")
    one_rule = [h for h in ("all_cloud", "near_sources", "below_cloud")
                if all(m["heuristic_gap"][h][a] == 0 for m in per_query.values() for a in ("0.2", "0.6", "0.9"))]
    if one_rule:
        fails.append(f"rule of thumb always optimal: {one_rule}")
    return fails


_PARTITIONS = {(0, 0, 0): "same", (0, 1, 1): "F|BC", (0, 0, 1): "FB|C", (0, 1, 0): "FC|B", (0, 1, 2): "F|B|C"}


def lesson(per_query, sol):
    """What a topology *teaches*, from its solutions rather than its shape --
    two networks that look different but tell the same story should count as
    similar. Per query: which goals share a placement (F|BC = Fast differs
    from Balanced+Cheap, ...), which rule of thumb wins for Fast and for
    Cheap, how much Fast/Cheap keep in the cloud, how many fog nodes the
    Cheap plan spreads over, and the push/pull mix per goal."""
    out = {}
    for sid, m in playable(per_query).items():
        stages = sol[sid]
        keys = [tuple(sorted(s["placement"].items())) for s in stages]
        canon, ids = {}, []
        for k in keys:
            ids.append(canon.setdefault(k, len(canon)))
        part = _PARTITIONS.get(tuple(ids), "other")
        rules = {a: sorted(h for h, g in m["heuristic_gap"].items() if g[a] == 0) for a in ("0.2", "0.9")}
        subq = max(1, m["subq"])
        out[sid] = dict(
            part=part,
            fast_rule=rules["0.2"], cheap_rule=rules["0.9"],
            fast_cloud=sum(1 for v in stages[0]["placement"].values() if v == 0) / subq,
            cheap_cloud=sum(1 for v in stages[2]["placement"].values() if v == 0) / subq,
            cheap_spread=len({v for v in stages[2]["placement"].values() if v != 0}),
            comm=[s["comm"] for s in stages],
            subq=m["subq"],
        )
    return out


def main():
    for tid in sys.argv[1:]:
        per_query, _ = evaluate(tid)
        print(f"=== {tid}")
        for sid, m in per_query.items():
            print(f"  {sid:11s} subq={m['subq']} plans={m['n_plans']:6d} maxhosts={m['max_hosts']} "
                  f"pareto={m['pareto']} stageNodes={m['stage_distinct_nodes']} stagePlans={m['stage_distinct_plans']} "
                  f"offcloud={m['off_cloud']} pts={m['stage_points']} comm={m['stage_comm']}")
        for f in verdict(per_query) or ["PASS"]:
            print("  -", f)


if __name__ == "__main__":
    main()
