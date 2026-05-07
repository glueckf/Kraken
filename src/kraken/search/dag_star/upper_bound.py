"""Upper-bound computation for DAG* pruning.

Uses the simulation's pre-computed ``prepp_from_cloud_result`` as the prune
ceiling. That call (``simulation_environment.calculate_prepp_from_cloud``)
runs PrePP **once** for the entire workload pinned to the cloud sink, so it
gets the benefit of cross-projection acquisition optimisation that
``cost_calculator.calculate`` cannot see when invoked per projection. The
returned cost is the actual cost of a feasible deployment of the all-cloud
plan, which is a valid upper bound on the cost-optimal placement.

We still construct a per-projection fallback ``SolutionCandidate`` so that
``DagStarSearch`` has a concrete plan to return in the (rare) case that the
heap empties without a goal being dequeued.

Caveat: the pre-computed cost is in PrePP's globally-optimised cost model,
while the search's heap keys (``cumulative_cost`` from
``cost_calculator.calculate``) are in the per-projection cost model. The
per-projection model is generally an over-estimate of the global model for
the same plan, so this prune ceiling is *tighter* than the per-projection
cloud cost would be. Correctness rests on the assumption that the search's
optimum cost is bounded above by the global cloud cost — an assumption that
holds when both costs faithfully measure the same network-traffic metric.
"""

from typing import TYPE_CHECKING, Any, Optional, Tuple

if TYPE_CHECKING:
    from kraken.problem import PlacementProblem
    from kraken.data.state import SolutionCandidate


def compute_prepp_cloud_upper_bound(
    problem: "PlacementProblem",
) -> Tuple[float, Optional["SolutionCandidate"]]:
    """Return ``(cost, fallback_state)`` for the cloud-pinned plan.

    The cost comes from ``simulation_environment.calculate_prepp_from_cloud``
    (already executed by the simulation harness before kraken runs); the
    fallback state is constructed by walking the search's own cost pipeline
    so that ``DagStarSearch`` has a concrete plan to return when the heap
    drains without a goal.

    Returns ``(inf, None)`` when the cloud baseline is infeasible (no PrePP
    result available, or latency-violating), which disables upper-bound
    pruning in the strategy.
    """
    sink_nodes = problem.cost_calculator.params["sink_nodes"]
    if not sink_nodes:
        return float("inf"), None

    bound_cost = _read_prepp_from_cloud_cost(problem)
    if bound_cost is None:
        return float("inf"), None

    fallback = _build_cloud_fallback_state(problem, sink_nodes[0])
    if fallback is None:
        return float("inf"), None
    if fallback.get_critical_path_latency(problem) > problem.latency_threshold:
        return float("inf"), None

    return float(bound_cost), fallback


def _read_prepp_from_cloud_cost(problem: "PlacementProblem") -> Optional[float]:
    """Extract the cost from the pre-computed PrePP-from-cloud result, if any."""
    result: Any = problem.cost_calculator.params.get("prepp_from_cloud_result")
    if not isinstance(result, dict):
        return None
    if result.get("status") != "success":
        return None
    cost = result.get("cost")
    if cost is None:
        return None
    try:
        return float(cost)
    except (TypeError, ValueError):
        return None


def _build_cloud_fallback_state(
    problem: "PlacementProblem", sink: int
) -> Optional["SolutionCandidate"]:
    """Construct a fully-placed cloud-pinned ``SolutionCandidate``.

    Walks ``cost_calculator.calculate`` projection-by-projection at the sink,
    using ``_create_next_candidate`` to update the event stack between
    iterations so downstream projections see local-event availability the
    same way ``expand`` would.
    """
    state = problem.get_initial_candidate()
    for p in problem.processing_order:
        results = problem.cost_calculator.calculate(p, sink, state)
        if not results:
            return None
        best = min(results, key=lambda r: r["individual_cost"])
        state = problem._create_next_candidate(state, p, sink, best)
    return state
