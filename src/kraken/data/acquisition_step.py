# src/kraken2_0/acquisition_step.py

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class PullRequest:
    """Represents the request phase of a pull-based acquisition step."""

    cost: float
    latency: float
    events: List[str] = field(default_factory=list)
    detailed_costs: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PullResponse:
    """Represents the response phase of a pull-based acquisition step."""

    cost: float
    latency: float
    detailed_costs: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AcquisitionStep:
    """
    Models a single step in the data acquisition process, consisting of an
    optional pull request and a pull response.
    """

    pull_request: Optional[PullRequest]
    pull_response: PullResponse
    events_to_pull: List[str] = field(default_factory=list)
    already_at_node: Optional[List[str]] = None
    acquired_by_query: Optional[Dict[str, Any]] = None

    @property
    def total_cost(self) -> float:
        """Calculate the total cost for this step."""
        pr_cost = self.pull_request.cost if self.pull_request else 0.0
        return pr_cost + self.pull_response.cost

    @property
    def total_latency(self) -> float:
        """Calculate the total latency for this step."""
        pr_latency = self.pull_request.latency if self.pull_request else 0.0
        return pr_latency + self.pull_response.latency

    @property
    def is_push_based(self) -> bool:
        """
        Indicates if this acquisition step uses push-based data delivery.
        True when pull_request is None or has no events to pull.
        """
        return self.pull_request is None or not self.pull_request.events

    @property
    def is_pull_based(self) -> bool:
        """
        Indicates if this acquisition step uses pull-based data delivery.
        True when pull_request exists and has events to pull.
        """
        return not self.is_push_based

    @property
    def pull_set(self) -> List[str]:
        """
        Returns the list of events that were actively pulled (requested).
        Empty list means the data was pushed (not pulled).
        """
        if self.pull_request:
            return self.pull_request.events
        return []


@dataclass(slots=True)
class AcquisitionSet:
    """A collection of acquisition steps for a single placement."""

    steps: List[AcquisitionStep] = field(default_factory=list)
