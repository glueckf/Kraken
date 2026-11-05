import re
from dataclasses import dataclass, field
from typing import Any, Dict

from .acquisition_step import AcquisitionSet, AcquisitionStep


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

        A projection's inputs travel in parallel: input w arrives at
        ready(w) + hops(source of w -> node), where a primitive event is ready
        at time 0 at each of its sources and a placed subquery is ready once
        its own inputs have arrived and it has processed them. Only push-pull
        acquisition steps are sequential (see input_arrival). A workload
        query placed off-sink adds the hops to its farthest sink at the end;
        dependents do not inherit that hop.

        l_v(v) = (l_p(v) * xi) + max(ready(w) + hops(w -> v) for w in inputs)
        """
        params = problem.cost_calculator.params
        distances = params["pairwise_distance_matrix"]
        sink_nodes = params["sink_nodes"]
        xi = problem.latency_weighting_factor

        ready: Dict[Any, float] = {}  # output available at the placement's node
        end_to_end_latencies: Dict[Any, float] = {}

        # Iterate through projections p in their topological dependency order
        for p in problem.processing_order:
            if p not in self.placements:
                continue

            placement = self.placements[p]  # v
            input_ready = {
                str(dep): ready[dep]
                for dep in problem.dependencies_per_projection.get(p, [])
                if dep in ready
            }
            arrival = input_arrival(
                placement.acquisition_steps, input_ready, distances
            )
            ready[p] = (placement.individual_processing_latency * xi) + arrival

            end_to_end_latencies[p] = ready[p]
            if (
                p in problem.query_workload
                and sink_nodes
                and placement.node not in sink_nodes
            ):
                end_to_end_latencies[p] += max(
                    distances[placement.node][sink] for sink in sink_nodes
                )

        if not end_to_end_latencies:
            return 0.0

        # Return the "high-water mark": the max latency of ANY projection placed so far.
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


def input_arrival(
    acquisition: AcquisitionSet, input_ready: Dict[str, float], distances: Any
) -> float:
    """Time at which the last input of a placement has arrived at its node.

    Pushed events stream in independently of each other. A pull step's
    request leaves once every event of the earlier steps has arrived (those
    events are what it filters with), reaches each source after its hop
    distance, and the source answers no earlier than its event is ready.

    Args:
        acquisition: The placement's acquisition steps, in plan order.
        input_ready: Ready time of each placed subquery input, keyed by its
            name; primitive events are ready at time 0.
        distances: Pairwise hop distances (request and response travel the
            same path).
    """
    arrived = 0.0
    for step in acquisition.steps:
        pulled = step.is_pull_based and not _already_local(step)
        step_arrival = 0.0
        for event, details in step.pull_response.detailed_costs.items():
            event_ready = input_ready.get(event, 0.0)
            for source in details.get("sources", []):
                hops = source["distance"]
                sent = max(arrived + hops, event_ready) if pulled else event_ready
                step_arrival = max(step_arrival, sent + hops)
        arrived = max(arrived, step_arrival)
    return arrived


def _already_local(step: AcquisitionStep) -> bool:
    """Whether every primitive of the step already reaches the node for another
    placement there, so it needs no pull round trip (same rule as
    CostCalculator._compute_acquisition_adjustment)."""
    if not step.already_at_node:
        return False
    primitives = set()
    for event in step.events_to_pull:
        name = re.sub(r"AND|SEQ|[0-9()\s]", "", str(event))
        primitives.update(name.split(",") if "," in name else name)
    return primitives <= set(step.already_at_node)
