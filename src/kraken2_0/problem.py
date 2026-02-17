import math
from typing import List, Any, Dict

from kraken2_0.components.event_stack_manager import update_event_stack
from kraken2_0.components.cost_calculator import CostCalculator
from kraken2_0.components.optimizer import PlacementOptimizer
from kraken2_0.components.sorter import EventPlacementSorter
from kraken2_0.data.state import SolutionCandidate, PlacementInfo


class PlacementProblem:
    def __init__(
        self,
        processing_order: List[Any],
        context: Dict[str, Any],
        enable_detailed_logging: bool = False,
    ):
        latency_threshold = context.get("latency_threshold", None)
        """Initializes the entire problem context"""

        # Logging configuration
        self.logging_enabled = enable_detailed_logging
        if self.logging_enabled:
            self.detailed_log = []

        # --- Core Search & Problem Parameters ---
        self.processing_order = processing_order
        self.latency_threshold = (
            latency_threshold if latency_threshold is not None else float("inf")
        )
        self.query_workload = context["query_workload"]
        self.dependencies_per_projection = context["dependencies_per_projection"]
        self.latency_weighting_factor = context.get(
            "latency_weighting_factor", 1.0
        )  # The 'xi' factor
        raw_cost_weight = context.get("cost_weight", 0.5)
        cost_weight = raw_cost_weight if math.isfinite(raw_cost_weight) else 0.5
        cost_weight = min(max(cost_weight, 0.0), 1.0)

        latency_weight = context.get("latency_weight")
        if latency_weight is None:
            latency_weight = 1.0 - cost_weight
        elif not math.isfinite(latency_weight):
            latency_weight = 1.0 - cost_weight

        if latency_weight < 0.0:
            latency_weight = 0.0

        weight_sum = cost_weight + latency_weight
        if weight_sum == 0:
            cost_weight = 0.5
            latency_weight = 0.5
            weight_sum = 1.0

        self.cost_weight = cost_weight / weight_sum
        self.latency_weight = latency_weight / weight_sum

        # --- Instantiate Helper Component ---
        self.optimizer = PlacementOptimizer(
            context["graph"], context.get("routing_dict", {})
        )
        self.sorter = EventPlacementSorter()
        self.cost_calculator = CostCalculator(context)

        # Add problem reference to cost calculator for accessing placed subqueries
        self.cost_calculator.params["problem_ref"] = self

    def get_initial_candidate(self) -> SolutionCandidate:
        """Return the root node of the Solution Space S"""
        return SolutionCandidate()

    def is_goal(self, candidate: SolutionCandidate) -> bool:
        """Checks if a candidate represent a complete and valid solution e.g. a complete INEv graph."""

        # Here we should do more checks in the future, for now we only check if each projection has been placed.
        return len(candidate.placements) == len(self.processing_order)

    def expand(self, s_current: SolutionCandidate) -> List[SolutionCandidate]:
        """
        This function expands the current solution space with new states.

        The core "move generator". Given a state 's', it computes all valid next states by placing
        the next projection in the processing order and returns them.
        With respect to cost and latency constraints.
        """

        # Initialize the list holding the new states
        s_next_options = []

        # Pruning variable
        pruning = False

        # Get the projection index from the current state, this gives us the next projection to place.
        # If the current state is the start state, the index returns 0 starting with the first projection and so on
        projection_index = len(s_current.placements)

        if self.is_goal(s_current):
            return []

        # Get the next projection to be placed from the processing_order
        p = self.processing_order[projection_index]

        # Get and sort candidate physical nodes
        placed_subqueries = s_current.get_placed_subqueries(p, self)

        # (Pass necessary context to the optimizer)
        # This returns all the physical nodes n from the network T, that are capable of hosting this query simply based
        # on the question if all inputs are able to arrive there.
        possible_nodes = self.optimizer.get_possible_placement_nodes_optimized(
            p, placed_subqueries, self.cost_calculator.params
        )

        if not possible_nodes:
            return []

        # This sorts the nodes in an optimized manner to allow for pruning.
        # The goal is to: Check nodes that have all the inputs available first
        # Then go from the bottom of the network to the cloud, this way our latency constraint allows for pruning
        candidate_nodes = self.sorter.sort_candidate_nodes_optimized(
            possible_nodes, p, s_current.event_stack
        )

        # Now we can loop through each node n
        for n in candidate_nodes:
            # We calculate the costs for getting all the inputs to this node.
            # This returns a list of dicts, one for each valid comm strategy (e.g. push, predicate based push-pull)
            strategy_results = self.cost_calculator.calculate(p, n, s_current)

            # NOTE: For the pruning logic to work it is critical, that 'strategy_results' is order
            # with the lowest-latency strategy (all_push) appearing first.

            for result in strategy_results:
                # Here we need to create this next state to check its true latency
                s_next_temp = self._create_next_candidate(s_current, p, n, result)

                # Perform the accurate, step-by-step latency checkx.
                max_latency_so_far = s_next_temp.get_critical_path_latency(self)

                # Look-ahead pruning: for intermediate projections, add minimum
                # remaining distance to sink as a lower bound on final latency.
                # Skip for workload projections where sink cost is already included.
                lookahead_latency = max_latency_so_far
                if p not in self.query_workload:
                    lookahead_latency += self._get_min_distance_to_sink(n)

                # Determine if this decision will be pruned
                is_pruned = False

                if (
                    result["strategy"] == "all_push"
                    and lookahead_latency > self.latency_threshold
                ):
                    # Pruning condition achieved, we can prune everything.
                    pruning = True
                    is_pruned = True

                if lookahead_latency > self.latency_threshold:
                    is_pruned = True

                # Log this placement decision if logging is enabled
                if self.logging_enabled:
                    log_entry = {
                        # Identifiers
                        "projection_index": projection_index,
                        "projection": p,
                        "candidate_node": n,
                        # Decision
                        "communication_strategy": result["strategy"],
                        "is_pruned": is_pruned,
                        "is_part_of_final_solution": False,  # Filled later
                        # Individual cost and latency
                        "individual_cost": result.get("individual_cost"),
                        "individual_transmission_latency": result.get(
                            "transmission_latency"
                        ),
                        "individual_processing_latency": result.get(
                            "processing_latency"
                        ),
                        # Cumulative metrics before this placement
                        "cumulative_cost_before": s_current.cumulative_cost,
                        "cumulative_processing_latency_before": s_current.cumulative_processing_latency,
                        # Cumulative metrics after this placement
                        "cumulative_cost_after": s_next_temp.cumulative_cost,
                        "cumulative_processing_latency_after": s_next_temp.cumulative_processing_latency,
                        # Overall latency
                        "max_latency_so_far": max_latency_so_far,
                        "lookahead_latency": lookahead_latency,
                    }
                    self.detailed_log.append(log_entry)

                if (
                    result["strategy"] == "all_push"
                    and lookahead_latency > self.latency_threshold
                ):
                    break

                if lookahead_latency <= self.latency_threshold:
                    s_next_options.append(s_next_temp)

            if pruning:
                break

        if not s_next_options:
            return s_next_options

        costs = [candidate.cumulative_cost for candidate in s_next_options]
        min_cost = min(costs)
        max_cost = max(costs)
        cost_range = max_cost - min_cost

        latencies = [
            candidate.get_critical_path_latency(self) for candidate in s_next_options
        ]
        min_latency = min(latencies)
        max_latency = max(latencies)
        latency_range = max_latency - min_latency

        scored_options = []

        for candidate in s_next_options:
            candidate_latency = candidate.get_critical_path_latency(self)

            if latency_range > 0:
                latency_norm = (candidate_latency - min_latency) / latency_range
            else:
                latency_norm = 0.0

            if cost_range > 0:
                cost_norm = (candidate.cumulative_cost - min_cost) / cost_range
            else:
                cost_norm = 0.0

            score = (self.cost_weight * cost_norm) + (
                self.latency_weight * latency_norm
            )
            scored_options.append((score, candidate))

        scored_options.sort(key=lambda item: item[0])
        return [candidate for _, candidate in scored_options]

    def _create_next_candidate(
        self, s_current: SolutionCandidate, p: Any, n: int, strategy_result: dict
    ) -> SolutionCandidate:
        """Helper function to create a new, extended SolutionCandidate object."""
        new_placements = s_current.placements.copy()
        new_event_stack = {k: v.copy() for k, v in s_current.event_stack.items()}

        placement_info = PlacementInfo(
            projection=p,
            node=n,
            strategy=strategy_result["strategy"],
            individual_cost=strategy_result["individual_cost"],
            individual_transmission_latency=strategy_result["transmission_latency"],
            individual_processing_latency=strategy_result["processing_latency"],
            acquisition_steps=strategy_result["acquisition_steps"],
        )

        new_placements[p] = placement_info

        # TODO: Implement this in /kraken/components/event_stack_manager.py
        update_event_stack(
            stack=new_event_stack, node_id=n, query_id=p, placement_info=placement_info
        )

        return SolutionCandidate(
            placements=new_placements,
            cumulative_cost=s_current.cumulative_cost + placement_info.individual_cost,
            cumulative_processing_latency=s_current.cumulative_processing_latency
            + placement_info.individual_processing_latency,
            event_stack=new_event_stack,
        )

    def _get_min_distance_to_sink(self, node: int) -> float:
        """Get minimum hop distance from a node to any sink node.

        Args:
            node: The network node to measure from.

        Returns:
            Minimum distance to any sink, or 0.0 if no sinks exist.
        """
        sink_nodes = self.cost_calculator.params["sink_nodes"]
        distances = self.cost_calculator.params["pairwise_distance_matrix"]
        if not sink_nodes:
            return 0.0
        return min(distances[node][sink] for sink in sink_nodes)
