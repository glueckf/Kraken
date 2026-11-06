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
from kraken.run import run_kraken_solver
import scenarios_def
from topologies import TOPOLOGIES
import reef_topologies

SINKS = (0,)
XI = 0.0
COST_WEIGHT = 0.5
FLOAT_TOL = 1e-6

# Player-facing "alpha" simplification: rather than exposing the raw 0-1
# cost/latency balance as a number, the demo offers these three named stages.
# Unlike the four other baselines (whose placement algorithms don't depend on
# cost_weight at all -- see BACKLOG.md item #17), Kraken's own greedy search
# genuinely chooses a different placement depending on this weight, so each
# stage needs its own real Kraken run, not just a re-normalized score.
#
# Balanced was 0.6 until 2026-11-06. At 0.6 Kraken's Balanced plan was the
# same as Cheap's in 45 of 65 reef queries, and players beat Kraken in 55 of
# them; at 0.5 Balanced differs from Cheap everywhere (BACKLOG.md item 38).
KRAKEN_STAGES = [
    (0.2, "Fast"),
    (0.5, "Balanced"),
    (0.9, "Cheap"),
]
# Kraken's Forge (the paper example) keeps Balanced at 0.6 for now
# (factory_example.DEFAULT_ALPHA) -- to be revisited, see item 38.
FORGE_STAGES = [
    (0.2, "Fast"),
    (0.6, "Balanced"),
    (0.9, "Cheap"),
]


# ----------------------------------------------------------------------------
# Reference all-push scorer — mirrors CostCalculator._compute_all_push_costs +
# _add_sink_costs + SolutionCandidate.get_critical_path_latency (xi=0).
# This is the exact model the Rust/WASM client scorer must reproduce.
# ----------------------------------------------------------------------------
def ref_all_push(placement, dist, local_rate, out_rate, deps_map, order, workload):
    """placement: {proj_str: node_id}. Returns (total_cost, max_latency, per_placement).

    Inputs arrive in parallel: each at ready(input) + hops, a primitive being
    ready at 0 at its sources, a sub-projection once its own inputs are in
    (sink egress is not part of ready)."""
    ready, e2e = {}, {}
    total = 0.0
    per = {}
    for p in order:
        n = placement[p]
        cost = 0.0
        tlat = 0.0
        arrival = 0.0
        for dep in deps_map[p]:
            if dep in local_rate:  # primitive event: sum over all its source nodes
                dep_lat = 0.0
                for src, rate in local_rate[dep].items():
                    cost += dist[src][n] * rate
                    dep_lat = max(dep_lat, dist[src][n])
                arrival = max(arrival, dep_lat)
            else:  # already-placed sub-projection: single source = its node
                src = placement[dep]
                cost += dist[src][n] * out_rate[dep]
                dep_lat = dist[src][n]
                arrival = max(arrival, ready[dep] + dep_lat)
            tlat = max(tlat, dep_lat)
        egress = 0.0
        if p in workload and n not in SINKS:  # egress to sink(s)
            cost += sum(dist[n][s] for s in SINKS) * out_rate[p]
            egress = max(dist[n][s] for s in SINKS)
            tlat += egress
        proc = out_rate[p]
        per[p] = {"cost": cost, "lt": tlat, "lp": proc}
        total += cost
        ready[p] = XI * proc + arrival
        e2e[p] = ready[p] + egress
    max_lat = max(e2e.values()) if e2e else 0.0
    return total, max_lat, per


def num(x):
    """Coerce numpy scalars to plain Python numbers."""
    if hasattr(x, "item"):
        return x.item()
    return x


def extract_static_tables(sim):
    """Topology, rates and the placeable projection DAG of a set-up Simulation,
    in the scenario-JSON shape the frontend and the Rust scorer read."""
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
    return {"letters": letters, "dist": dist, "local_rate": local_rate, "workload": workload,
            "out_rate": out_rate, "deps_map": deps_map, "order": order,
            "projections": projections, "nodes": nodes}


