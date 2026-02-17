from dataclasses import dataclass, field
from typing import Any, Dict

from .acquisition_step import AcquisitionSet


# Forward declaration to allow type hinting PlacementProblem within SolutionCandidate
class PlacementProblem:
    pass


@dataclass()
class PlacementInfo:
    """
    Represents a single Vertex 'v' in the INEv Graph 'I'.
    It's an immutable record of a single placement decision.
    'I' contains a Vertex v for each pair of an event type referenced in a query and
    any respective source node.
    """

    projection: Any  # The projection (event type) this vertex v represents
    node: int  # The physical node n from Graph T
    strategy: str  # e.g. 'all_push' or 'push_pull'

    individual_cost: (
        float  # Cost for this specific node v to acquire and process its inputs
    )

    individual_transmission_latency: float  # l_t(v)
    individual_processing_latency: float  # l_p(v)

    acquisition_steps: (
        AcquisitionSet  # Acquisition steps for this vertex v and its inputs
    )


@dataclass(slots=True)
class SolutionCandidate:
    """
    Represents a single state 's' in the Solution Space Graph 'S'.
    It contains the entire state of a partial or complete INEv Graph 'I'.
    """

    # The set of INEv nodes that form the current graph state
    placements: Dict[Any, PlacementInfo] = field(default_factory=dict)

    # The sum of individual_cost for all placements so far.
    cumulative_cost: float = 0.0

    # The sum of individual_processing_latency for all placements so far.
    cumulative_processing_latency: float = 0.0

    # The state of events on the physical network T for this solution state s.
    event_stack: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    def get_critical_path_latency(self, problem: "PlacementProblem") -> float:
        """
        Calculates the true end-to-end latency for all currently placed projections by finding the critical path.
        Return the MAXIMUM value found so far. This is used for accurate pruning at every search step.
        """

        # TODO: Double check correctness
        end_to_end_latencies: Dict[Any, float] = {}

        xi = problem.latency_weighting_factor

        # Iterate through projections p in their topological dependency order
        for p in problem.processing_order:
            if p not in self.placements:
                continue

            # 1. Find the arrival time of the latest-arriving dependency
            latest_input_arrival = (
                0.0  # This represent max(l_v(w) for w in predecessors)
            )
            dependencies = problem.dependencies_per_projection.get(p, [])
            for dep in dependencies:
                latest_input_arrival = max(
                    latest_input_arrival, end_to_end_latencies.get(dep, 0.0)
                )

            # 2. Get the individual latency components for this placement step
            placement = self.placements[p]  # v
            processing_latency = placement.individual_processing_latency  # l_p(v)
            transmission_latency = placement.individual_transmission_latency  # l_t(v)

            # 3. Apply the formal latency model for this single projection:
            # l_v(v) = (l_p(v) * xi) + l_t(v) + max(l_v(w) for w in predecessors)
            end_to_end_latencies[p] = (
                (processing_latency * xi) + transmission_latency + latest_input_arrival
            )

        if not end_to_end_latencies:
            return 0.0

        # 4. Return the "high-water mark": the max latency of ANY projection placed so far.
        return max(end_to_end_latencies.values())

    def get_placed_subqueries(
        self, projection: Any, problem: "PlacementProblem"
    ) -> Dict[Any, int]:
        """Helper method to get the locations of already-placed direct dependencies"""
        return {
            dep: self.placements[dep].node
            for dep in problem.dependencies_per_projection.get(projection, [])
            if dep in self.placements
        }
