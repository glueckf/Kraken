"""Isolated push-pull scoring worker: given a topology id, a query id, a
placement, and (optionally) the player's own push/pull choices, reconstructs
that exact simulation context (same size/seed as export_scenario.py used)
and scores it using Kraken's own CostCalculator.

For a projection with no push choice given, this picks the cheapest
available communication strategy (push vs push-pull) at whatever node the
caller placed it — the same thing the "Sequential" baseline already does for
INEv's placement, generalized to any placement. For a projection where the
player DID make a push/pull call — pushing any subset of its dependencies,
not just one (a raw primitive letter, or an already-placed sub-query
dependency by its own name) — that exact choice is costed instead via
`forced_push_group` (prepp.py / cost_calculator.py, which already accepted
an arbitrary group, not just a single dep) — so a good push/pull call is
rewarded and a bad one costs what it actually costs, rather than always
silently falling back to the optimizer's own pick. Dependency names are
passed through as-is (not flattened to leaf primitives) — PrePP's own
forced-group matching is one-level, so a flattened sub-query name would
silently never match and fall through unnoticed.

Runs as its own process (see server.py) so RNG state from scoring one
topology can never leak into another's reconstruction — the same reason
export_scenario.py isolates each topology into its own subprocess.

Usage: python score_one.py <topology_id> <scenario_id> '<placement-json>' ['<push-choice-json>']
push-choice-json (optional, default "{}"): {projection_name: [primitive_letter, ...]}
— only for projections the player has made an explicit push/pull call on;
any projection missing from it falls back to the optimizer's own choice.
The array can be any subset of that projection's own deps (including empty
— an explicit "pull everything"). The value can also be the string
ALL_PUSH ("__all_push__", mirrors state.ts) for an explicit "push
everything, pull nothing" choice, sent instead of the literal full list —
forcing a single group covering every dependency hits a separate PrePP bug
(cost off by a division-like factor), so that case is costed directly via
the plain all-push strategy instead of forced_push_group.
Prints one JSON line to stdout: {"cost", "latency", "per_placement"} or
{"error": "..."} on failure (exit code 1).
"""
import os
import sys

if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

import io
import json
import random
import contextlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "src")
sys.path.insert(0, REPO)
sys.path.insert(0, SRC)

import simulation_environment as se
from core.query_workload import number_children
from inev.process_combination import compute_dependencies
from kraken.run import _gather_problem_parameters
from kraken.problem import PlacementProblem
import scenarios_def
from topologies import TOPOLOGIES


# Mirrors ALL_PUSH in demo/web/src/state.ts — an explicit "push everything,
# pull nothing" choice, distinct from picking one specific dependency to push.
ALL_PUSH = "__all_push__"


def fail(message: str):
    print(json.dumps({"error": message}))
    sys.exit(1)