def summarize_kraken_run(g, order):
    """Extract {placement, per_placement, comm} from one greedy-search result
    (`sim.kraken_results["strategies"]["greedy"]`, or the same shape from a
    fresh `run_kraken_solver` call at a different cost_weight)."""
    placement = {str(pi.projection): int(pi.node) for pi in g["solution"].placements.values()}
    placement = {name: placement.get(name, 0) for name in order}
    per_placement = {}
    comm = set()
    for pi in g["solution"].placements.values():
        # Per-dependency push/pull: each AcquisitionStep names which of this
        # placement's deps it acquires (`events_to_pull`) and whether that
        # happened via push or pull (`is_push_based`, false once a
        # PullRequest with events is attached). Verified empirically against
        # a real run: for SEQ(A,B) (strategy="push_pull"), step 0 acquires B
        # with pull_request=None (pushed), step 1 acquires A with
        # pull_request.events=['B'] (A is pulled, using already-received B as
        # a semi-join filter) -- confirming the dep actually being acquired
        # in a step is `events_to_pull`, not `pull_request.events` (that
        # names the filter events sent along with the request, not the
        # dep being fetched).
        edges = {}
        for step in pi.acquisition_steps.steps:
            label = "push" if step.is_push_based else "pull"
            for dep in step.events_to_pull:
                edges[str(dep)] = label
        per_placement[str(pi.projection)] = {
            "node": int(pi.node), "strategy": pi.strategy,
            "cost": float(pi.individual_cost),
            "lt": float(pi.individual_transmission_latency),
            "lp": float(pi.individual_processing_latency),
            "edges": edges,
        }
        comm.add(pi.strategy)
    return placement, per_placement, comm


def comm_of(strats):
    s = set(strats)
    return "mixed" if len(s) > 1 else next(iter(s))


def build_scenario(spec, topology):
    q = number_children(spec["build"]())
    se.generate_hardcoded_workload = lambda: [q]

    network_size = topology["network_size"]
    kind = topology.get("kind")
    if kind == "hardcoded":
        # The original 12-node reef: hand-built tree, no RNG involved at all.
        cfg = se.SimulationConfig.create_deterministic(
            network_size=12, num_event_types=6, xi=XI, cost_weight=COST_WEIGHT,
            latency_threshold=None, output_dataset_name="demo_%s" % spec["id"],
        )
        with contextlib.redirect_stdout(io.StringIO()):
            sim = se.Simulation(cfg)
            sim.run()
    elif kind == "hand_curated":
        # A different hand-built tree (reef_topologies.py), also no RNG --
        # see topologies.py's module docstring for why these exist instead
        # of more random ones.
        cfg = se.SimulationConfig.create_deterministic(
            network_size=network_size, num_event_types=6, xi=XI, cost_weight=COST_WEIGHT,
            latency_threshold=None, output_dataset_name="demo_%s_%s" % (topology["id"], spec["id"]),
        )
        with reef_topologies.curated_tree(topology["id"]), contextlib.redirect_stdout(io.StringIO()):
            sim = se.Simulation(cfg)
            sim.run()
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
        with contextlib.redirect_stdout(io.StringIO()):
            sim = se.Simulation(cfg)
            sim.run()

    tables = extract_static_tables(sim)
    dist, local_rate, workload = tables["dist"], tables["local_rate"], tables["workload"]
    out_rate, deps_map, order = tables["out_rate"], tables["deps_map"], tables["order"]
    projections, nodes, letters = tables["projections"], tables["nodes"], tables["letters"]

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
    kraken_place, kraken_per, kraken_comm = summarize_kraken_run(g, order)

    # --- per-alpha Kraken stages (see KRAKEN_STAGES) ---
    # Unlike All-Push/INEv/Sequential/PrePP -- single deterministic algorithms
    # whose placement never depends on cost_weight, only their displayed score
    # does -- Kraken's greedy search genuinely picks a different placement per
    # alpha, so each stage needs its own real run. The COST_WEIGHT stage reuses
    # the run already done above instead of repeating it.
    kraken_stages = []
    for alpha, label in KRAKEN_STAGES:
        if alpha == COST_WEIGHT:
            stage_g = g
        else:
            sim.config.cost_weight = alpha
            with contextlib.redirect_stdout(io.StringIO()):
                stage_result = run_kraken_solver(
                    sim, strategies_to_run=[{"name": "greedy"}], compare_within_kraken=False
                )
            stage_g = stage_result["strategies"]["greedy"]
        stage_place, stage_per, stage_comm = summarize_kraken_run(stage_g, order)
        kraken_stages.append({
            "alpha": alpha,
            "label": label,
            "placement": stage_place,
            "comm": comm_of(stage_comm),
            "cost": float(stage_g["metrics"]["total_cost"]),
            "latency": float(stage_g["metrics"]["max_latency"]),
            "processing_latency": float(stage_g["metrics"]["cumulative_processing_latency"]),
            "per_placement": stage_per,
            # Wall time of Kraken's search on the export machine (the engine's
            # own execution_time_seconds: strategy.solve() only), shown
            # against the player's decision time. Measured, so every
            # re-export changes it slightly.
            "solve_seconds": float(stage_g["execution_time_seconds"]),
        })
    sim.config.cost_weight = COST_WEIGHT

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

    # Anchors must span every Kraken stage too, not just the 5 baseline rows --
    # a pure-latency (alpha=0) or pure-cost (alpha=1) stage can land outside the
    # 0.5-stage's own cost/latency, and the Rust normalizer only clamps the low
    # side (norm() floors at 0, never ceils), so an un-anchored high value would
    # display as an out-of-range score instead of a merely-unsurprising one.
    costs = [s["cost"] for s in strategies.values()] + [s["cost"] for s in kraken_stages]
    lats = [s["latency"] for s in strategies.values()] + [s["latency"] for s in kraken_stages]
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
        "schema_version": 2,
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
        "kraken_stages": kraken_stages,
        "norm_anchors": norm_anchors,
        "goldens": goldens,
    }
    return scenario, mismatches


