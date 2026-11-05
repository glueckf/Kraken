"""Pick a diverse pool from the search archive by farthest-point sampling.

Quality is a gate (pass every design check + score threshold), diversity is the
objective: greedy max-min distance, with the existing curated Reef/Grand Reef
variants as fixed anchors (new picks must also be far from those). Distinct
node counts are capped at PER_N per size so complexity tiers still differ.
"""
import json, os, sys, math
SCR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCR))
os.environ.setdefault("PYTHONHASHSEED", "0")
import importlib.util

K = int(os.environ.get("K", 10))
QMIN = float(os.environ.get("QMIN", 0))
PER_N = int(os.environ.get("PER_N", 2))   # topologies allowed per node count
LETTERS = "ABCDEF"


def wl(spec):
    # same features as topology_lab.wl_histogram, re-implemented to avoid
    # importing the engine here
    edges = {int(k): v for k, v in spec["edges"].items()}
    leaves = {int(k): v for k, v in spec["leaves"].items()}
    n = max(max(edges), *(max(c) for c in edges.values())) + 1
    par = {i: [] for i in range(n)}
    ch = {i: list(edges.get(i, [])) for i in range(n)}
    for p, cs in edges.items():
        for c in cs:
            par[c].append(p)
    lab = {i: "cloud" if i == 0 else ("leaf%d" % len(leaves.get(i, [])) if not ch[i] else "wt") for i in range(n)}
    hist = {}
    for it in range(4):
        for v in lab.values():
            hist[(it, v)] = hist.get((it, v), 0) + 1
        lab = {i: str((lab[i], tuple(sorted("u" + lab[p] for p in par[i])),
                       tuple(sorted("d" + lab[c] for c in ch[i])))) for i in range(n)}
    return hist, n


def cos(a, b):
    dot = sum(a[k] * b.get(k, 0) for k in a)
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


COMM = {"all_push": 0.0, "mixed": 0.5, "push_pull": 1.0}
PARTS = ["same", "FB|C", "FC|B", "F|BC", "F|B|C", "other"]


def jacc(a, b):
    a, b = set(a), set(b)
    return 1 - len(a & b) / len(a | b) if a | b else 0.0


def lesson_dist(la, lb):
    """Distance between what two topologies teach, query by query. A query
    playable on only one of them counts as maximally different."""
    ds = []
    for sid in set(la) | set(lb):
        if sid not in la or sid not in lb:
            ds.append(1.0)
            continue
        x, y = la[sid], lb[sid]
        parts = [
            1.0 if x["part"] != y["part"] else 0.0,
            jacc(x["fast_rule"], y["fast_rule"]),
            jacc(x["cheap_rule"], y["cheap_rule"]),
            abs(x["fast_cloud"] - y["fast_cloud"]),
            abs(x["cheap_cloud"] - y["cheap_cloud"]),
            min(abs(x["cheap_spread"] - y["cheap_spread"]), 3) / 3,
            sum(abs(COMM[p] - COMM[q]) for p, q in zip(x["comm"], y["comm"])) / 3,
            abs(x["subq"] - y["subq"]) / 3,
        ]
        w = [2, 1, 1, 1, 1, 0.5, 1, 0.5]
        ds.append(sum(p * q for p, q in zip(parts, w)) / sum(w))
    return sum(ds) / len(ds)


def feats(rec):
    import topology_lab as lab
    h, n = wl(rec["spec"])
    return dict(h=h, n=n, les=lab.lesson(rec["per_query"], rec["sol"]))


def dist(a, b):
    dg = 1 - cos(a["h"], b["h"])
    dl = lesson_dist(a["les"], b["les"])
    dn = abs(a["n"] - b["n"]) / 23
    return 0.6 * dl + 0.25 * dg + 0.15 * dn


def main():
    recs, seen = [], set()
    for line in open(os.path.join(SCR, "archive.jsonl")):
        r = json.loads(line)
        if not r.get("per_query") or r["score"] < QMIN:
            continue
        import topology_lab as lab
        if lab.verdict(r["per_query"]):
            continue
        sp = r["spec"]
        issues = lab.layout_issues(sp["edges"], sp["leaves"], min_visible=10)
        behind = {i.split(" runs")[0] for i in issues if "runs behind" in i}
        if len(issues) != sum("runs behind" in i for i in issues) or len(behind) > 0.15 * sum(len(v) for v in sp["edges"].values()):
            continue
        if sum(1 for v in sp["leaves"].values() if len(v) > 1) < max(2, math.ceil(0.35 * len(sp["leaves"]))):
            continue
        key = json.dumps(r["spec"], sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        recs.append(r)
    anchors = []
    ap = os.path.join(SCR, "anchors.jsonl")
    if os.path.exists(ap):
        anchors = [json.loads(l) for l in open(ap)]
    print(f"pool: {len(recs)} passing unique candidates, {len(anchors)} anchors")
    F = [feats(r) for r in recs]
    A = [feats(a) for a in anchors]
    # start from whatever is farthest from the curated anchors, not the best
    # score -- otherwise the first pick is always the most common lesson
    chosen = [max(range(len(recs)), key=lambda i: (min(dist(F[i], a) for a in A) if A else 0, recs[i]["score"]))]
    used_n = {F[chosen[0]]["n"]: 1}
    while len(chosen) < K:
        best, bd = None, -1
        for i in range(len(recs)):
            if i in chosen or used_n.get(F[i]["n"], 0) >= PER_N:
                continue
            d = min([dist(F[i], F[j]) for j in chosen] + [dist(F[i], a) for a in A])
            if d > bd:
                best, bd = i, d
        if best is None:
            break
        chosen.append(best)
        used_n[F[best]["n"]] = used_n.get(F[best]["n"], 0) + 1
        print(f"  pick n={F[best]['n']:2d} score={recs[best]['score']:.1f} min-dist={bd:.3f}")
    out = [recs[i] for i in sorted(chosen, key=lambda i: F[i]["n"])]
    json.dump(out, open(os.path.join(SCR, "pool.json"), "w"))
    for r in out:
        pq = r["per_query"]
        print(f"n={wl(r['spec'])[1]:2d} score={r['score']:5.1f} cell={r['cell']} arche={r['cand'].get('arche')} "
              + " ".join(f"{sid[:6]}:sq{m['subq']}/h{m['max_hosts']}/{l['part']}/{','.join(c[:2] for c in l['comm'])}"
                         for sid, m, l in ((s, pq[s], f["les"][s]) for f in [feats(r)] for s in f["les"])))


if __name__ == "__main__":
    main()
