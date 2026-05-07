"""DAG* search strategy: cost-optimal placement via best-first search."""

import heapq
from math import inf
from typing import TYPE_CHECKING, List, Tuple

from kraken.search.base import SearchStrategy

from .heuristic import DagStarHeuristic
from .upper_bound import compute_prepp_cloud_upper_bound

if TYPE_CHECKING:
    from kraken.problem import PlacementProblem
    from kraken.data.state import SolutionCandidate


class DagStarSearch(SearchStrategy):
    """A*-style best-first search with admissible cost-only heuristic.

    Optimises pure `cumulative_cost`. Latency stays a hard constraint via
    the latency-threshold pruning already inside `PlacementProblem.expand`.
    The first goal state dequeued is provably cost-optimal.

    Args:
        use_upper_bound: if True, prune states whose `f`-value already
            exceeds the PrePP-from-cloud baseline cost.
        disable_heuristic: if True, force `h(s) = 0`, degenerating DAG*
            into pure uniform-cost (Dijkstra) search. h ≡ 0 is trivially
            admissible, so if the surrounding search is correct this
            variant must return the cost-optimal plan on every run.
            Useful as an ablation when the regular heuristic appears to
            overestimate true cost.
    """

    def __init__(
        self, *, use_upper_bound: bool = True, disable_heuristic: bool = False
    ):
        self.use_upper_bound = use_upper_bound
        self.disable_heuristic = disable_heuristic

    def solve(self, problem: "PlacementProblem") -> "SolutionCandidate":
        if self.disable_heuristic:
            estimate = lambda _state: 0.0  # noqa: E731 — pure Dijkstra mode
        else:
            heuristic = DagStarHeuristic(problem)
            estimate = heuristic.estimate

        upper, cloud_plan = (
            compute_prepp_cloud_upper_bound(problem)
            if self.use_upper_bound
            else (inf, None)
        )

        s0 = problem.get_initial_candidate()
        f0 = s0.cumulative_cost + estimate(s0)
        if f0 >= upper:
            if cloud_plan is None:
                raise ValueError("DAG*: cloud baseline infeasible and no other plan")
            return cloud_plan

        counter = 0
        heap: List[Tuple[float, int, "SolutionCandidate"]] = [(f0, counter, s0)]

        while heap:
            f, _, s = heapq.heappop(heap)
            if f >= upper:
                continue
            if problem.is_goal(s):
                return s
            for s_next in problem.expand(s):
                f_next = s_next.cumulative_cost + estimate(s_next)
                if f_next >= upper:
                    continue
                counter += 1
                heapq.heappush(heap, (f_next, counter, s_next))

        if cloud_plan is not None:
            return cloud_plan
        raise ValueError("DAG* exhausted queue with no feasible plan")
