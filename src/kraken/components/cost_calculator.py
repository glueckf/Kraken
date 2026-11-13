"""Cost calculation pipeline for placement decisions."""

import io
import hashlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from kraken.data.acquisition_step import (
    AcquisitionSet,
    AcquisitionStep,
    PullResponse,
)
from kraken.data.state import PlacementInstance, SolutionCandidate


class CostCalculator:
    """
    Modular component for cost and latency calculation pipeline.

    Encapsulates the logic for calling the PrePP function, adjusting
    for local events, and adding final sink costs. This is a completely
    self-contained implementation that uses only the SolutionCandidate
    state and the external PrePP library.
    """

    def __init__(self, context: Dict[str, Any]):
        """Initialize calculator with static problem data.

        Args:
            context: Dictionary containing all static problem parameters
        """
        self.params = context
        self._prepp_cache: Dict[str, Any] = {}
        self._static_buffer_cache: Optional[str] = None

    def calculate(
        self, p: Any, n: int, s_current: SolutionCandidate
    ) -> List[Dict[str, Any]]:
        """Orchestrate the full cost calculation pipeline.

        Args:
            p: Projection being placed
            n: Node ID where placement is considered
            s_current: Current solution state

        Returns:
            List of dictionaries with strategy-specific costs and metrics
        """
        # Get raw costs for all strategies
        raw_strategies = self._get_raw_costs_for_strategies(p, n, s_current)

        # Apply adjustments to each strategy
        final_strategies = []
        for strategy in raw_strategies:
            adjusted = self._adjust_for_local_events(strategy, p, n, s_current)
            final = self._add_sink_costs(adjusted, p, n)

            # final = self._add_sink_costs(strategy, p, n)
            final_strategies.append(final)

        return final_strategies

    def calculate_multi_node(
        self, p: Any, option: Any, s_current: SolutionCandidate
    ) -> List[Dict[str, Any]]:
        """Costs of a multi-node placement (see components/multi_node.py).

        Every instance receives all senders of the complete inputs and its
        share of the split input's senders. Its output rate is the
        projection's output rate times its share of the split input's rate
        (INES rates are products of the input rates). Each instance is
        costed like a single-node placement, local events and sink included:
        all-push, and with push-pull on also a PrePP plan that sees only the
        instance's senders of the split input. The placement's cost and
        processing latency are the instances' sums, its transmission latency
        their maximum.

        Args:
            p: Projection being placed
            option: MultiNodeOption (split input and instances)
            s_current: Current solution state

        Returns:
            One strategy dictionary like calculate()'s, plus "split_input" and
            "instances" (PlacementInstance list), with every instance
            all-push; and, if push-pull is cheaper for some instance, a
            second one where every instance uses its cheaper plan.
        """
        senders = self.get_input_senders(p, s_current)
        split = option.split_input
        split_rate = dict(senders[split])
        total_split_rate = sum(split_rate.values())
        output_rate = self.params["projection_rates_selectivity"].get(p, (0.0, 0.0))[1]
        push_pull = self.params.get("push_pull", True)

        all_push_instances, cheapest_instances = [], []
        for host, split_nodes in option.assignment:
            if total_split_rate > 0:
                share = sum(split_rate[u] for u in split_nodes) / total_split_rate
            else:
                share = len(split_nodes) / len(split_rate)
            instance_rate = output_rate * share
            instance_senders = dict(senders)
            instance_senders[split] = [(u, split_rate[u]) for u in split_nodes]

            all_push = self._all_push_from_senders(
                p, host, instance_senders, instance_rate
            )
            strategies = [all_push]
            if push_pull:
                pushed_pulled = self._instance_push_pull(
                    p, host, split, split_nodes, s_current, instance_rate
                )
                if pushed_pulled is not None:
                    strategies.append(pushed_pulled)

            instances = []
            for result in strategies:
                result = self._adjust_for_local_events(result, p, host, s_current)
                result = self._add_sink_costs(result, p, host, instance_rate)
                instances.append(
                    PlacementInstance(
                        node=host,
                        split_senders=list(split_nodes),
                        output_rate=instance_rate,
                        individual_cost=result["individual_cost"],
                        individual_transmission_latency=result["transmission_latency"],
                        individual_processing_latency=result["processing_latency"],
                        acquisition_steps=result["acquisition_steps"],
                        strategy=result["strategy"],
                    )
                )
            all_push_instances.append(instances[0])
            cheapest_instances.append(min(instances, key=lambda i: i.individual_cost))

        results = [self._combine_instances(split, all_push_instances)]
        if any(i.strategy == "push_pull" for i in cheapest_instances):
            results.append(self._combine_instances(split, cheapest_instances))
        return results

    @staticmethod
    def _combine_instances(split: Any, instances: List[PlacementInstance]) -> Dict:
        """The strategy dictionary of a multi-node placement of these instances."""
        uses_push_pull = any(i.strategy == "push_pull" for i in instances)
        return {
            "strategy": "push_pull" if uses_push_pull else "all_push",
            "individual_cost": sum(i.individual_cost for i in instances),
            "transmission_latency": max(
                i.individual_transmission_latency for i in instances
            ),
            "processing_latency": sum(
                i.individual_processing_latency for i in instances
            ),
            # Each instance has its own plan (PlacementInstance.acquisition_steps)
            "acquisition_steps": AcquisitionSet(steps=[]),
            "split_input": split,
            "instances": instances,
        }

    def _instance_push_pull(
        self,
        p: Any,
        host: int,
        split: Any,
        split_nodes: List[int],
        s_current: SolutionCandidate,
        instance_rate: float,
    ) -> Optional[Dict[str, Any]]:
        """PrePP's push-pull plan for one instance of a multi-node placement.

        PrePP sees only the instance's senders of the split input: a
        primitive event is left out of the network at its other sources, a
        multi-node subquery lists only the instances it sends from. None if
        PrePP finds no plan, or if a primitive split input also occurs inside
        another input (leaving it out of the network would shrink that
        input too).
        """
        if split in self.params.get("local_rate_lookup", {}):
            for dep in self.params["dependencies_per_projection"].get(p, []):
                if dep != split and split in self._extract_needed_events(dep):
                    return None
        input_buffer = self._build_prepp_input_buffer(
            p, host, s_current, split=(split, split_nodes)
        )
        if input_buffer is None:
            return None
        prepp_output = self._run_prepp(input_buffer)
        if not prepp_output or len(prepp_output) < 6:
            return None
        return self._process_prepp_output(
            prepp_output, p, host, None, output_rate=instance_rate
        )

    def get_input_senders(
        self, p: Any, s_current: SolutionCandidate
    ) -> Dict[Any, List[Tuple[int, float]]]:
        """The senders (node, rate) of each input of a projection.

        A primitive event is sent by every node producing it, with its local
        rate; a placed subquery by its node with its output rate, or by each
        instance of a multi-node placement with that instance's output rate.
        Inputs that are neither are left out, as in the all-push costs.
        """
        local_rate_lookup = self.params.get("local_rate_lookup", {})
        projection_rates = self.params["projection_rates_selectivity"]
        senders = {}
        for dependency in self.params["dependencies_per_projection"].get(p, []):
            if dependency in local_rate_lookup:
                senders[dependency] = list(local_rate_lookup[dependency].items())
            elif dependency in s_current.placements:
                placement = s_current.placements[dependency]
                if placement.instances:
                    senders[dependency] = [
                        (instance.node, instance.output_rate)
                        for instance in placement.instances
                    ]
                else:
                    senders[dependency] = [
                        (placement.node, projection_rates.get(dependency, (0, 1))[1])
                    ]
        return senders

    def _get_raw_costs_for_strategies(
        self, p: Any, n: int, s_current: SolutionCandidate
    ) -> List[Dict[str, Any]]:
        """Get raw costs for all valid strategies.

        Args:
            p: Projection being placed
            n: Node ID where placement is considered
            s_current: Current solution state

        Returns:
            List of strategy dictionaries (all-push and optionally push-pull)
        """
        # Step 1: Compute all-push strategy
        all_push_result = self._compute_all_push_costs(p, n, s_current)

        if not self.params.get("push_pull", True):
            return [all_push_result]

        # Step 2: Compute push-pull strategy using PrePP
        # Create input buffer for PrePP
        input_buffer = self._build_prepp_input_buffer(p, n, s_current)
        if input_buffer is None:
            return [all_push_result]

        # Run PrePP for push-pull optimization
        prepp_output = self._run_prepp(input_buffer)

        # Process PrePP results to extract push-pull strategy
        if not prepp_output or len(prepp_output) < 6:
            return [all_push_result]

        push_pull_result = self._process_prepp_output(
            prepp_output, p, n, all_push_result["individual_cost"]
        )

        # Step 3: Compare and return distinct strategies
        if push_pull_result is None:
            return [all_push_result]

        # Check if strategies are identical
        strategies_identical = (
            push_pull_result["individual_cost"] == all_push_result["individual_cost"]
            and push_pull_result["transmission_latency"]
            == all_push_result["transmission_latency"]
            and push_pull_result["processing_latency"]
            == all_push_result["processing_latency"]
        )

        if strategies_identical:
            return [all_push_result]

        return [all_push_result, push_pull_result]

    def _run_prepp(self, input_buffer: Any) -> Optional[List]:
        """Run PrePP's exact push-pull planner on an input buffer."""
        from prepp.prepp import generate_prePP

        return generate_prePP(
            input_buffer=input_buffer,
            method="ppmuse",
            algorithm="e",
            samples=0,
            top_k=0,
            runs=1,
            plan_print=True,
            allPairs=self.params.get("all_pairs"),
            is_deterministic=self.params["simulation_mode"].value == "deterministic",
        )

    def _adjust_for_local_events(
        self, strategy_result: Dict, p: Any, n: int, s_current: SolutionCandidate
    ) -> Dict:
        """Adjust costs for events already available at node.

        Args:
            strategy_result: Single strategy dictionary to adjust
            p: Projection being placed
            n: Node ID where placement is considered
            s_current: Current solution state

        Returns:
            Adjusted strategy dictionary
        """
        # Get events available at node from state
        if n not in s_current.event_stack:
            return strategy_result

        available_events = set(s_current.event_stack[n].keys())

        # Extract primitive events needed for projection
        needed_events = self._extract_needed_events(p)

        if not (available_events & needed_events):
            return strategy_result

        events_already_available = available_events & needed_events

        # Calculate adjustment based on strategy type
        strategy_name = strategy_result["strategy"]
        acquisition_set = strategy_result["acquisition_steps"]

        if strategy_name == "all_push":
            # Pass the dictionary representation from the first step
            cost_adj, lat_adj = self._compute_all_push_adjustment(
                {0: acquisition_set.steps[0].pull_response.detailed_costs},
                events_already_available,
            )
        else:  # push_pull
            # Pass the list of step objects
            cost_adj, lat_adj = self._compute_acquisition_adjustment(
                acquisition_set.steps, events_already_available, n, s_current
            )

        # Apply adjustments
        strategy_result["individual_cost"] = max(
            0.0, strategy_result["individual_cost"] - cost_adj
        )
        strategy_result["transmission_latency"] = max(
            0.0, strategy_result["transmission_latency"] - lat_adj
        )

        return strategy_result

    def _add_sink_costs(
        self, strategy_result: Dict, p: Any, n: int, output_rate: float = None
    ) -> Dict:
        """Add transmission costs to sink nodes if needed.

        Args:
            strategy_result: Single strategy dictionary to update
            p: Projection being placed
            n: Node ID where placement is considered
            output_rate: Rate sent to the sinks; defaults to the projection's
                output rate (an instance of a multi-node placement sends its share)

        Returns:
            Strategy dictionary with sink costs added
        """
        # Check if projection needs to be sent to sinks
        if p not in self.params["query_workload"] or n in self.params["sink_nodes"]:
            return strategy_result

        if output_rate is None:
            proj_rates = self.params["projection_rates_selectivity"]
            output_rate = proj_rates.get(p, (0, 1))[1]

        # Calculate distances to sinks
        sink_nodes = self.params["sink_nodes"]
        distances = [
            self.params["pairwise_distance_matrix"][n][sink] for sink in sink_nodes
        ]

        if distances:
            total_distance = sum(distances)
            transmission_cost = total_distance * output_rate
            max_distance = max(distances)

            strategy_result["individual_cost"] += transmission_cost
            strategy_result["transmission_latency"] += max_distance

        return strategy_result

    def _create_cache_key(self, p: Any, n: int) -> str:
        """Create deterministic cache key."""
        proj_str = str(p)
        sel_rate = self.params["projection_rates_selectivity"].get(p, (0.0, 0.0))[0]
        sel_items = sorted(self.params["pairwise_selectivities"].items())

        key_data = f"{n}|{proj_str}|{sel_rate}|{sel_items}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def _get_placement_context(
        self, p: Any, s_current: SolutionCandidate
    ) -> Dict[str, Any]:
        """Gather common parameters for cost calculations.

        Args:
            p: Projection being placed
            s_current: Current solution state

        Returns:
            Dictionary of common cost calculation parameters
        """
        problem_ref = self.params.get("problem_ref")
        placed_subqueries = (
            s_current.get_placed_subqueries(p, problem_ref) if problem_ref else {}
        )

        return {
            "placed_subqueries": placed_subqueries,
            "has_placed_subqueries": bool(placed_subqueries),
            "selectivities": self.params["pairwise_selectivities"],
            "selection_rate": self.params["projection_rates_selectivity"].get(
                p, (0.0, 0.0)
            )[0],
            "dependencies": self.params["dependencies_per_projection"],
            "rates": self.params["global_event_rates"],
            "projection_rates": self.params["projection_rates_selectivity"],
            "index_event_nodes": self.params["index_event_nodes"],
            "local_rate_lookup": self.params.get("local_rate_lookup", {}),
        }

    def _build_prepp_input_buffer(
        self,
        p: Any,
        n: int,
        s_current: SolutionCandidate,
        split: Optional[Tuple[Any, List[int]]] = None,
    ) -> Optional[Any]:
        """Build input buffer for PrePP using only state information.

        Args:
            p: Projection being placed
            n: Node where placement is considered
            s_current: Current solution state
            split: For an instance of a multi-node placement, the split input
                and the nodes of its senders the instance receives. A
                primitive split input is left out of the network at its other
                sources; a multi-node subquery lists only these instances.

        Returns:
            Input buffer for PrePP or None if creation fails
        """
        context = self._get_placement_context(p, s_current)
        local_rate_lookup = self.params.get("local_rate_lookup", {})
        if split is not None and split[0] in local_rate_lookup:
            event, keep = split
            static_lines = self._generate_network_config(
                drop_sources={
                    event: {node for node in local_rate_lookup[event] if node not in keep}
                }
            )
            static_lines.append("selectivities")
            static_lines.append(str(context["selectivities"]))
            static_lines.append("")
            static_buffer = "\n".join(static_lines)
        else:
            if self._static_buffer_cache is None:
                # First time call: Generate and cache the static sections
                static_lines = self._generate_network_config()
                static_lines.append("selectivities")
                static_lines.append(str(context["selectivities"]))
                static_lines.append("")
                self._static_buffer_cache = "\n".join(static_lines)
            static_buffer = self._static_buffer_cache

        # Start with the static sections
        buffer_content = [static_buffer]

        # Add the dynamic sections
        buffer_content.append("queries")
        buffer_content.append(str(p))
        buffer_content.append("")
        buffer_content.append("muse graph")
        dynamic_lines = []
        self._add_muse_graph_entries(
            dynamic_lines, p, n, context["placed_subqueries"], s_current, split
        )
        buffer_content.append("\n".join(dynamic_lines))

        # Create buffer
        buffer = io.StringIO()
        buffer.write("\n".join(buffer_content))
        buffer.seek(0)

        return buffer

    def _generate_network_config(
        self, drop_sources: Optional[Dict[str, Set[int]]] = None
    ) -> List[str]:
        """Generate network configuration section.

        drop_sources: primitive events to leave out at some of their sources
        (rate 0 there), for an instance of a multi-node placement.
        """
        lines = ["network"]
        network = self.params["network_data_nodes"]

        for i, node in enumerate(network):
            lines.append(f"Node {i} Node {i}")

            comp_power = getattr(node, "computational_power", "inf")
            memory = getattr(node, "memory", "inf")

            # Try different possible attribute names for event rates
            event_rates = (
                getattr(node, "event_rates", None)
                or getattr(node, "eventrates", None)
                or getattr(node, "Eventrates", None)
                or getattr(node, "rates", None)
                or [0] * 6
            )

            dropped = [
                ord(event) - ord("A")
                for event, nodes in (drop_sources or {}).items()
                if i in nodes
            ]
            if dropped:
                event_rates = [
                    0 if index in dropped else rate
                    for index, rate in enumerate(event_rates)
                ]

            # Try different possible attribute names for children
            children = self._extract_node_ids(
                getattr(node, "children", None)
                or getattr(node, "child", None)
                or getattr(node, "Child", None),
                network,
            )

            # Try different possible attribute names for siblings
            siblings = self._extract_node_ids(
                getattr(node, "siblings", None)
                or getattr(node, "Siblings", None)
                or getattr(node, "sibling", None),
                network,
            )

            # Build parent map
            parents = self._get_parents_for_node(i, network)

            lines.append(f"Computational Power: {comp_power}")
            lines.append(f"Memory: {memory}")
            lines.append(
                f"Eventrates: {list(event_rates) if hasattr(event_rates, '__iter__') and not isinstance(event_rates, str) else event_rates}"
            )
            lines.append(f"Parents: {parents}")
            lines.append(f"Child: {children}")
            lines.append(f"Siblings: {siblings}")
            lines.append("")

        return lines

    def _add_muse_graph_entries(
        self,
        lines: List[str],
        p: Any,
        n: int,
        placed_subqueries: Dict,
        s_current: Optional[SolutionCandidate] = None,
        split: Optional[Tuple[Any, List[int]]] = None,
    ) -> None:
        """Add muse graph entries for projection.

        A multi-node subquery is listed ON its instance nodes with a
        sourceShare: PrePP assumes one rate per source, so each instance
        sends the mean share of the listed instances. If it is the split
        input of an instance (split), only the instances that send to it
        are listed.
        """
        proj_str = str(p)
        sel_rate = self.params["projection_rates_selectivity"].get(p, (0.0, 0.0))[0]

        if placed_subqueries:
            # Add placed subqueries first
            for subquery, subquery_node in placed_subqueries.items():
                subq_rate = self.params["projection_rates_selectivity"].get(
                    subquery, (0.001, 0.001)
                )[0]
                primitives = self._get_primitive_events(subquery)
                combination_str = "; ".join(primitives)
                source_share = ""
                if isinstance(subquery_node, tuple):
                    instances = s_current.placements[subquery].instances
                    total = sum(i.output_rate for i in instances)
                    if split is not None and split[0] == subquery:
                        instances = [i for i in instances if i.node in split[1]]
                    share = (
                        sum(i.output_rate for i in instances) / total
                        if total > 0
                        else len(instances) / len(s_current.placements[subquery].instances)
                    ) / len(instances)
                    subquery_node = ", ".join(str(i.node) for i in instances)
                    source_share = f" sourceShare= {share}"
                lines.append(
                    f"SELECT {subquery} FROM {combination_str} ON {{{subquery_node}}} WITH selectionRate= {subq_rate}{source_share}"
                )

            # Add main query referencing virtual events
            dependencies = self.params["dependencies_per_projection"].get(p, [])
            combination_str = "; ".join(str(dep) for dep in dependencies)
        else:
            # No subqueries, use primitives
            primitives = self._get_primitive_events(p)
            combination_str = "; ".join(primitives)

        lines.append(
            f"SELECT {proj_str} FROM {combination_str} ON {{{n}}} WITH selectionRate= {sel_rate}"
        )

    def _compute_all_push_costs(
        self, p: Any, n: int, s_current: SolutionCandidate
    ) -> Dict[str, Any]:
        """
        Compute all-push strategy costs using state information, formatting the
        output to match the detailed structure of a push-pull acquisition step.

        Args:
            p: Projection being placed
            n: Node where placement is considered
            s_current: Current solution state

        Returns:
            Dictionary containing all-push strategy with a standardized format.
        """
        output_rate = self.params["projection_rates_selectivity"].get(
            p, (0.0, 0.0)
        )[1]
        return self._all_push_from_senders(
            p, n, self.get_input_senders(p, s_current), output_rate
        )

    def _all_push_from_senders(
        self,
        p: Any,
        n: int,
        senders: Dict[Any, List[Tuple[int, float]]],
        processing_latency: float,
    ) -> Dict[str, Any]:
        """All-push costs of node n receiving the given senders of each input.

        Every sender pushes its rate over its hop distance to n. Inputs come
        in the projection's dependency order; the processing latency is the
        output rate of what n computes.
        """
        distances = self.params["pairwise_distance_matrix"]

        total_cost = 0.0
        max_transmission_latency = 0.0
        pull_response_details = {}

        for dependency in self.params["dependencies_per_projection"].get(p, []):
            if dependency not in senders:
                # Skip if dependency is not found (should not happen in a valid graph)
                continue
            dep_total_cost = 0.0
            dep_max_latency = 0
            sources_info = []
            for source_node, rate in senders[dependency]:
                hops = distances[source_node][n]
                cost = hops * rate
                dep_total_cost += cost
                dep_max_latency = max(dep_max_latency, hops)
                sources_info.append(
                    {
                        "source_node": source_node,
                        "distance": hops,
                        "base_rate": rate,
                        "raw_cost": cost,
                    }
                )

            total_cost += dep_total_cost
            max_transmission_latency = max(max_transmission_latency, dep_max_latency)

            # Selectivity is 1.0: primitive events have none applied here, and a
            # subquery's rate already is its output rate.
            pull_response_details[str(dependency)] = {
                "cost_with_selectivity": dep_total_cost,
                "latency": dep_max_latency,
                "raw_cost": dep_total_cost,
                "selectivity_applied": 1.0,
                "sources": sources_info,
            }

        # Build dataclass-based acquisition step
        pull_response = PullResponse(
            cost=total_cost,
            latency=max_transmission_latency,
            detailed_costs=pull_response_details,
        )

        acquisition_step = AcquisitionStep(
            pull_request=None,  # No pull request in "all-push"
            pull_response=pull_response,
            events_to_pull=[
                str(dep)
                for dep in self.params["dependencies_per_projection"].get(p, [])
            ],
        )

        return {
            "strategy": "all_push",
            "individual_cost": total_cost,
            "transmission_latency": max_transmission_latency,
            "processing_latency": processing_latency,
            "acquisition_steps": AcquisitionSet(steps=[acquisition_step]),
        }

    def _process_prepp_output(
        self,
        prepp_output: List,
        p: Any,
        n: int,
        all_push_base_cost: float,
        output_rate: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Process raw PrePP output to extract push-pull strategy.

        Args:
            prepp_output: Raw PrePP results
            p: Projection
            n: Node
            all_push_base_cost: Base cost from all-push strategy for ratio calculation
            output_rate: The output rate the processing latency scales with;
                defaults to the projection's (an instance produces its share)

        Returns:
            Push-pull strategy dictionary or None if invalid
        """
        qkey = str(p)
        steps_by_proj = prepp_output[6] if len(prepp_output) > 6 else {}

        if not steps_by_proj or qkey not in steps_by_proj:
            return None

        # prepp.py now returns AcquisitionSet objects directly
        acquisition_set = steps_by_proj[qkey]

        # Check if it's an error dict (legacy error handling)
        if isinstance(acquisition_set, dict) and "error" in acquisition_set:
            return None

        total_plan_costs = sum(step.total_cost for step in acquisition_set.steps)
        total_plan_latency = sum(step.total_latency for step in acquisition_set.steps)

        all_push_processing_latency = (
            output_rate
            if output_rate is not None
            else self.params["projection_rates_selectivity"].get(p, (0.0, 0.0))[1]
        )

        # Calculate the processing latency
        # The ratio is: (sum of pull response costs) / (sum of all primitive input rates for query)
        # where costs = rate × distance, creating a weighted average by transmission distance

        sum_of_input_costs_for_strategy = sum(
            step.pull_response.cost for step in acquisition_set.steps
        )
        sum_of_input_rates_for_primitive_strategy = self.params[
            "sum_of_input_rates_per_query"
        ][p]

        # Calculate the input ratio based on transmission costs
        input_ratio = (
            sum_of_input_costs_for_strategy / sum_of_input_rates_for_primitive_strategy
            if sum_of_input_rates_for_primitive_strategy > 0
            else 0.0
        )

        push_pull_processing_latency = input_ratio * all_push_processing_latency

        return {
            "strategy": "push_pull",
            "individual_cost": total_plan_costs,
            "transmission_latency": total_plan_latency,
            "processing_latency": push_pull_processing_latency,
            "acquisition_steps": acquisition_set,
        }

    def _extract_needed_events(self, p: Any) -> Set[str]:
        """Extract primitive events needed for projection.

        Args:
            p: Projection

        Returns:
            Set of primitive event names
        """
        # Use fast path if available
        if hasattr(p, "leafs") and callable(p.leafs):
            return set(p.leafs())

        # Parse from string representation
        proj_str = str(p)
        proj_str = proj_str.replace("AND", "").replace("SEQ", "")
        proj_str = proj_str.replace("(", "").replace(")", "")
        proj_str = re.sub(r"[0-9]+", "", proj_str).replace(" ", "")

        if "," in proj_str:
            return set(proj_str.split(","))
        else:
            return set(list(proj_str))

    def _compute_acquisition_adjustment(
        self,
        acquisition_steps: List[AcquisitionStep],
        events_already_available: Set[str],
        n: int,
        s_current: SolutionCandidate,
    ) -> Tuple[float, float]:
        """Compute cost/latency adjustment for locally available events.

        Args:
            acquisition_steps: List of AcquisitionStep objects
            events_already_available: Events available at node
            n: Node ID
            s_current: Current solution state

        Returns:
            Tuple of (cost_adjustment, latency_adjustment)
        """
        total_cost_adj = 0.0
        total_lat_adj = 0.0

        for step in acquisition_steps:
            events_to_pull = step.events_to_pull
            if not events_to_pull:
                continue

            all_primitives = self._parse_primitive_events(events_to_pull)
            events_we_can_skip = all_primitives & events_already_available

            if not events_we_can_skip:
                continue

            # Update metadata
            step.already_at_node = list(events_we_can_skip)
            step.acquired_by_query = self._get_query_sources(
                events_we_can_skip, n, s_current
            )

            # Calculate adjustment
            if all_primitives <= events_already_available:
                # All events available
                total_cost_adj += step.total_cost
                total_lat_adj += step.total_latency
            else:
                # Partial availability - pass pull_response detailed_costs
                total_cost_adj += self._compute_partial_cost_adjustment(
                    step.pull_response.detailed_costs,
                    events_we_can_skip,
                    all_primitives,
                    step.total_cost,
                )

        return total_cost_adj, total_lat_adj

    def _compute_all_push_adjustment(
        self,
        push_pull_steps: Dict[int, Dict[str, Any]],
        events_already_available: Set[str],
    ) -> Tuple[float, float]:
        """Compute all-push adjustment using push-pull step 0.

        Args:
            push_pull_steps: Push-pull acquisition steps
            events_already_available: Events available at node

        Returns:
            Tuple of (cost_adjustment, latency_adjustment)
        """
        if 0 not in push_pull_steps:
            return 0.0, 0.0

        step_0 = push_pull_steps[0]
        pull_response = step_0.get("detailed_cost_contribution", {}).get(
            "pull_response", {}
        )

        if not pull_response:
            return 0.0, 0.0

        all_push_events = set(pull_response.keys())
        events_we_can_skip = all_push_events & events_already_available

        if not events_we_can_skip:
            return 0.0, 0.0

        total_cost_adj = 0.0
        max_latency = 0.0

        for event in events_we_can_skip:
            if event in pull_response:
                details = pull_response[event]
                total_cost_adj += details.get("cost_with_selectivity", 0.0)
                max_latency = max(max_latency, details.get("latency", 0))

        if all_push_events <= events_already_available:
            return total_cost_adj, max_latency
        else:
            return total_cost_adj, 0.0

    def _parse_primitive_events(self, events_to_pull: List[Any]) -> Set[str]:
        """Parse primitive events from list.

        Args:
            events_to_pull: List of events or subqueries

        Returns:
            Set of primitive event names
        """
        primitives = set()
        for event in events_to_pull:
            event_str = str(event)
            event_str = event_str.replace("AND", "").replace("SEQ", "")
            event_str = event_str.replace("(", "").replace(")", "")
            event_str = re.sub(r"[0-9]+", "", event_str).replace(" ", "")
            if "," in event_str:
                primitives.update(event_str.split(","))
            else:
                primitives.update(list(event_str))
        return primitives

    def _get_query_sources(
        self, events: Set[str], n: int, s_current: SolutionCandidate
    ) -> Dict[str, Any]:
        """Get query sources for events from state.

        Args:
            events: Set of event names
            n: Node ID
            s_current: Current solution state

        Returns:
            Dictionary mapping events to query IDs
        """
        sources = {}
        if n in s_current.event_stack:
            node_events = s_current.event_stack[n]
            for event in events:
                if event in node_events:
                    sources[event] = node_events[event].get("query_id")
        return sources

    def _compute_partial_cost_adjustment(
        self,
        pull_response_details: Dict[str, Any],
        events_we_can_skip: Set[str],
        all_primitives: Set[str],
        total_step_cost: float,
    ) -> float:
        """Compute partial cost adjustment.

        Args:
            pull_response_details: Pull response detailed costs
            events_we_can_skip: Events available
            all_primitives: All primitive events
            total_step_cost: Total cost for this step

        Returns:
            Cost adjustment amount
        """
        total_adj = 0.0
        for event in events_we_can_skip:
            if event in pull_response_details:
                total_adj += pull_response_details[event].get(
                    "cost_with_selectivity", 0.0
                )
            else:
                fraction = len(events_we_can_skip) / len(all_primitives)
                total_adj += total_step_cost * fraction
                break

        return total_adj

    def _extract_node_ids(self, node_list: Any, network: List) -> Optional[List[int]]:
        """Extract node IDs from node objects.

        Args:
            node_list: List of node objects
            network: Full network list

        Returns:
            List of node IDs or None
        """
        if node_list is None:
            return None
        if not hasattr(node_list, "__iter__") or isinstance(node_list, str):
            return node_list

        network_lookup = {node: i for i, node in enumerate(network)}
        ids = []

        for item in node_list:
            if hasattr(item, "id"):
                ids.append(item.id)
            elif hasattr(item, "nodeID"):
                ids.append(item.nodeID)
            elif isinstance(item, int):
                ids.append(item)
            elif item in network_lookup:
                ids.append(network_lookup[item])

        return ids if ids else None

    def _get_parents_for_node(self, node_id: int, network: List) -> Optional[List[int]]:
        """Get parent nodes for a given node.

        Args:
            node_id: Node ID
            network: Full network list

        Returns:
            List of parent node IDs or None
        """
        parents = []
        for i, node in enumerate(network):
            children = self._extract_node_ids(
                getattr(node, "children", None)
                or getattr(node, "child", None)
                or getattr(node, "Child", None),
                network,
            )
            if children and node_id in children:
                parents.append(i)

        return parents if parents else None

    def _get_primitive_events(self, projection: Any) -> List[str]:
        """Get primitive events for projection.

        Args:
            projection: Projection object

        Returns:
            List of primitive event names
        """
        if hasattr(projection, "leafs") and callable(projection.leafs):
            return list(projection.leafs())

        proj_str = str(projection)
        proj_str = proj_str.replace("AND", "").replace("SEQ", "")
        proj_str = proj_str.replace("(", "").replace(")", "")
        proj_str = re.sub(r"[0-9]+", "", proj_str).replace(" ", "")

        if "," in proj_str:
            return proj_str.split(",")
        else:
            return list(proj_str)