FACTORY_SCENARIO = dict(
    id="factory_join",
    title=None,  # filled from factory_example.QUERY_TITLE
    emblem="factory",
    difficulty=1,
    blurb="The paper's factory example: one join, two valid fog nodes plus the cloud, "
          "and a push/pull choice that decides which node is best.",
)


def build_factory_scenario(topology):
    """The paper's motivating example (factory_example.py) as a scenario JSON.

    Everything numeric comes from the engine: the 6-cell decision table is
    Kraken's CostCalculator on clean inputs, Kraken's plan per stage is a real
    run_kraken_solver call, All-Push and PrePP come from Simulation.run(), and
    Sequential is Example 1's two-step planner evaluated on the same table
    with the same score F. The paper's own formulas (paper_cost_model) are
    recomputed alongside as a cross-check; any disagreement is a mismatch.
    """
    import factory_example as fx

    spec = dict(FACTORY_SCENARIO, title=fx.QUERY_TITLE)
    base_sim = fx.run_baselines(output_dataset_name="demo_%s_%s" % (topology["id"], spec["id"]))
    clean_sim = fx.fresh_simulation(fx.DEFAULT_ALPHA)
    with fx.factory_model():
        tables = extract_static_tables(clean_sim)
    order, deps_map = tables["order"], tables["deps_map"]
    assert len(order) == 1, order
    p = order[0]

    pool = fx.enumerate_decisions(clean_sim)
    mismatches = []
    for d in pool:
        ref = fx.paper_cost_model(d["node"], d["scheme"])
        d["paper"] = {"cost": ref["cost"], "latency": ref["latency"]}
        if abs(ref["cost"] - d["cost"]) > FLOAT_TOL or abs(ref["latency"] - d["latency"]) > FLOAT_TOL:
            mismatches.append(("paper-model", d["node"], d["scheme"], d["cost"], ref["cost"],
                               d["latency"], ref["latency"]))
        if "forced_cost" in d and abs(d["forced_cost"] - d["cost"]) > FLOAT_TOL:
            mismatches.append(("forced-vs-free push-pull", d["node"], d["forced_cost"], d["cost"]))
    cell = {(d["node"], d["scheme"]): d for d in pool}

    # all-push cells must also agree with the Rust/WASM all-push reference
    for d in pool:
        if d["scheme"] != "all_push":
            continue
        tc, ml, _ = ref_all_push({p: d["node"]}, tables["dist"], tables["local_rate"],
                                 tables["out_rate"], deps_map, order, tables["workload"])
        if abs(tc - d["cost"]) > FLOAT_TOL or abs(ml - d["latency"]) > FLOAT_TOL:
            mismatches.append(("ref_all_push", d["node"], tc, d["cost"], ml, d["latency"]))

    def plan(d, label):
        return {
            "label": label, "placement": {p: d["node"]},
            "comm": "push" if d["scheme"] == "all_push" else "push_pull",
            "cost": d["cost"], "latency": d["latency"],
            "processing_latency": d.get("processing_latency", 0.0),
            "decision": {"node": d["node"], "scheme": d["scheme"]},
        }

    def kraken_entry(alpha, label):
        _, g = fx.run_kraken(alpha, output_dataset_name="demo_factory_kraken")
        place, per, comm = summarize_kraken_run(g, order)
        node = place[p]
        scheme = per[p]["strategy"]
        d = cell.get((node, scheme))
        if d is None or abs(d["cost"] - float(g["metrics"]["total_cost"])) > FLOAT_TOL:
            mismatches.append(("kraken-vs-table", alpha, node, scheme, float(g["metrics"]["total_cost"])))
        return {
            "alpha": alpha, "label": label, "placement": place, "comm": comm_of(comm),
            "cost": float(g["metrics"]["total_cost"]),
            "latency": float(g["metrics"]["max_latency"]),
            "processing_latency": float(g["metrics"]["cumulative_processing_latency"]),
            "per_placement": per,
            "solve_seconds": float(g["execution_time_seconds"]),  # see build_scenario
        }

    def analysis(alpha):
        opt = fx.reference_optimum(pool, alpha)
        seq = fx.sequential_plan(pool, alpha)
        apb = fx.all_push_best(pool, alpha)
        return {
            "alpha": alpha,
            "scores": [{"node": d["node"], "scheme": d["scheme"],
                        "score": fx.score_F(d["cost"], d["latency"], pool, alpha)} for d in pool],
            "reference_optimum": {"node": opt["node"], "scheme": opt["scheme"],
                                  "cost": opt["cost"], "latency": opt["latency"]},
            "all_push_best": {"node": apb["node"], "scheme": apb["scheme"],
                              "cost": apb["cost"], "latency": apb["latency"]},
            "sequential": plan(seq, "Sequential"),
        }

    kraken_stages = []
    for alpha, label in FORGE_STAGES:
        st = kraken_entry(alpha, label)
        st["analysis"] = analysis(alpha)
        opt = st["analysis"]["reference_optimum"]
        st["matches_reference"] = (st["placement"][p] == opt["node"]
                                   and st["per_placement"][p]["strategy"] == opt["scheme"])
        kraken_stages.append(st)
    default = next(s for s in kraken_stages if s["alpha"] == fx.DEFAULT_ALPHA)

    ap_c, pp_c = cell[(fx.CLOUD, "all_push")], cell[(fx.CLOUD, "push_pull")]
    if abs(float(base_sim.all_push_results["cost"]) - ap_c["cost"]) > FLOAT_TOL:
        mismatches.append(("all_push baseline", base_sim.all_push_results["cost"], ap_c["cost"]))
    if abs(float(base_sim.prepp_from_cloud_result["cost"]) - pp_c["cost"]) > FLOAT_TOL:
        mismatches.append(("prepp baseline", base_sim.prepp_from_cloud_result["cost"], pp_c["cost"]))

    strategies = {
        "all_push": {
            "label": "All-Push", "placement": {p: 0}, "comm": "push",
            "cost": float(base_sim.all_push_results["cost"]),
            "latency": float(base_sim.all_push_results["transmission_latency"]),
            "processing_latency": float(base_sim.all_push_results["processing_latency"]),
        },
        "prepp": {
            "label": "PrePP", "placement": {p: 0}, "comm": "push_pull",
            "cost": float(base_sim.prepp_from_cloud_result["cost"]),
            "latency": float(base_sim.prepp_from_cloud_result["transmission_latency"]),
            "processing_latency": float(base_sim.prepp_from_cloud_result["processing_latency"]),
        },
        # Example 1's sequential planner on the same table and F as Kraken
        # (not the engine's INEv+PrePP pipeline, whose INEv step uses its own
        # placement cost model — see FACTORY_ROUND.md).
        "sequential": default["analysis"]["sequential"],
        "kraken": {k: default[k] for k in ("label", "placement", "comm", "cost", "latency",
                                           "processing_latency", "per_placement")},
    }
    strategies["kraken"]["label"] = "Kraken"

    # Score anchors = the candidate pool C of Sec. 4.3.2, so the displayed
    # score is exactly the paper's F(s) for every decision.
    norm_anchors = {"cost_min": min(d["cost"] for d in pool), "cost_max": max(d["cost"] for d in pool),
                    "latency_min": min(d["latency"] for d in pool),
                    "latency_max": max(d["latency"] for d in pool)}

    goldens = []
    for n in sorted({d["node"] for d in pool}):
        tc, ml, _ = ref_all_push({p: n}, tables["dist"], tables["local_rate"], tables["out_rate"],
                                 deps_map, order, tables["workload"])
        goldens.append({"name": f"all_push_at_{n}", "placement": {p: n},
                        "all_push_cost": tc, "all_push_latency": ml})

    scenario = {
        "schema_version": 2,
        "scenario_id": spec["id"],
        "title": spec["title"],
        "emblem": spec["emblem"],
        "difficulty": spec["difficulty"],
        "blurb": spec["blurb"],
        "query": str(p),
        "config": {"cost_weight": fx.DEFAULT_ALPHA, "xi": XI, "sink_nodes": list(SINKS)},
        "topology": {
            "num_nodes": len(tables["nodes"]),
            "cloud_node_id": 0,
            "event_letters": tables["letters"],
            "nodes": tables["nodes"],
            "distance_matrix": tables["dist"],
        },
        "event_map": {
            "producers": {L: [int(x) for x in v] for L, v in clean_sim.h_nodes.items()},
            "local_rate_lookup": tables["local_rate"],
        },
        "projections": tables["projections"],
        "processing_order": order,
        "strategies": strategies,
        "kraken_stages": kraken_stages,
        "norm_anchors": norm_anchors,
        "goldens": goldens,
        # --- paper-example round only (frontend: state.ts isPaperRound) ---
        "paper_round": {
            "source": "Kraken_DEBS_Long_Version.pdf — Example 1–4, Fig. 1, Fig. 3, Sec. 4.3",
            "node_labels": {str(k): v for k, v in fx.NODE_LABEL.items()},
            "inputs": {
                "rates": fx.RATES, "selectivity_AB": fx.SELECTIVITY_AB,
                "conditional_selectivities": fx.CONDITIONAL_SELECTIVITIES,
                "output_rate": tables["projections"][0]["output_rate"],
                "edges": [[c, par] for c, par in fx.PARENT.items()],
                "sink": fx.CLOUD, "xi": XI,
            },
            # The decision space a player can build with the free
            # per-dependency push/pull chips (panel.ts renderPushPullRow) --
            # three of the four subsets of {A, B}: the paper's own two named
            # schemes, plus push_a. Not pull_both ("push neither"): this
            # round has no pull-all quick button and score_one.py's
            # paper_round validation rejects an empty push group -- pulling
            # needs an already-pushed tuple to filter against, so "pull
            # everything" has nothing to filter with (see the ALL_SCHEMES
            # comment in factory_example.py). Used by state.ts (paperScheme)
            # to match a chosen push set back to its decision_table row, by
            # exact push-array equality.
            "comm_options": [
                {"id": "all_push", "push": ["A", "B"], "pull": []},
                {"id": "push_pull", "push": list(fx.PUSH_PULL_PUSHED), "pull": ["A"]},
                {"id": "push_a", "push": list(fx.PUSH_A), "pull": ["B"]},
            ],
            "decision_table": pool,
            "default_alpha": fx.DEFAULT_ALPHA,
        },
    }
    return scenario, mismatches, spec


