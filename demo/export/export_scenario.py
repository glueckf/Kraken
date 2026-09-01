"""Offline scenario exporter for the Kraken interactive demo.

Drives the real Python engine (src/) on each curated scenario in a deterministic
configuration, extracts the static tables + all five baseline placements/metrics +
normalization anchors, computes all-push goldens (for the Rust scorer's unit tests),
cross-checks the reference all-push formula against the engine, and writes one
self-contained JSON per scenario into demo/web/scenarios/ plus a manifest.

Run:  python demo/export/export_scenario.py
It re-execs itself with PYTHONHASHSEED=0 so PrePP's str-hash seeding is reproducible.
"""
import os
import sys

# --- make the run byte-reproducible: PrePP seeds random.seed(42 + hash(query)) ---
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

import io
import json
import random
import subprocess
import contextlib
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "src")
OUT_DIR = os.path.join(REPO, "demo", "web", "scenarios")
sys.path.insert(0, REPO)   # so `import src.kraken.run` (used inside run()) resolves
sys.path.insert(0, SRC)    # so `from core...`, `from kraken...`, `from prepp...` resolve

import simulation_environment as se
from core.query_workload import number_children
from inev.process_combination import compute_dependencies
import scenarios_def

SINKS = (0,)
XI = 0.0
COST_WEIGHT = 0.5
FLOAT_TOL = 1e-6

# Three topology sizes sharing the same 4 story queries. "medium" is the
# original hand-built 12-node reef (untouched); "small"/"large" are randomly
# generated (see build_scenario) and only need a stable seed to reproduce.
TOPOLOGIES = [
    dict(id="small", label="Small Reef", network_size=8, seed=1008),
    dict(id="medium", label="Reef", network_size=12, seed=None),
    dict(id="large", label="Grand Reef", network_size=24, seed=1024),
]


# ----------------------------------------------------------------------------
# Reference all-push scorer — mirrors CostCalculator._compute_all_push_costs +
# _add_sink_costs + SolutionCandidate.get_critical_path_latency (xi=0).
# This is the exact model the Rust/WASM client scorer must reproduce.
# ----------------------------------------------------------------------------
def ref_all_push(placement, dist, local_rate, out_rate, deps_map, order, workload):
    """placement: {proj_str: node_id}. Returns (total_cost, max_latency, per_placement)."""
    e2e = {}
    total = 0.0
    per = {}
    for p in order:
        n = placement[p]
        cost = 0.0
        tlat = 0.0
        for dep in deps_map[p]:
            if dep in local_rate:  # primitive event: sum over all its source nodes
                dep_lat = 0.0
                for src, rate in local_rate[dep].items():
                    cost += dist[src][n] * rate
                    dep_lat = max(dep_lat, dist[src][n])
            else:  # already-placed sub-projection: single source = its node
                src = placement[dep]
                cost += dist[src][n] * out_rate[dep]
                dep_lat = dist[src][n]
            tlat = max(tlat, dep_lat)
        if p in workload and n not in SINKS:  # egress to sink(s)
            cost += sum(dist[n][s] for s in SINKS) * out_rate[p]
            tlat += max(dist[n][s] for s in SINKS)
        proc = out_rate[p]
        per[p] = {"cost": cost, "lt": tlat, "lp": proc}
        total += cost
        latest = max([e2e.get(dep, 0.0) for dep in deps_map[p]], default=0.0)
        e2e[p] = XI * proc + tlat + latest
    max_lat = max(e2e.values()) if e2e else 0.0
    return total, max_lat, per


def num(x):
    """Coerce numpy scalars to plain Python numbers."""
    if hasattr(x, "item"):
        return x.item()
    return x


