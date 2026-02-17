"""Greedy search strategy for placement optimization."""

from typing import TYPE_CHECKING

from .base import SearchStrategy

if TYPE_CHECKING:
    pass


# Uses a depth-first search of S.
class GreedySearch(SearchStrategy):
    """
    Greedy search strategy that selects the lowest-cost option at each step.

    This strategy builds a solution by always choosing the next state with
    the minimum cumulative cost, without backtracking.
    """

    def solve(self, problem):
        # Start at the root of the solution space S
        s_current = problem.get_initial_candidate()

        # Continue until the INEv graph is complete, e.g. all projections are placed.
        while not problem.is_goal(s_current):
            # Generate all possible next states, sorted by best-to-worst by cost.
            s_next_options = problem.expand(s_current)

            # Check for dead end or error
            if not s_next_options:
                raise ValueError("Cost Greedy Search failed: a dead end was reached.")

            # Greedy Heuristic: Always choose the single best option (first one)
            s_current = s_next_options[0]

        return s_current