def export_factory_topology(topology):
    topo_dir = os.path.join(OUT_DIR, topology["id"])
    os.makedirs(topo_dir, exist_ok=True)
    entry = {"id": topology["id"], "family": topology.get("family", topology["id"]),
             "label": topology["label"], "label_de": topology.get("label_de", topology["label"]),
             "network_size": topology["network_size"], "scenarios": []}
    print(f"--- exporting {topology['id']}/{FACTORY_SCENARIO['id']} (paper example) ---")
    try:
        scenario, mismatches, spec = build_factory_scenario(topology)
    except Exception as e:
        print(f"  !! FAILED: {e!r}")
        traceback.print_exc()
        return entry, False
    ok = not mismatches
    if mismatches:
        print(f"  !! cross-check mismatches: {mismatches}")
    path = os.path.join(topo_dir, f"{spec['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scenario, f, indent=1, ensure_ascii=False)
    for d in scenario["paper_round"]["decision_table"]:
        print(f"  node {d['node']} {d['scheme']:9s} V={d['cost']:7.1f} L={d['latency']:.0f}")
    for st in scenario["kraken_stages"]:
        a = st["analysis"]
        print(f"  alpha={st['alpha']}: Kraken {st['placement']} {st['comm']} V={st['cost']:.1f} L={st['latency']:.0f} | "
              f"enumeration optimum {a['reference_optimum']['node']}/{a['reference_optimum']['scheme']} | "
              f"sequential {a['sequential']['decision']} | all-push best node {a['all_push_best']['node']}")
    entry["scenarios"].append({
        "id": spec["id"], "title": spec["title"], "emblem": spec["emblem"],
        "difficulty": spec["difficulty"], "blurb": spec["blurb"],
        "num_subqueries": len(scenario["processing_order"]),
        "file": f"{topology['id']}/{spec['id']}.json",
    })
    return entry, ok


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


def export_one_topology(topology, only=None):
    """Build + write all scenarios for a single topology (or just the one with
    id `only`). Returns (manifest_entry, ok)."""
    topo_dir = os.path.join(OUT_DIR, topology["id"])
    os.makedirs(topo_dir, exist_ok=True)
    entry = {
        "id": topology["id"], "family": topology.get("family", topology["id"]),
        "label": topology["label"], "label_de": topology.get("label_de", topology["label"]),
        "network_size": topology["network_size"], "scenarios": [],
    }
    ok = True
    # A topology may list the queries it offers (topologies.py `scenarios`):
    # the designed ones keep only queries that decompose into 2-5 operators
    # on that network (see topology_lab.py).
    wanted = topology.get("scenarios")
    for spec in scenarios_def.SCENARIOS:
        if wanted is not None and spec["id"] not in wanted:
            continue
        if only is not None and spec["id"] != only:
            continue
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


def _fragment_path(topology_id, scenario_id):
    suffix = f"-{scenario_id}" if scenario_id else ""
    return os.path.join(OUT_DIR, f".manifest-{topology_id}{suffix}.json")


def main():
    # Child mode: `export_scenario.py <topology-id> [<scenario-id>]` builds
    # that topology (or just that one of its scenarios) and writes its
    # manifest fragment. Every scenario gets its own fresh interpreter (see
    # the driver below), for two reasons:
    #   - RNG state from one topology (random.seed for the sized-random ones)
    #     can never leak into another -- in particular it can't perturb the
    #     untouched, hand-built "medium" reef.
    #   - INES's Simulation keeps its projection lists and decomposition
    #     dicts at class level (h_projlist, h_combiDict, ...), shared by every
    #     instance in a process. A query built after another one in the same
    #     process can pick up the earlier query's projections as operators:
    #     the retired Grand Reef's Q5 shipped two of Q4's (BACKLOG.md #32).
    if len(sys.argv) > 1 and sys.argv[1] in _TOPOLOGY_BY_ID:
        topology = _TOPOLOGY_BY_ID[sys.argv[1]]
        only = sys.argv[2] if len(sys.argv) > 2 else None
        if topology.get("kind") == "paper_example":
            entry, ok = export_factory_topology(topology)
        else:
            entry, ok = export_one_topology(topology, only)
        with open(_fragment_path(topology["id"], only), "w", encoding="utf-8") as f:
            json.dump(entry, f)
        _cleanup_junk()
        sys.exit(0 if ok else 1)

    # Driver mode: one fresh subprocess per scenario, then merge manifests.
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {"topologies": []}
    ok = True
    for topology in TOPOLOGIES:
        print(f"=== topology: {topology['id']} ({topology['network_size']} nodes) ===")
        if topology.get("kind") == "paper_example":
            parts = [None]   # one fixed scenario, built by its own code path
        else:
            wanted = topology.get("scenarios")
            parts = [s["id"] for s in scenarios_def.SCENARIOS if wanted is None or s["id"] in wanted]
        entry, topology_ok = None, True
        for scenario_id in parts:
            r = subprocess.run([sys.executable, os.path.abspath(__file__), topology["id"]]
                               + ([scenario_id] if scenario_id else []))
            frag_path = _fragment_path(topology["id"], scenario_id)
            if r.returncode != 0 or not os.path.exists(frag_path):
                topology_ok = False
                print(f"  !! subprocess failed for {topology['id']}/{scenario_id or '*'} (exit {r.returncode})")
                continue
            with open(frag_path, encoding="utf-8") as f:
                part = json.load(f)
            os.remove(frag_path)
            if entry is None:
                entry = part
            else:
                entry["scenarios"].extend(part["scenarios"])
        if not topology_ok:
            ok = False
            continue
        manifest["topologies"].append(entry)

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    n_scenarios = sum(len(t["scenarios"]) for t in manifest["topologies"])
    print(f"\nmanifest: {len(manifest['topologies'])} topologies, "
          f"{n_scenarios} scenarios -> {os.path.relpath(OUT_DIR, REPO)}")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