def main():
    if len(sys.argv) not in (4, 5):
        fail("usage: score_one.py <topology_id> <scenario_id> <placement-json> ['<push-choice-json>']")

    topology_id, scenario_id, placement_json = sys.argv[1], sys.argv[2], sys.argv[3]
    push_choice_json = sys.argv[4] if len(sys.argv) == 5 else "{}"

    topology = next((t for t in TOPOLOGIES if t["id"] == topology_id), None)
    if topology is None:
        fail(f"unknown topology_id: {topology_id!r}")
    spec = next((s for s in scenarios_def.SCENARIOS if s["id"] == scenario_id), None)
    if spec is None:
        fail(f"unknown scenario_id: {scenario_id!r}")

    try:
        placement = json.loads(placement_json)
    except json.JSONDecodeError as e:
        fail(f"invalid placement JSON: {e}")
    try:
        push_choice = json.loads(push_choice_json)
    except json.JSONDecodeError as e:
        fail(f"invalid push-choice JSON: {e}")

    q = number_children(spec["build"]())
    se.generate_hardcoded_workload = lambda: [q]

    network_size = topology["network_size"]
    if network_size == 12:
        cfg = se.SimulationConfig.create_deterministic(
            network_size=12, num_event_types=6, xi=0.0, cost_weight=0.5,
            latency_threshold=None, output_dataset_name="score_worker",
        )
    else:
        random.seed(topology["seed"])
        np.random.seed(topology["seed"])
        cfg = se.SimulationConfig.create_sized_deterministic(
            network_size=network_size, num_event_types=6, xi=0.0, cost_weight=0.5,
            latency_threshold=None, output_dataset_name="score_worker",
        )

    with contextlib.redirect_stdout(io.StringIO()):
        sim = se.Simulation(cfg)
        sim.run()

    deps_levels = compute_dependencies(sim, sim.h_mycombi, getattr(sim, "h_criticalMSTypes", None))
    order = sorted(deps_levels.keys(), key=lambda x: deps_levels[x])

    missing = [str(p) for p in order if str(p) not in placement]
    if missing:
        fail(f"incomplete placement, missing: {missing}")

    context = _gather_problem_parameters(sim)
    problem = PlacementProblem(order, context)
    s_current = problem.get_initial_candidate()

    per_placement = {}
    with contextlib.redirect_stdout(io.StringIO()):  # CostCalculator prints per-decision debug lines
        for p in order:
            name = str(p)
            node = int(placement[name])
            # The player chooses over `deps` (one level — a raw primitive
            # letter, or an already-placed sub-query dependency). PrePP's
            # forced_push_group matching (prepp.py's `old_copy = query.
            # primitive_operators`) is ITSELF one-level — a sub-query
            # dependency appears as its own name string (e.g. "SEQ(A, B)"),
            # never flattened to its leaf primitives. Passing flattened
            # leaves here (an earlier version of this code did, via
            # `dep_obj.leafs()`) never matches that one-level list, so the
            # forced choice was silently dropped and the optimizer's own
            # pick was scored instead — confirmed 2026-09-08 by comparing
            # against dozens of placements where forcing a sub-query
            # dependency's flattened leaves always reproduced the unforced
            # result exactly, while forcing a raw primitive letter (which
            # already matches one-level) correctly diverged from it. Fixed
            # by passing `chosen_dep` itself, unflattened.
            chosen = push_choice.get(name)
            if chosen == ALL_PUSH:
                # Not routed through forced_push_group at all: forcing a
                # *single* group covering every dependency (i.e. nothing
                # left to pull) hits a separate bug in PrePP's plan-to-
                # acquisition-step conversion — verified cost off by a
                # division-like factor (e.g. 609.0 instead of the true
                # 1827.0) in several placements. `_compute_all_push_costs`
                # (raw_strategies[0], always present and unaffected by
                # forced_push_group) is independently, reliably correct, so
                # use that directly for an explicit "push everything" call.
                strategy_results = problem.cost_calculator.calculate(p, node, s_current, forced_push_group=None)
                best = strategy_results[0]
            elif chosen is not None:
                # Any subset of this projection's deps is a valid forced
                # group, including a single dep (backward-compat: a bare
                # string from an older/manual caller is wrapped) and an
                # explicit empty list ("pull everything" — prepp.py forces
                # this correctly as of the `is not None` fix, not silently
                # falling back to the optimizer's own pick).
                forced_group = [chosen] if isinstance(chosen, str) else list(chosen)
                strategy_results = problem.cost_calculator.calculate(
                    p, node, s_current, forced_push_group=forced_group
                )
                # The player made an explicit push/pull call — cost exactly
                # that choice (last entry = the forced attempt, or the sole
                # all-push entry if push-pull couldn't be computed at all),
                # not whichever strategy happens to be cheapest.
                best = strategy_results[-1]
            else:
                strategy_results = problem.cost_calculator.calculate(p, node, s_current, forced_push_group=None)
                best = min(strategy_results, key=lambda r: r["individual_cost"])
            per_placement[name] = {
                "node": node,
                "strategy": best["strategy"],
                "cost": float(best["individual_cost"]),
            }
            s_current = problem._create_next_candidate(s_current, p, node, best)

    total_latency = s_current.get_critical_path_latency(problem)
    print(json.dumps({
        "cost": float(s_current.cumulative_cost),
        "latency": float(total_latency),
        "per_placement": per_placement,
    }))


if __name__ == "__main__":
    main()