def build_scenario(spec, topology):
    q = number_children(spec["build"]())
    se.generate_hardcoded_workload = lambda: [q]

    network_size = topology["network_size"]
    if network_size == 12:
        # The original 12-node reef: hand-built tree, no RNG involved at all.
        cfg = se.SimulationConfig.create_deterministic(
            network_size=12, num_event_types=6, xi=XI, cost_weight=COST_WEIGHT,
            latency_threshold=None, output_dataset_name="demo_%s" % spec["id"],
        )
    else:
        # A sized-but-random reef. Topology generation draws from both stdlib
        # `random` (parent/edge sampling) and `numpy.random` (event rates/leaf
        # assignment), so both must be seeded right before run() for the
        # export to be byte-reproducible across re-runs.
        random.seed(topology["seed"])
        np.random.seed(topology["seed"])
        cfg = se.SimulationConfig.create_sized_deterministic(
            network_size=network_size, num_event_types=6, xi=XI, cost_weight=COST_WEIGHT,
            latency_threshold=None, output_dataset_name="demo_%s_%s" % (topology["id"], spec["id"]),
        )
    sim = se.Simulation(cfg)
    with contextlib.redirect_stdout(io.StringIO()):
        sim.run()

    letters = list("ABCDEF")
    dist = [[int(sim.allPairs[i][j]) for j in range(len(sim.allPairs))]
            for i in range(len(sim.allPairs))]
    local_rate = {L: {int(nid): float(r) for nid, r in d.items()}
                  for L, d in sim.h_local_rate_lookup.items()}

    # --- projections (the placeable DAG) keyed by str(proj) ---
    workload = {str(qq) for qq in sim.query_workload}
    projrates = {str(k): (float(v[0]), float(v[1])) for k, v in sim.h_projrates.items()}
    out_rate = {name: sr_or[1] for name, sr_or in projrates.items()}
    deps_map = {str(k): [str(x) for x in v] for k, v in sim.h_mycombi.items()}

    deps_levels = compute_dependencies(sim, sim.h_mycombi, getattr(sim, "h_criticalMSTypes", None))
    order = [str(p) for p in sorted(deps_levels.keys(), key=lambda x: deps_levels[x])]
    assert set(order) == set(deps_map), (set(order), set(deps_map))

    projections = []
    for name in order:
        k = next(k for k in sim.h_mycombi if str(k) == name)
        projections.append({
            "name": name,
            "primitives": [str(x) for x in k.leafs()],
            "deps": deps_map[name],
            "selection_rate": projrates[name][0],
            "output_rate": projrates[name][1],
            "is_workload": name in workload,
            "level": int(deps_levels[k]),
        })

    # --- topology nodes ---
    nodes = []
    for n in sim.network:
        cp = n.computational_power
        events = {letters[i]: num(r) for i, r in enumerate(n.eventrates) if r}
        nodes.append({
            "id": int(n.id),
            "layer": int(dist[0][n.id]),
            "computational_power": (None if cp == float("inf") else num(cp)),
            "is_cloud": n.id == 0,
            "is_leaf": len(n.Child) == 0,
            "parents": [int(p.id) for p in n.Parent],
            "children": [int(c.id) for c in n.Child],
            "events": events,
        })

    # --- per-strategy placements + metrics ---
    def all_at_cloud():
        return {name: 0 for name in order}

    def inev_seq_placement():
        pl = all_at_cloud()
        for wrapped in sim.eval_plan[0].projections:
            inner = wrapped.name
            nm = str(inner.name)
            if nm in pl and inner.sinks:
                pl[nm] = int(inner.sinks[0])
        return pl

    g = sim.kraken_results["strategies"]["greedy"]
    kraken_place = {str(pi.projection): int(pi.node) for pi in g["solution"].placements.values()}
    kraken_place = {name: kraken_place.get(name, 0) for name in order}
    kraken_per = {}
    kraken_comm = set()
    for pi in g["solution"].placements.values():
        kraken_per[str(pi.projection)] = {
            "node": int(pi.node), "strategy": pi.strategy,
            "cost": float(pi.individual_cost),
            "lt": float(pi.individual_transmission_latency),
            "lp": float(pi.individual_processing_latency),
        }
        kraken_comm.add(pi.strategy)

    def comm_of(strats):
        s = set(strats)
        return "mixed" if len(s) > 1 else next(iter(s))

    strategies = {
        "all_push": {
            "label": "All-Push", "placement": all_at_cloud(), "comm": "push",
            "cost": float(sim.all_push_results["cost"]),
            "latency": float(sim.all_push_results["transmission_latency"]),
            "processing_latency": float(sim.all_push_results["processing_latency"]),
        },
        "inev": {
            "label": "INEv", "placement": inev_seq_placement(), "comm": "push",
            "cost": float(sim.inev_results["cost"]),
            "latency": float(sim.inev_results["transmission_latency"]),
            "processing_latency": float(sim.inev_results["processing_latency"]),
        },
        "sequential": {
            "label": "Sequential", "placement": inev_seq_placement(), "comm": "push_pull",
            "cost": float(sim.sequential_results["cost"]),
            "latency": float(sim.sequential_results["transmission_latency"]),
            "processing_latency": float(sim.sequential_results["processing_latency"]),
        },
        "prepp": {
            "label": "PrePP", "placement": all_at_cloud(), "comm": "push_pull",
            "cost": float(sim.prepp_from_cloud_result["cost"]),
            "latency": float(sim.prepp_from_cloud_result["transmission_latency"]),
            "processing_latency": float(sim.prepp_from_cloud_result["processing_latency"]),
        },
        "kraken": {
            "label": "Kraken", "placement": kraken_place, "comm": comm_of(kraken_comm),
            "cost": float(g["metrics"]["total_cost"]),
            "latency": float(g["metrics"]["max_latency"]),
            "processing_latency": float(g["metrics"]["cumulative_processing_latency"]),
            "per_placement": kraken_per,
        },
    }

    costs = [s["cost"] for s in strategies.values()]
    lats = [s["latency"] for s in strategies.values()]
    norm_anchors = {"cost_min": min(costs), "cost_max": max(costs),
                    "latency_min": min(lats), "latency_max": max(lats)}

    # --- cross-check: reference all-push must match the engine for Kraken's
    #     all_push placements (the authoritative per-placement cost model) ---
    _, _, ref_per = ref_all_push(kraken_place, dist, local_rate, out_rate, deps_map, order, workload)
    mismatches = []
    for name, info in kraken_per.items():
        if info["strategy"] == "all_push":
            got = ref_per[name]["cost"]
            exp = info["cost"]
            if abs(got - exp) > max(FLOAT_TOL, 1e-4 * abs(exp)):
                mismatches.append((name, got, exp))

    # --- goldens for the Rust scorer (all-push cost+latency for known placements) ---
    golden_placements = {
        "all_at_cloud": all_at_cloud(),
        "inev_placement": inev_seq_placement(),
        "kraken_placement": kraken_place,
    }
    goldens = []
    for gname, pl in golden_placements.items():
        tc, ml, _ = ref_all_push(pl, dist, local_rate, out_rate, deps_map, order, workload)
        goldens.append({"name": gname, "placement": pl,
                        "all_push_cost": tc, "all_push_latency": ml})

    scenario = {
        "schema_version": 1,
        "scenario_id": spec["id"],
        "title": spec["title"],
        "emblem": spec["emblem"],
        "difficulty": spec["difficulty"],
        "blurb": spec["blurb"],
        "query": str(q),
        "config": {"cost_weight": COST_WEIGHT, "xi": XI, "sink_nodes": list(SINKS)},
        "topology": {
            "num_nodes": len(nodes),
            "cloud_node_id": 0,
            "event_letters": letters,
            "nodes": nodes,
            "distance_matrix": dist,
        },
        "event_map": {
            "producers": {L: [int(x) for x in v] for L, v in sim.h_nodes.items()},
            "local_rate_lookup": local_rate,
        },
        "projections": projections,
        "processing_order": order,
        "strategies": strategies,
        "norm_anchors": norm_anchors,
        "goldens": goldens,
    }
    return scenario, mismatches


