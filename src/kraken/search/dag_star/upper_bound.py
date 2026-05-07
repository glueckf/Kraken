"""Upper-bound computation: cost of pinning every projection to the cloud sink.

Used by DAG* as a pruning ceiling: any partial state whose `f`-value already
exceeds this bound cannot lead to a plan better than the cloud baseline, so
it can be discarded. The bound is exact under KRAKEN's cost model because we
walk the same `cost_calculator.calculate` pipeline that the search uses.
"""

from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from kraken.problem import PlacementProblem
    from kraken.data.state import SolutionCandidate


def compute_prepp_cloud_upper_bound(
    problem: "PlacementProblem",
) -> Tuple[float, Optional["SolutionCandidate"]]:
    """Score the cloud-pinned placement. Returns (cost, fully_placed_state).

    If the cloud is infeasible for any projection, returns (inf, None) — the
    caller should disable upper-bound pruning in that case.
    """
    sink_nodes = problem.cost_calculator.params["sink_nodes"]
    if not sink_nodes:
        return float("inf"), None
    sink = sink_nodes[0]

    state = problem.get_initial_candidate()
    total = 0.0

    for p in problem.processing_order:
        results = problem.cost_calculator.calculate(p, sink, state)
        if not results:
            return float("inf"), None
        best = min(results, key=lambda r: r["individual_cost"])
        state = problem._create_next_candidate(state, p, sink, best)
        total += float(best["individual_cost"])

    # The cloud plan only serves as a pruning bound if it itself satisfies the
    # latency constraint — otherwise it could be cheaper than any feasible plan
    # and lead us to discard the true optimum.
    if state.get_critical_path_latency(problem) > problem.latency_threshold:
        return float("inf"), None

    return total, state
