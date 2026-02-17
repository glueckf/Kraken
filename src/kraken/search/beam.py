"""K-Beam search strategy for placement optimization."""

from typing import TYPE_CHECKING, List

from .base import SearchStrategy

if TYPE_CHECKING:
    from kraken.data.state import SolutionCandidate


class BeamSearch(SearchStrategy):
    """
    K-Beam search strategy that maintains k best candidates at each level.

    This strategy explores the state space by keeping the k best states
    (the "beam") at each step. It expands all states in the beam, gathers
    all their successors, and selects the k best to form the next beam.

    Attributes:
        k: The beam width (number of best candidates to keep at each step).
    """

    def __init__(self, k: int = 3):
        """
        Initialize the beam search strategy.

        Args:
            k: The beam width. Must be at least 1. Default is 3.

        Raises:
            ValueError: If k is less than 1.
        """
        if k < 1:
            raise ValueError("Beam width 'k' must be at least 1.")
        self.k = k

    def solve(self, problem) -> "SolutionCandidate":
        """
        Execute the k-beam search to find a solution.

        The algorithm maintains a beam of k best partial solutions at each
        level. At each iteration:
        1. Expand all states in the current beam
        2. Collect all successor states
        3. Select the k best successors for the next beam
        4. Continue until a goal state is found or no successors exist

        Args:
            problem: The placement problem to solve.

        Returns:
            The best complete solution found.

        Raises:
            ValueError: If no valid solution can be found (dead end reached).
        """
        # Initialize beam with the starting state
        beam: List[SolutionCandidate] = [problem.get_initial_candidate()]

        while True:
            # Collect all candidates generated from the current beam
            candidates: List[SolutionCandidate] = []

            # Track goal states found in the current beam
            goal_states: List[SolutionCandidate] = []

            # Expand each state in the current beam
            for state in beam:
                # Check if this state is already a goal
                if problem.is_goal(state):
                    goal_states.append(state)
                    continue  # Don't expand completed solutions

                # Generate successors for this state
                successors = problem.expand(state)

                # Add all successors to the candidate pool
                candidates.extend(successors)

            # If we found goal states, return the best one (lowest cost)
            if goal_states:
                return min(goal_states, key=lambda s: s.cumulative_cost)

            # If no new candidates were generated and no goals found, we hit a dead end
            if not candidates:
                # Return the best state from the last beam as fallback
                if beam:
                    return min(beam, key=lambda s: s.cumulative_cost)
                raise ValueError(
                    "Beam Search failed: no valid solution path found (dead end reached)."
                )

            # Select the k best candidates for the next beam
            # Sort by cumulative cost (ascending)
            candidates.sort(key=lambda s: s.cumulative_cost)

            # Keep only the top k candidates
            beam = candidates[: self.k]