def _cleanup_junk():
    # side-effect file written into cwd by the INEv placement code
    for junk in ("msFilter.txt",):
        for base in (os.getcwd(), SRC):
            p = os.path.join(base, junk)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def export_one_topology(topology):
    """Build + write all scenarios for a single topology. Returns (manifest_entry, ok)."""
    topo_dir = os.path.join(OUT_DIR, topology["id"])
    os.makedirs(topo_dir, exist_ok=True)
    entry = {
        "id": topology["id"], "label": topology["label"],
        "network_size": topology["network_size"], "scenarios": [],
    }
    ok = True
    for spec in scenarios_def.SCENARIOS:
        print(f"--- exporting {topology['id']}/{spec['id']} ({spec['title']}) ---")
        try:
            scenario, mismatches = build_scenario(spec, topology)
        except Exception as e:
            ok = False
            print(f"  !! FAILED: {e!r}")
            traceback.print_exc()
            continue
        if mismatches:
            ok = False
            print(f"  !! reference/engine all-push mismatch: {mismatches}")
        path = os.path.join(topo_dir, f"{spec['id']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(scenario, f, indent=1, ensure_ascii=False)
        n_sub = len(scenario["processing_order"])
        s = scenario["strategies"]
        print(f"  ok: {n_sub} subqueries | kraken cost={s['kraken']['cost']:.1f} "
              f"lat={s['kraken']['latency']:.1f} | wrote {os.path.relpath(path, REPO)}")
        entry["scenarios"].append({
            "id": spec["id"], "title": spec["title"], "emblem": spec["emblem"],
            "difficulty": spec["difficulty"], "blurb": spec["blurb"],
            "num_subqueries": n_sub, "file": f"{topology['id']}/{spec['id']}.json",
        })
    return entry, ok


_TOPOLOGY_BY_ID = {t["id"]: t for t in TOPOLOGIES}


def main():
    # Child mode: `export_scenario.py <topology-id>` builds just that one
    # topology and writes its manifest fragment. Each topology gets its own
    # fresh interpreter (see the driver below) so RNG state from one topology
    # (random.seed for the sized-random ones) can never leak into another —
    # in particular it can't perturb the untouched, hand-built "medium" reef.
    if len(sys.argv) > 1 and sys.argv[1] in _TOPOLOGY_BY_ID:
        topology = _TOPOLOGY_BY_ID[sys.argv[1]]
        entry, ok = export_one_topology(topology)
        frag_path = os.path.join(OUT_DIR, f".manifest-{topology['id']}.json")
        with open(frag_path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        _cleanup_junk()
        sys.exit(0 if ok else 1)

    # Driver mode: one fresh subprocess per topology, then merge manifests.
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {"topologies": []}
    ok = True
    for topology in TOPOLOGIES:
        print(f"=== topology: {topology['id']} ({topology['network_size']} nodes) ===")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), topology["id"]])
        frag_path = os.path.join(OUT_DIR, f".manifest-{topology['id']}.json")
        if r.returncode != 0 or not os.path.exists(frag_path):
            ok = False
            print(f"  !! subprocess failed for topology {topology['id']} (exit {r.returncode})")
            continue
        with open(frag_path, encoding="utf-8") as f:
            manifest["topologies"].append(json.load(f))
        os.remove(frag_path)

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    n_scenarios = sum(len(t["scenarios"]) for t in manifest["topologies"])
    print(f"\nmanifest: {len(manifest['topologies'])} topologies, "
          f"{n_scenarios} scenarios -> {os.path.relpath(OUT_DIR, REPO)}")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
