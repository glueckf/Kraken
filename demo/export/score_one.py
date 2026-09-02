"""Isolated push-pull scoring worker: given a topology id, a query id, and a
placement, reconstructs that exact simulation context (same size/seed as
export_scenario.py used) and scores the placement using Kraken's own
CostCalculator — for each projection, in dependency order, the cheapest
available communication strategy (push vs push-pull) at whatever node the
caller placed it. This is exactly what the "Sequential" baseline already
does for INEv's placement, generalized to any placement.

Runs as its own process (see server.py) so RNG state from scoring one
topology can never leak into another's reconstruction — the same reason
export_scenario.py isolates each topology into its own subprocess.

Usage: python score_one.py <topology_id> <scenario_id> '<placement-json>'
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


def fail(message: str):
    print(json.dumps({"error": message}))
    sys.exit(1)


def main():
    if len(sys.argv) != 4:
        fail("usage: score_one.py <topology_id> <scenario_id> <placement-json>")

    topology_id, scenario_id, placement_json = sys.argv[1], sys.argv[2], sys.argv[3]

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
            strategy_results = problem.cost_calculator.calculate(p, node, s_current)
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
