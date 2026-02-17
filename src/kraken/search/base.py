"""Base interface for search strategies."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kraken.problem import PlacementProblem
    from kraken.data.state import SolutionCandidate


class SearchStrategy(ABC):
    """Abstract base class for all search strategies."""

    @abstractmethod
    def solve(self, problem: "PlacementProblem") -> "SolutionCandidate":
        """Execute the search strategy to find a solution.

        Args:
            problem: The placement problem to solve

        Returns:
            A complete solution candidate

        Raises:
            ValueError: If no valid solution can be found
        """
        pass
