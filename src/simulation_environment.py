"""
Simulation Environment - Central Orchestrator for INES Placement Strategies

This module provides a clean, well-structured orchestrator for the entire simulation pipeline.
It separates the simulation setup phase from the execution phase, where different placement
strategies are run sequentially.
"""

import io
import logging
import string
import time
from enum import Enum
from dataclasses import dataclass
from itertools import permutations
from typing import Any, Dict, List, Optional

import networkx as nx
import numpy as np

from core.node import Node
from core.network import generate_eventrates, create_random_tree
from core.graph import create_fog_graph
from core.all_pairs import populate_all_pairs
from core.query_workload import generate_workload
from ines.selectivity import initialize_selectivities
from core.write_config import generate_config_buffer
from ines.single_selectivities import initialize_single_selectivity
from core.parse_network import initialize_globals
from core.structures import init_event_nodes, get_longest
from ines.combigen import populate_proj_filter_dict, remove_filters, generate_combigen
from prepp.prepp import generate_prePP

# ==================== SIMULATION CONFIGURATION ====================

logger = logging.getLogger(__name__)


class SimulationMode(Enum):
    """Defines different simulation configuration modes for reproducible experiments."""

    RANDOM = "random"  # All components randomly generated
    FIXED_TOPOLOGY = "fixed_topology"  # Fixed network topology, rest random
    FIXED_WORKLOAD = "fixed_workload"  # Fixed topology + workload, rest random
    FULLY_DETERMINISTIC = "deterministic"  # All components fixed for reproducibility


class PlacementAlgorithm(Enum):
    """Defines available placement algorithms for Kraken."""

    GREEDY = "greedy"  # Greedy algorithm (default, fast)
    BACKTRACKING = "backtracking"  # Backtracking with latency constraints
    BRANCH_AND_CUT = "branch_and_cut"  # Branch and cut (not yet implemented)


class ProjectionRateLookupError(KeyError):
    """Raised when projection rates cannot be resolved for a query."""


_NOT_FOUND = object()


def _safe_to_str(obj: Any) -> Optional[str]:
    """Safely convert an object to string; return None if conversion fails."""
    try:
        return str(obj)
    except Exception:
        return None


def _attempt_projection_rate_lookup(projrates: Dict[Any, Any], candidate: Any) -> Any:
    """Attempt to resolve a projection rate entry using multiple key styles."""
    try:
        return projrates[candidate]
    except Exception:
        pass

    candidate_str = _safe_to_str(candidate)

    for key, value in projrates.items():
        if key is candidate:
            return value
        try:
            if key == candidate:
                return value
        except Exception:
            pass
        if candidate_str is not None:
            key_str = _safe_to_str(key)
            if key_str == candidate_str:
                return value

    return _NOT_FOUND


def _is_and_structure(candidate: Any) -> bool:
    """Determine whether a candidate represents an AND operator."""
    if hasattr(candidate, "mytype"):
        try:
            return str(getattr(candidate, "mytype", "")).upper() == "AND"
        except Exception:
            return False
    return False


def _generate_and_permutation_strings(candidate: Any):
    """Yield all unique string permutations for AND query children."""
    children = getattr(candidate, "children", None)
    if not children or len(children) < 2:
        return

    child_strings = [_safe_to_str(child) for child in children]
    if any(child_str is None for child_str in child_strings):
        return

    original = tuple(child_strings)
    seen = set()

    for perm in permutations(child_strings):
        if perm == original:
            continue
        candidate_str = f"AND({', '.join(perm)})"
        if candidate_str in seen:
            continue
        seen.add(candidate_str)
        yield candidate_str


def resolve_projection_rate_tuple(context: Any, query: Any) -> Any:
    """Resolve the projection rate tuple for a query, trying AND permutations if needed."""
    projrates = getattr(context, "h_projrates", None)
    if not projrates:
        query_repr = _safe_to_str(query) or repr(query)
        raise ProjectionRateLookupError(
            f"Projection rates are not initialized; failed for query '{query_repr}'."
        )

    candidates: List[Any] = []
    candidates.append(query)

    if hasattr(query, "stripKL_simple"):
        try:
            stripped = query.strip_kl_simple()
            candidates.append(stripped)
        except Exception:
            pass

    query_str = _safe_to_str(query)
    if query_str is not None:
        candidates.append(query_str)

    checked_strings = set()

    for candidate in candidates:
        if candidate is None:
            continue
        result = _attempt_projection_rate_lookup(projrates, candidate)
        if result is not _NOT_FOUND:
            return result
        candidate_str = _safe_to_str(candidate)
        if candidate_str:
            checked_strings.add(candidate_str)

    for candidate in candidates:
        if candidate is None or isinstance(candidate, str):
            continue
        if not _is_and_structure(candidate):
            continue
        for permutation_str in _generate_and_permutation_strings(candidate):
            if permutation_str in checked_strings:
                continue
            checked_strings.add(permutation_str)
            result = _attempt_projection_rate_lookup(projrates, permutation_str)
            if result is not _NOT_FOUND:
                return result

    query_repr = query_str or repr(query)
    raise ProjectionRateLookupError(
        f"Unable to resolve projection rates for query '{query_repr}' even after AND permutations."
    )


def get_projection_rate_value(context: Any, query: Any, index: int) -> float:
    """Fetch a specific projection rate (selection/output) as float."""
    rate_info = resolve_projection_rate_tuple(context, query)

    if isinstance(rate_info, (list, tuple)):
        try:
            selected_value = rate_info[index]
        except (IndexError, TypeError):
            query_repr = _safe_to_str(query) or repr(query)
            raise ProjectionRateLookupError(
                f"Projection rate tuple for query '{query_repr}' does not contain index {index}."
            ) from None
    else:
        if index != 0:
            query_repr = _safe_to_str(query) or repr(query)
            raise ProjectionRateLookupError(
                f"Projection rate for query '{query_repr}' is scalar; index {index} is invalid."
            )
        selected_value = rate_info

    try:
        return float(selected_value)
    except (TypeError, ValueError):
        query_repr = _safe_to_str(query) or repr(query)
        raise ProjectionRateLookupError(
            f"Projection rate value for query '{query_repr}' at index {index} is not numeric."
        ) from None


@dataclass
class SimulationConfig:
    """Configuration class for INES simulation parameters."""

    # Network parameters
    network_size: int = 12
    event_skew: float = 0.3
    node_event_ratio: float = 0.5
    max_parents: int = 10
    parent_factor: float = 1.8
    num_event_types: int = 6

    # Query parameters
    query_size: int = 3
    query_length: int = 5

    # Latency Awareness
    xi: float = 0.0
    latency_threshold: float = None  # If None, latency is not considered
    cost_weight: float = 0.5

    # Latency Trade-off Study
    run_latency_tradeoff_study: bool = False
    output_dataset_name: Optional[str] = None

    # Simulation mode
    mode: SimulationMode = SimulationMode.RANDOM

    # Placement algorithm
    algorithm: PlacementAlgorithm = PlacementAlgorithm.GREEDY

    def is_topology_fixed(self) -> bool:
        """Check if network topology should be hardcoded."""
        return self.mode in [
            SimulationMode.FIXED_TOPOLOGY,
            SimulationMode.FIXED_WORKLOAD,
            SimulationMode.FULLY_DETERMINISTIC,
        ]

    def is_workload_fixed(self) -> bool:
        """Check if query workload should be hardcoded."""
        return self.mode in [
            SimulationMode.FIXED_WORKLOAD,
            SimulationMode.FULLY_DETERMINISTIC,
        ]

    def is_selectivities_fixed(self) -> bool:
        """Check if selectivities should be hardcoded."""
        return self.mode == SimulationMode.FULLY_DETERMINISTIC

    @classmethod
    def create_random(cls, **kwargs) -> "SimulationConfig":
        """Create a fully random simulation configuration."""
        return cls(mode=SimulationMode.RANDOM, **kwargs)

    @classmethod
    def create_fixed_topology(cls, **kwargs) -> "SimulationConfig":
        """Create configuration with fixed topology, rest random."""
        return cls(mode=SimulationMode.FIXED_TOPOLOGY, **kwargs)

    @classmethod
    def create_fixed_workload(cls, **kwargs) -> "SimulationConfig":
        """Create configuration with fixed topology and workload, rest random."""
        return cls(mode=SimulationMode.FIXED_WORKLOAD, **kwargs)

    @classmethod
    def create_deterministic(cls, **kwargs) -> "SimulationConfig":
        """Create fully deterministic configuration for reproducible results."""
        return cls(mode=SimulationMode.FULLY_DETERMINISTIC, **kwargs)


# ==================== PLACEHOLDER FUNCTIONS ====================


def compute_all_push(context):
    """Calculate the All Push (central) placement cost and latency.

    This strategy places all operators at the cloud (node 0) and calculates
    the cost of transmitting all primitive events to the cloud.

    Args:
        context: Simulation context containing network, workload, and rate data

    Returns:
        Dictionary containing cost, latency, node, routing_dict, and status
    """
    try:
        print("--- Running All Push Scenario ---")

        import networkx as nx

        start_time = time.time()

        destination = 0  # Cloud node

        # Pre-compute: Get all event types
        eventtypes = set()
        for query in context.query_workload:
            eventtypes.update(query.leafs())

        eventtypes = list(eventtypes)  # Convert back to list if needed

        # Pre-fetch destination distances once (instead of accessing allPairs repeatedly)
        dest_distances = context.allPairs[destination]

        # Calculate costs for central placement at cloud (node 0)
        mycosts = 0
        routing_dict = {}
        event_costs = {}  # Track costs per event type for processing latency calculation

        for eventtype in eventtypes:
            event_rate = context.h_rates_data[eventtype]
            routing_dict[eventtype] = {}
            event_type_cost = 0

            for etb in context.h_IndexEventNodes[eventtype]:
                # Get event node indices directly
                index = context.h_IndexEventNodes[etb]
                node_list = context.h_eventNodes[index]

                # Find source with minimum distance in one pass
                min_distance = float("inf")
                best_source = None

                for node_id, has_event in enumerate(node_list):
                    if has_event == 1:
                        distance = dest_distances[node_id]
                        if distance < min_distance:
                            min_distance = distance
                            best_source = node_id

                # Add transmission cost: rate × distance
                cost = event_rate * min_distance
                mycosts += cost
                event_type_cost += cost

                # Compute shortest path only once per event instance
                shortest_path = nx.shortest_path(
                    context.graph, best_source, destination, method="dijkstra"
                )
                routing_dict[eventtype][etb] = shortest_path

            event_costs[eventtype] = event_type_cost

        # Calculate processing latency using the correct formula
        processing_latency = 0
        for query in context.query_workload:
            query_output_rate = get_projection_rate_value(context, query, index=1)

            # Sum costs for events used by this query
            query_event_cost = sum(
                event_costs.get(event, 0.0) for event in query.leafs()
            )

            # Get sum of primitive input rates for this query
            sum_input_rates = context.sum_of_input_rates_per_query.get(query, 1.0)

            # Calculate processing latency: output_rate × (costs / sum_input_rates)
            if sum_input_rates > 0:
                processing_latency += query_output_rate * (
                    query_event_cost / sum_input_rates
                )

        # Longest path is simply the maximum distance from destination
        longest_path = max(dest_distances)

        end_time = time.time()

        print(f"--- All Push Complete: Cost={mycosts:.2f}, Latency={longest_path} ---")

        return {
            "cost": mycosts,
            "transmission_latency": longest_path,
            "processing_latency": processing_latency,
            "computing_time": end_time - start_time,
            "status": "success",
        }
    except Exception as e:
        logger.error(
            msg=e,
            exc_info=True,
        )
        raise


def calculate_prepp_from_cloud(context, reused_buffer_section):
    """Calculate PrePP placement with all queries placed on cloud (node 0).

    Args:
        context: Simulation context containing network, workload, and rate data
        reused_buffer_section: String containing pre-built network and selectivities sections

    Returns:
        Dictionary containing PrePP results with cost, latency, and status
    """

    try:
        print("--- Running Solely PrePP from Cloud Scenario ---")

        prepp_start_time = time.time()

        # Convert reused_buffer_section to ensure no numpy types in output
        # The reused section may contain numpy type representations like 'np.int64(113)'
        # which cannot be parsed by prepp.py. Replace them with plain numbers.
        import re

        # Match patterns like 'np.int64(123)' or 'np.float64(1.5)' and extract just the number
        reused_buffer_section = re.sub(
            r"np\.\w+\(([^)]+)\)", r"\1", reused_buffer_section
        )

        # Build buffer content using list for efficient concatenation
        buffer_lines = [reused_buffer_section]

        # Add queries section
        buffer_lines.append("queries")
        for query in context.query_workload:
            buffer_lines.append(str(query))
        buffer_lines.append("")  # Empty line after queries

        # Add muse graph section
        buffer_lines.append("muse graph")
        for query in context.processing_order:
            if query not in context.query_workload:
                continue
            qkey = str(query)
            primitive_events = context.h_primitive_events[qkey]

            # Build primitive events list with proper formatting
            list_str = "; ".join(str(event) for event in primitive_events)

            # Build the SELECT line (all queries placed on cloud node 0)
            selection_rate = get_projection_rate_value(context, query, index=0)

            line = f"SELECT {qkey} FROM {list_str} ON {{0}} WITH selectionRate= {selection_rate}"
            buffer_lines.append(line)

        # Create buffer with proper initialization
        buffer = io.StringIO()
        buffer.write("\n".join(buffer_lines))
        buffer.seek(0)  # CRITICAL: Reset to start for reading

        # Determine if running in deterministic mode
        is_deterministic = context.config.mode.value == "deterministic"

        # Run PrePP for cloud-only placement
        prepp_results = generate_prePP(
            input_buffer=buffer,
            method="ppmuse",
            algorithm="e",
            samples=1,
            top_k=0,
            runs=1,
            plan_print=True,
            allPairs=context.allPairs,
            is_deterministic=is_deterministic,
        )

        if prepp_results is None or len(prepp_results) < 7:
            return {
                "cost": 0,
                "transmission_latency": 0,
                "processing_latency": 0,
                "computing_time": 0,
                "status": "failed",
            }

        # Extract results (prepp_results format: [cost, time, latency, ratio, push_costs, central_latency, steps])
        exact_cost = prepp_results[0]
        max_latency_tuple = prepp_results[2]
        acquisition_steps = prepp_results[6]  # Dictionary: {query_str: AcquisitionSet}

        # Extract transmission latency
        if isinstance(max_latency_tuple, tuple):
            transmission_latency = max_latency_tuple[1]  # Latency value from tuple
        else:
            transmission_latency = max_latency_tuple

        # Calculate processing latency using acquisition steps
        # For each query: output_rate * (sum_of_acquisition_response_costs / sum_of_primitive_input_rates)
        processing_latency = 0.0
        max_latency = 0.0
        for query in context.query_workload:
            query_str = str(query)

            # Get the acquisition set for this query
            if query_str not in acquisition_steps:
                continue

            acquisition_set = acquisition_steps[query_str]

            # Handle error case where acquisition_set is a dict with "error" key
            if isinstance(acquisition_set, dict) and "error" in acquisition_set:
                continue

            # Sum the pull response costs from all acquisition steps
            sum_of_acquisition_step_response_cost = sum(
                step.pull_response.cost for step in acquisition_set.steps
            )

            transmission_latency = sum(
                step.total_latency for step in acquisition_set.steps
            )

            max_latency = max(max_latency, transmission_latency)

            # Get the sum of primitive input rates for this query
            sum_input_rates_per_query = context.sum_of_input_rates_per_query.get(
                query, 1.0
            )

            # Calculate the input ratio
            if sum_input_rates_per_query > 0:
                input_ratio = (
                    sum_of_acquisition_step_response_cost / sum_input_rates_per_query
                )
            else:
                input_ratio = 0.0

            # Get the output rate for this query
            output_rate = get_projection_rate_value(context, query, index=1)

            # Calculate processing latency contribution for this query
            query_processing_latency = output_rate * input_ratio
            processing_latency += query_processing_latency

        prepp_end_time = time.time()

        return {
            "cost": exact_cost,
            "transmission_latency": max_latency,
            "processing_latency": processing_latency,
            "computing_time": prepp_end_time - prepp_start_time,
            "status": "success",
        }
    except Exception as e:
        logger.error(
            msg=e,
            exc_info=True,
        )
        raise


def update_results_for_topology(context, ines_results, inev_results):
    """
    Update INES results to include cloud transmission costs and latency.
    Format INEv results into the expected dictionary structure (already adjusted in placement).

    Args:
        context: Simulation context with network topology and query workload
        ines_results: Results from INES (PrePP) containing:
            [0] exact_cost (total costs)
            [1] pushPullTime (calculation time)
            [2] maxPushPullLatency (latency value or tuple)
            [3] endTransmissionRatio
            [4] total_push_costs (all-push costs)
            [5] node_received_eventtypes
            [6] acquisition_steps
        inev_results: Results from INEv (already adjusted, just needs formatting)

    Returns:
        Tuple of (ines_dict, inev_dict) where each dict contains:
        {
            "cost": costs,
            "transmission_latency": transmission_latency,
            "processing_latency": processing_latency,
            "computing_time": computing_time,
            "status": "success"
        }
    """
    try:
        CLOUD_NODE_ID = 0

        query_workload = context.query_workload
        ines_eval_plan = context.eval_plan[0].projections

        # Extract INES data
        ines_total_costs = ines_results[0]
        ines_calculation_time = ines_results[1]
        ines_max_latency_tuple = ines_results[2]

        # Calculate INES latencies (returns tuple of transmission and processing latencies)
        ines_transmission_latency_per_query, ines_processing_latency = (
            calculate_ines_max_latency(context, ines_results)
        )

        # ===== ADJUST INES RESULTS ONLY =====
        # Calculate additional costs for sending query results to cloud
        additional_costs = 0

        for projection in ines_eval_plan:
            projection_name = projection.name.name
            if projection_name in query_workload:
                placement_nodes = projection.name.sinks
                for placed_node in placement_nodes:
                    hops_from_node_to_cloud = context.allPairs[placed_node][
                        CLOUD_NODE_ID
                    ]
                    query_output_rate = context.h_projrates.get(
                        projection_name, (1.0, 1.0)
                    )[1]
                    additional_costs += hops_from_node_to_cloud * query_output_rate

        # Update costs for INES only
        ines_total_costs += additional_costs

        # Calculate additional latency for sending to cloud (INES only)
        if (
            isinstance(ines_max_latency_tuple, tuple)
            and len(ines_max_latency_tuple) > 0
        ):
            node_with_max_latency = ines_max_latency_tuple[0]
            if not isinstance(node_with_max_latency, int):
                logger.debug(
                    "INES max latency node is not an integer (value=%s); skipping cloud latency adjustment",
                    node_with_max_latency,
                )

        projections = context.eval_plan[0].projections

        def _lookup_base_latency(query_obj: Any) -> float:
            """Fetch the pre-cloud critical latency for a query using multiple key styles."""
            query_key = str(query_obj)
            if query_key in ines_transmission_latency_per_query:
                return float(ines_transmission_latency_per_query[query_key])
            if query_obj in ines_transmission_latency_per_query:
                return float(ines_transmission_latency_per_query[query_obj])
            return 0.0

        def _cloud_hop_latency(query_name: Any) -> float:
            """Compute the max distance from placements to the cloud for a given query."""
            max_distance = 0.0
            for proj in projections:
                current_name = proj.name.name
                if current_name == query_name:
                    sinks = getattr(proj.name, "sinks", []) or []
                    for sink in sinks:
                        max_distance = max(
                            max_distance,
                            float(context.allPairs[sink][CLOUD_NODE_ID]),
                        )
            return max_distance

        # Update transmission latency for INES (add cloud transmission)
        ines_transmission_latency = 0.0
        for query in query_workload:
            base_latency = _lookup_base_latency(query)
            cloud_latency = _cloud_hop_latency(query)
            candidate_latency = base_latency + cloud_latency
            ines_transmission_latency = max(
                ines_transmission_latency, candidate_latency
            )

        # ===== FORMAT INEV RESULTS (NO ADJUSTMENTS) =====
        # INEv results are already adjusted in the placement algorithm
        # Just extract and format them
        inev_total_costs = inev_results["cost"]
        inev_calculation_time = inev_results["computing_time"]
        inev_transmission_latency = inev_results["transmission_latency"]
        inev_processing_latency = inev_results["processing_latency"]

        # Create return dictionaries
        ines_dict = {
            "cost": ines_total_costs,
            "transmission_latency": ines_transmission_latency,
            "processing_latency": ines_processing_latency,
            "computing_time": ines_calculation_time,
            "status": "success",
        }

        inev_dict = {
            "cost": inev_total_costs,
            "transmission_latency": inev_transmission_latency,
            "processing_latency": inev_processing_latency,
            "computing_time": inev_calculation_time,
            "status": "success",
        }

        return ines_dict, inev_dict
    except Exception as e:
        logger.error(msg=e, exc_info=True)
        raise


# ==================== HARDCODED TOPOLOGY/WORKLOAD FUNCTIONS ====================


def create_hardcoded_tree():
    """
    Create a hardcoded topology with 12 nodes in a hierarchical structure:
    - Layer 0: Node 0 (Cloud)
    - Layer 1: Nodes 1, 2
    - Layer 2: Nodes 3, 4, 5
    - Layer 3: Nodes 6, 7, 8, 9, 10, 11 (Leaf nodes)

    Based on expected output structure where all intermediate nodes connect to all leaf nodes.
    """
    import math
    from core.node import Node

    # Initialize network and event tracking
    nw = []
    eList = {}

    # Define event rates with strong variation
    base_eventrates = generate_hardcoded_primitive_events()

    # Create nodes with decreasing compute power by layer
    nodes = {}

    # Layer 0: Cloud (Node 0)
    nodes[0] = Node(
        id=0, compute_power=math.inf, memory=math.inf, resource_capacity=math.inf
    )
    nodes[0].eventrates = [0] * len(base_eventrates)
    nw.append(nodes[0])

    # Layer 1: Nodes 1, 2
    for node_id in [1, 2]:
        nodes[node_id] = Node(
            id=node_id, compute_power=math.inf, memory=math.inf, resource_capacity=math.inf
        )
        nodes[node_id].eventrates = [0] * len(base_eventrates)
        nw.append(nodes[node_id])

    # Layer 2: Nodes 3, 4, 5
    for node_id in [3, 4, 5]:
        nodes[node_id] = Node(
            id=node_id, compute_power=math.inf, memory=math.inf, resource_capacity=math.inf
        )
        nodes[node_id].eventrates = [0] * len(base_eventrates)
        nw.append(nodes[node_id])

    # Layer 3: Leaf nodes 6, 7, 8, 9, 10, 11
    for node_id in [6, 7, 8, 9, 10, 11]:
        nodes[node_id] = Node(
            id=node_id, compute_power=math.inf, memory=math.inf, resource_capacity=math.inf
        )
        nodes[node_id].eventrates = [0] * len(base_eventrates)
        nw.append(nodes[node_id])

    # Set up parent-child relationships based on expected output
    # Cloud connections (Layer 0 -> Layer 1)
    nodes[0].Child = [nodes[1], nodes[2]]
    nodes[1].Parent = [nodes[0]]
    nodes[2].Parent = [nodes[0]]

    # Layer 1 -> Layer 2 connections (partial connectivity, not full mesh)
    nodes[1].Child = [nodes[3], nodes[5]]  # Node 1 connects only to nodes 3, 5
    nodes[2].Child = [nodes[3], nodes[4]]  # Node 2 connects only to nodes 3, 4

    # Each node in layer 2 has selected parents
    nodes[3].Parent = [nodes[1], nodes[2]]  # Node 3 has both parents
    nodes[4].Parent = [nodes[2]]  # Node 4 has only node 2 as parent
    nodes[5].Parent = [nodes[1]]  # Node 5 has only node 1 as parent

    # Layer 2 -> Layer 3 connections (realistic overlap with varied parent counts)
    nodes[3].Child = [
        nodes[6],
        nodes[7],
        nodes[8],
        nodes[9],
    ]  # Node 3 connects to 6,7,8,9
    nodes[4].Child = [
        nodes[6],
        nodes[7],
        nodes[8],
        nodes[9],
        nodes[10],
    ]  # Node 4 connects to 6,7,8,9,10
    nodes[5].Child = [nodes[6], nodes[10], nodes[11]]  # Node 5 connects to 6,10,11

    # Realistic parent distribution: mix of 1, 2, and 3 parents per leaf node
    nodes[6].Parent = [nodes[3], nodes[4], nodes[5]]  # Node 6: 3 parents (3,4,5)
    nodes[7].Parent = [nodes[3], nodes[4]]  # Node 7: 1 parent (3, 4)
    nodes[8].Parent = [nodes[3], nodes[4]]  # Node 8: 2 parents (3,4)
    nodes[9].Parent = [nodes[3], nodes[4]]  # Node 9: 2 parents (3,4)
    nodes[10].Parent = [nodes[4], nodes[5]]  # Node 10: 2 parents (4,5)
    nodes[11].Parent = [nodes[5]]  # Node 11: 1 parent (5)

    # Assign events to leaf nodes with varied distributions
    # Event assignments with diverse event rate combinations
    event_assignments = {
        6: [0, 4],  # Node 6: Events A (1000), E (800)
        7: [1, 2, 3],  # Node 7: Events B (2), C (45), D (203)
        # 8: [0, 2, 4],          # Node 8: Events A (1000), C (45), E (800)
        8: [0, 2],  # Node 8: Events A (1000), C (45)
        # 9: [3,5]
        9: [3],  # Node 9: Events D (203), F (5)
        10: [0, 1, 5],  # Node 10: Events A (1000), B (2), F (5)
        11: [2, 3, 4, 5],  # Node 11: Events C (45), D (203), E (800), F (5)
    }

    # Apply event assignments
    for leaf_id, event_indices in event_assignments.items():
        for event_idx in event_indices:
            nodes[leaf_id].eventrates[event_idx] = base_eventrates[event_idx]

    # Build eList - each leaf node gets its actual ancestor IDs based on the new topology
    eList[6] = [
        0,
        1,
        2,
        3,
        4,
        5,
    ]  # Node 6: ancestors through nodes 3, 4, and 5 (all paths)
    eList[7] = [0, 1, 2, 3, 4]  # Node 7: ancestors through node 3 and 4
    eList[8] = [0, 1, 2, 3, 4]  # Node 8: ancestors through nodes 3 and 4
    eList[9] = [0, 1, 2, 3, 4]  # Node 9: ancestors through nodes 3 and 4
    eList[10] = [0, 1, 2, 4, 5]  # Node 10: ancestors through nodes 4 and 5
    eList[11] = [0, 1, 5]  # Node 11: ancestors through node 5 only

    root = nodes[0]
    return root, nw, eList


def generate_hardcoded_workload():
    """
    Generate a hardcoded workload with 4 queries showing synergies:
    - 2 simple queries
    - 1 medium complexity query
    - 1 complex nested query

    Queries share common subexpressions for optimization potential.
    """
    queries = []

    # # Query 1: Simple SEQ - SEQ(A, B, C)
    # q1 = SEQ(PrimEvent("A"), PrimEvent("B"), PrimEvent("C"))
    # q1 = number_children(q1)
    # queries.append(q1)
    #
    # # Query 2:
    # q2 = AND(PrimEvent("A"), PrimEvent("B"))
    # q2 = number_children(q2)
    # queries.append(q2)
    #
    # # Query 3: Simple AND with shared elements - AND(A, B, D)
    # q3 = AND(PrimEvent("A"), PrimEvent("B"), PrimEvent("D"))
    # q3 = number_children(q3)
    # queries.append(q3)
    # #
    # # Query 4: Medium complexity - SEQ(A, B, AND(E, F))
    # # Shares A, B with queries 1 and 2
    # q4 = SEQ(PrimEvent("A"), PrimEvent("B"), AND(PrimEvent("E"), PrimEvent("F")))
    # q4 = number_children(q4)
    # queries.append(q4)
    # #
    # # Query 4: Complex nested - AND(SEQ(A, B, C), D, SEQ(E, F))
    # # Shares SEQ(A, B, C) with query 1, and has synergy with query 3
    # q5 = AND(
    #     SEQ(PrimEvent("A"), PrimEvent("B"), PrimEvent("C")),
    #     PrimEvent("D"),
    #     SEQ(PrimEvent("E"), PrimEvent("F")),
    # )
    # q5 = number_children(q5)
    # queries.append(q5)
    #
    # # Query 6: AND(A, B, C)
    # q6 = AND(PrimEvent("A"), PrimEvent("B"), PrimEvent("C"))
    # q6 = number_children(q6)
    # queries.append(q6)

    return queries


def generate_hardcoded_selectivities():
    """
    Generate hardcoded selectivities for consistent results across simulation runs.
    This eliminates the randomness in selectivity generation.

    This function generates selectivities for all combinations of events A-F,
    using the selectivities from the first run of the original random simulation.
    """
    # From the original run output - these are the selectivities that were used
    # in the first simulation run to ensure consistency
    selectivities = {
        "CB": 1,
        "BC": 1,  # C-B and B-C: 100% selectivity
        "AD": 0.0394089916562073,
        "DA": 0.0394089916562073,  # A-D and D-A: ~3.9%
        "CA": 0.050898519659186986,
        "AC": 0.050898519659186986,  # C-A and A-C: ~5.1%
        "DF": 1,
        "FD": 1,  # D-F and F-D: 100% selectivity
        "ED": 1,
        "DE": 1,  # E-D and D-E: 100% selectivity
        "EA": 0.06653100823467012,
        "AE": 0.06653100823467012,  # E-A and A-E: ~6.7%
        "DB": 0.08737603662227181,
        "BD": 0.08737603662227181,  # D-B and B-D: ~8.7%
        "EB": 0.08525918368867062,
        "BE": 0.08525918368867062,  # E-B and B-E: ~8.5%
        "CF": 0.032539286285100014,
        "FC": 0.032539286285100014,  # C-F and F-C: ~3.3%
        "EC": 0.09001062335728674,
        "CE": 0.09001062335728674,  # E-C and C-E: ~9.0%
        "CD": 1,
        "DC": 1,  # C-D and D-C: 100% selectivity
        "AB": 0.0013437,
        "BA": 0.0013437,  # A-B and B-A: ~0.13%
        "EF": 0.04513571523602232,
        "FE": 0.04513571523602232,  # E-F and F-E: ~4.5%
        "BF": 0.09888225719599508,
        "FB": 0.09888225719599508,  # B-F and F-B: ~9.9%
        "AF": 0.024810748715466777,
        "FA": 0.024810748715466777,  # A-F and F-A: ~2.5%
    }

    for key in selectivities:
        selectivities[key] /= 1

    # Generate experiment data (used for analysis)
    selectivity_values = list(selectivities.values())
    import numpy as np

    selectivitiesExperimentData = [
        0.01,
        np.median(selectivity_values),
    ]  # [min_bound, median]

    return selectivities, selectivitiesExperimentData


def calculate_ines_max_latency(context, ines_results):
    """
    Reconstruct critical-path latency for INES using Kraken's latency model.

    Returns
        Tuple:
            dict(query -> critical path latency without cloud hop)
            float total processing latency across queries (for reporting)
    """
    acquisition_steps = ines_results[6]
    config = getattr(context, "config", None)
    xi = getattr(config, "xi", 1.0)
    if xi is None:
        xi = 1.0

    processing_order_objects = list(getattr(context, "processing_order", []))
    processing_order = [str(proj) for proj in processing_order_objects]
    key_to_projection = {str(proj): proj for proj in processing_order_objects}

    # Build per-projection latency metrics from acquisition steps
    per_projection_metrics = {}
    for proj_key in processing_order:
        steps = acquisition_steps.get(proj_key)
        if not steps or (isinstance(steps, dict) and "error" in steps):
            continue

        total_transmission_latency = 0.0
        inputs_cost = 0.0
        step_sequence = getattr(steps, "steps", []) or []
        for step in step_sequence:
            if step is None:
                continue
            total_transmission_latency += getattr(step, "total_latency", 0.0) or 0.0
            pull_response = getattr(step, "pull_response", None)
            if pull_response is not None:
                inputs_cost += getattr(pull_response, "cost", 0.0) or 0.0

        projection_obj = key_to_projection.get(proj_key, proj_key)

        sum_of_inputs = context.sum_of_input_rates_per_query.get(projection_obj)
        if sum_of_inputs is None:
            sum_of_inputs = context.sum_of_input_rates_per_query.get(proj_key)
        if sum_of_inputs is None:
            sum_of_inputs = 0.0

        output_rate_tuple = context.h_projrates.get(projection_obj)
        if output_rate_tuple is None:
            output_rate_tuple = context.h_projrates.get(proj_key)

        output_rate = 0.0
        if output_rate_tuple:
            output_rate = (
                output_rate_tuple[1]
                if isinstance(output_rate_tuple, (list, tuple))
                and len(output_rate_tuple) > 1
                else output_rate_tuple[0]
                if isinstance(output_rate_tuple, (list, tuple)) and output_rate_tuple
                else float(output_rate_tuple)
            )

        if sum_of_inputs > 0:
            processing_latency = output_rate * (inputs_cost / sum_of_inputs)
        else:
            processing_latency = 0.0

        per_projection_metrics[proj_key] = {
            "transmission": total_transmission_latency,
            "processing": processing_latency,
        }

    # Prepare dependency lookup using string keys for consistency
    dependency_map: Dict[str, List[str]] = {}
    raw_dependencies = getattr(context, "h_mycombi", {})
    for projection in getattr(context, "processing_order", []):
        proj_key = str(projection)
        deps = raw_dependencies.get(projection)
        if deps is None and proj_key in raw_dependencies:
            deps = raw_dependencies[proj_key]
        normalized_deps: List[str] = []
        if deps:
            for dep in deps:
                if isinstance(dep, str):
                    normalized_deps.append(dep)
                else:
                    normalized_deps.append(str(dep))
        dependency_map[proj_key] = normalized_deps

    processing_latency_cache = {}
    critical_latency_cache = {}

    def calculate_processing_latency(proj_key):
        if proj_key in processing_latency_cache:
            return processing_latency_cache[proj_key]

        own_processing = per_projection_metrics.get(proj_key, {}).get("processing", 0.0)
        total = own_processing
        for predecessor in dependency_map.get(proj_key, []):
            total += calculate_processing_latency(predecessor)
        processing_latency_cache[proj_key] = total
        return total

    def calculate_critical_latency(proj_key):
        if proj_key in critical_latency_cache:
            return critical_latency_cache[proj_key]

        metrics = per_projection_metrics.get(
            proj_key, {"transmission": 0.0, "processing": 0.0}
        )
        transmission_latency = metrics["transmission"]
        processing_latency = metrics["processing"]

        latest_predecessor_latency = 0.0
        for predecessor in dependency_map.get(proj_key, []):
            latest_predecessor_latency = max(
                latest_predecessor_latency,
                calculate_critical_latency(predecessor),
            )

        critical_latency = (
            (processing_latency * xi)
            + transmission_latency
            + latest_predecessor_latency
        )
        critical_latency_cache[proj_key] = critical_latency
        return critical_latency

    # Extract per-query critical latencies
    critical_latency_per_query = {}
    total_processing_latency = 0.0

    # Calculate total processing latency for ALL projections (not just final queries)
    # This matches Kraken's logic of summing individual processing latencies for all placements
    for proj_key in processing_order:
        # Get the individual processing latency for this projection
        individual_processing = per_projection_metrics.get(proj_key, {}).get(
            "processing", 0.0
        )
        total_processing_latency += individual_processing

    # Still calculate critical latency per query for transmission latency reporting
    for query in context.query_workload:
        query_key = str(query)
        latency_value = calculate_critical_latency(query_key)
        critical_latency_per_query[query_key] = latency_value
        try:
            critical_latency_per_query[query] = latency_value
        except TypeError:
            pass

    return critical_latency_per_query, total_processing_latency


def generate_hardcoded_primitive_events():
    """
    Generate hardcoded primitive events for consistent results across simulation runs.
    This ensures that single_selectivity calculations remain consistent when using hardcoded selectivities.

    Returns a fixed event distribution that matches the expected selectivity patterns.
    """
    # Fixed primitive events distribution: A=1000, B=2, C=45, D=203, E=800, F=5
    # This distribution is consistent with the hardcoded selectivities above
    return [1000, 2, 45, 203, 800, 5]  # A=1000, B=2, C=45, D=203, E=800, F=5


def calculate_global_eventrates(context):
    """Calculate global event rates across all nodes in the network."""
    global_event_rates = np.zeros_like(context.network[0].eventrates)
    for node in context.network:
        if len(node.eventrates) > 0:
            # Take every eventrate from the node
            global_event_rates = np.add(global_event_rates, node.eventrates)
    # Convert numpy types to Python native types to avoid 'np.int64(...)' in strings
    result = [
        int(x) if isinstance(x, (np.integer, np.int64, np.int32)) else float(x)
        for x in global_event_rates
    ]
    return result


def calculate_graph_density(graph):
    """Calculate the density of our topology."""
    density = nx.density(graph)
    return density


# ==================== MAIN SIMULATION CLASS ====================


class Simulation:
    """
    Central orchestrator for the entire INES simulation pipeline.

    This class cleanly separates the simulation setup phase (in __init__)
    from the execution phase (in run method), where different placement
    strategies are run sequentially.
    """

    # Class attributes (type declarations)
    allPairs: list
    network: list[Node]
    eventrates: list[list[int]]
    query_workload = None
    selectivities = None
    selectivitiesExperimentData = None
    primitiveEvents: list[int]
    config_single: None
    single_selectivity = None
    nwSize: int
    node_event_ratio: float
    number_eventtypes: int
    eventskew: float
    max_parents: int
    query_size: int
    query_length: int
    networkParams: list
    eval_plan = None
    central_eval_plan = None
    experiment_result = None
    prim = None
    CURRENT_SECTION = ""
    eList = {}
    h_treeDict = {}
    graph_density = None

    # Helper Variables from different Files - namespace issues
    h_network_data = None
    h_rates_data = None
    h_primEvents = None
    h_instances = None
    h_nodes = None
    h_projlist = []
    h_projrates = {}
    h_projsPerQuery = {}
    h_sharedProjectionsDict = {}
    h_sharedProjectionsList = []
    h_eventNodes = None
    h_IndexEventNodes = None
    h_projFilterDict = None
    h_longestPath = None
    h_mycombi = None
    h_criticalMSTypes_criticalMSProjs = None
    h_combiExperimentData = None
    h_criticalMSTypes = None
    h_criticalMSProjs = None
    h_combiDict = {}
    h_globalPartitioninInputTypes = {}
    h_globalSiSInputTypes = {}
    h_placementTreeDict = {}

    # Results from different strategies
    all_push_results = None
    inev_results = None
    ines_results = None
    prepp_from_cloud_result = None
    kraken_results = None
    results = None

    def __init__(self, config: SimulationConfig):
        """
        Initialize the Simulation environment with the provided configuration.
        This method handles ALL setup and pre-computation, but does NOT execute
        any placement strategies.

        Args:
            config: SimulationConfig object containing all simulation parameters
        """
        print("--- Initializing Simulation Environment ---")
        try:
            # ------ SETUP -------#
            start_time_setup = time.time()
            self.start_time_setup = start_time_setup
            # Initialize for future reference
            self.entire_simulation_time = 0
            # Store configuration and extract parameters
            self.config = config
            self.nwSize = config.network_size
            self.node_event_ratio = config.node_event_ratio
            self.number_eventtypes = config.num_event_types
            self.eventskew = config.event_skew
            self.max_parents = config.max_parents
            self.query_size = config.query_size
            self.query_length = config.query_length
            self.latency_threshold = config.latency_threshold

            # Initialize result schema for experiments
            self.schema = [
                "ID",
                "TransmissionRatio",
                "Transmission",
                "INEvTransmission",
                "FilterUsed",
                "Nodes",
                "EventSkew",
                "EventNodeRatio",
                "WorkloadSize",
                "NumberProjections",
                "MinimalSelectivity",
                "MedianSelectivity",
                "CombigenComputationTime",
                "Efficiency",
                "PlacementComputationTime",
                "centralHopLatency",
                "Depth",
                "CentralTransmission",
                "LowerBound",
                "EventTypes",
                "MaximumParents",
                "exact_costs",
                "PushPullTime",
                "MaxPushPullLatency",
                "endTransmissionRatio",
            ]

            # Initialize core simulation parameters
            from ines.projections import generate_all_projections

            eventrates_per_source = generate_eventrates(
                config.event_skew, config.num_event_types
            )
            self.eventrates = eventrates_per_source
            self.networkParams = [
                self.eventskew,
                self.number_eventtypes,
                self.node_event_ratio,
                self.nwSize,
                min(self.eventrates) / max(self.eventrates),
            ]

            # Generate primitive events - use hardcoded values for consistent selectivity calculations
            if config.is_selectivities_fixed():
                self.primitiveEvents = generate_hardcoded_primitive_events()
            else:
                self.primitiveEvents = eventrates_per_source

            # Initialize simulation components based on configuration mode
            self._initialize_network_topology()

            # Convert all node eventrates to Python native types to prevent numpy type strings
            self._convert_node_eventrates_to_python()

            self._initialize_network_graph()
            self._initialize_query_workload()
            self._initialize_selectivities()

            self.graph_density = calculate_graph_density(self.graph)

            global_event_rates = calculate_global_eventrates(self)
            self.primitiveEvents = global_event_rates
            self.eventrates = global_event_rates

            # Generate configuration and single selectivities for detailed analysis
            self.config_single = generate_config_buffer(
                self.network, self.query_workload, self.selectivities
            )
            deterministic_flag = self.config.is_selectivities_fixed()

            """
            Finn Glück 31.08.2025:
            When using multiple runs the legacy system produces an error since some selectivities are not initialized properly.
            This is a quick fix to ensure that all selectivities are initialized properly.
            """
            # Get all events
            all_events_array_string = list(
                string.ascii_uppercase[: config.num_event_types]
            )

            self.single_selectivity = initialize_single_selectivity(
                CURRENT_SECTION=self.CURRENT_SECTION,
                config_single=self.config_single,
                workload=self.query_workload,
                is_deterministic=deterministic_flag,
                all_events_array_string=all_events_array_string,
            )

            # Initialize remaining simulation components (legacy processing pipeline)
            (
                self.h_network_data,
                self.h_rates_data,
                self.h_primEvents,
                self.h_instances,
                self.h_nodes,
                self.h_etb_rates,
            ) = initialize_globals(self.network)
            self.h_eventNodes, self.h_IndexEventNodes = init_event_nodes(
                self.h_nodes, self.h_network_data
            )
            (
                self.h_projlist,
                self.h_projrates,
                self.h_projsPerQuery,
                self.h_sharedProjectionsDict,
                self.h_sharedProjectionsList,
            ) = generate_all_projections(self)
            self.h_projFilterDict = populate_proj_filter_dict(self)
            self.h_projFilterDict = remove_filters(self)

            start_time_generate_combigen = time.time()
            (
                self.h_mycombi,
                self.h_combiDict,
                self.h_criticalMSTypes_criticalMSProjs,
                self.h_combiExperimentData,
                self.h_primitive_events,
            ) = generate_combigen(self)

            end_time_generate_combigen = time.time()
            self.combigen_computation_time = (
                end_time_generate_combigen - start_time_generate_combigen
            )

            self.h_criticalMSTypes, self.h_criticalMSProjs = (
                self.h_criticalMSTypes_criticalMSProjs
            )

            # Create optimized rate lookup structure for fast dependency rate calculations
            self.h_local_rate_lookup = self._create_optimized_rate_lookup()

            # Calculate sum of primitive input rates per query for processing latency calculations
            self.sum_of_input_rates_per_query = (
                self._calculate_sum_of_primitive_input_rates_per_query()
            )

            end_time_setup = time.time()
            self.setup_time = end_time_setup - start_time_setup

            # calculate the average selectivity
            self.average_selectivity = sum(self.selectivities.values()) / len(
                self.selectivities
            )

            print("--- SETUP COMPLETE ---")
        except Exception as e:
            logger.error(msg=e, exc_info=True)
            raise

    def run(self):
        """
        Execute all placement strategies sequentially and gather the results.

        This method runs the following strategies in order:
        1. All Push (placeholder)
        2. INEv
        3. INES (using INEv results)
        4. PrePP from Cloud (placeholder)
        5. Kraken
        6. Write Results
        """

        try:
            # ----- ALL PUSH CALCULATION -----#
            print("--- Running All Push Computation ---")
            self.all_push_results = compute_all_push(self)
            all_push_latency = self.all_push_results.get("transmission_latency", 0.0)

            # Only multiply threshold here for normal simulations
            # For trade-off study, multiplication happens inside run_kraken_solver
            if (
                self.latency_threshold is not None
                and not self.config.run_latency_tradeoff_study
            ):
                self.latency_threshold *= all_push_latency
            print("--- ALL PUSH COMPUTATION COMPLETE ---")

            # ----- INEV AND INES DISABLED -----#
            # Resource constraint experiment: only comparing All Push, PrePP from Cloud, and Kraken
            self.inev_results = None
            self.ines_results = None
            self.eval_plan = None
            self.central_eval_plan = None
            self.experiment_result = None
            self.results = None
            self.raw_ines_prepp_result = None

            # Compute processing order (needed by PrePP from Cloud and Kraken)
            from inev.process_combination import compute_dependencies

            dependencies = compute_dependencies(
                self, self.h_mycombi, self.h_criticalMSTypes
            )
            self.processing_order = sorted(
                dependencies.keys(), key=lambda x: dependencies[x]
            )

            # Generate reused_section for PrePP from Cloud
            from prepp.generate_eval_plan import network_text, selectivities_text

            reused_section = (
                network_text(self.network)
                + "\n"
                + selectivities_text(self.selectivities)
                + "\n"
            )

            # ----- SOLELY PREPP COMPUTATION (from cloud) -----#
            print("--- Running PrePP from Cloud Computation ---")
            self.prepp_from_cloud_result = calculate_prepp_from_cloud(
                self, reused_section
            )
            print("--- PREPP FROM CLOUD COMPUTATION COMPLETE ---")

            # ----- KRAKEN COMPUTATION -----#
            print("--- Running Kraken Computation ---")
            from src.kraken.run import run_kraken_solver

            # Check if running latency trade-off study
            if self.config.run_latency_tradeoff_study:
                # Run dual-run experiment: baseline + constrained
                self.kraken_results = run_kraken_solver(
                    ines_context=self, run_latency_tradeoff_study=True
                )
            else:
                # Normal multi-strategy run
                self.kraken_results = run_kraken_solver(
                    ines_context=self,
                    strategies_to_run=[{"name": "greedy"}],
                    compare_within_kraken=False,
                )
            print("--- KRAKEN COMPUTATION COMPLETE ---")

            self.entire_simulation_time = self.start_time_setup - time.time()

            # ----- WRITE RESULTS -----#
            self._write_results()
            print("--- All computations complete and results saved. ---")
        except Exception as e:
            logger.error(msg=e, exc_info=True)
            raise

    def _write_results(self, output_dataset_name: Optional[str] = None):
        """Write all strategy results to a unified parquet file."""
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
        from pathlib import Path

        # Allow config to override output dataset name
        if self.config.output_dataset_name:
            output_dataset_name = self.config.output_dataset_name

        try:
            print("--- Writing unified results to parquet ---")

            row: Dict[str, Any] = {}

            def safe_float(value: Any) -> Optional[float]:
                """Safely convert any numeric value to float, handling None."""
                if value is None:
                    return None
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            def populate_basic(prefix: str, result: Optional[Dict[str, Any]]):
                """Populate row with basic metrics, ensuring all numeric values are floats."""
                if not result:
                    return
                row[f"{prefix}_status"] = result.get("status", "unknown")
                row[f"{prefix}_cost"] = safe_float(result.get("cost"))
                row[f"{prefix}_transmission_latency"] = safe_float(
                    result.get("transmission_latency")
                )
                row[f"{prefix}_processing_latency"] = safe_float(
                    result.get("processing_latency")
                )
                row[f"{prefix}_computing_time"] = safe_float(
                    result.get("computing_time")
                )

            # Check if this is a latency trade-off study
            if (
                self.kraken_results
                and self.kraken_results.get("is_tradeoff_study") is True
            ):
                print("--- Writing latency trade-off study results ---")

                # Extract results from dual-run
                cost_focused_results = self.kraken_results.get(
                    "cost_focused_results", {}
                )
                tradeoff_results = self.kraken_results.get("tradeoff_results", {})
                run_params = self.kraken_results.get("run_parameters", {})

                # Populate cost-focused results - flatten structure for populate_basic
                cost_focused_metrics = cost_focused_results.get("metrics", {})
                cost_focused_flat = {
                    "status": cost_focused_results.get("status", "unknown"),
                    "cost": cost_focused_metrics.get("total_cost"),
                    "transmission_latency": cost_focused_metrics.get("max_latency"),
                    "processing_latency": cost_focused_metrics.get(
                        "cumulative_processing_latency"
                    ),
                    "computing_time": cost_focused_results.get(
                        "execution_time_seconds"
                    ),
                }
                populate_basic("cost_focused_greedy", cost_focused_flat)

                # Add extended cost-focused metrics
                if cost_focused_results.get("status") == "success":
                    row["cost_focused_greedy_workload_cost"] = safe_float(
                        cost_focused_metrics.get("workload_cost")
                    )
                    row["cost_focused_greedy_num_placements"] = safe_float(
                        cost_focused_metrics.get("num_placements")
                    )
                    row["cost_focused_greedy_placements_at_cloud"] = safe_float(
                        cost_focused_metrics.get("placements_at_cloud")
                    )
                    row["cost_focused_greedy_average_cost_per_placement"] = safe_float(
                        cost_focused_metrics.get("average_cost_per_placement")
                    )

                # Populate trade-off results - flatten structure for populate_basic
                tradeoff_metrics = tradeoff_results.get("metrics", {})
                tradeoff_flat = {
                    "status": tradeoff_results.get("status", "unknown"),
                    "cost": tradeoff_metrics.get("total_cost"),
                    "transmission_latency": tradeoff_metrics.get("max_latency"),
                    "processing_latency": tradeoff_metrics.get(
                        "cumulative_processing_latency"
                    ),
                    "computing_time": tradeoff_results.get("execution_time_seconds"),
                }
                populate_basic("tradeoff_greedy", tradeoff_flat)

                # Add extended trade-off metrics
                if tradeoff_results.get("status") == "success":
                    row["tradeoff_greedy_workload_cost"] = safe_float(
                        tradeoff_metrics.get("workload_cost")
                    )
                    row["tradeoff_greedy_num_placements"] = safe_float(
                        tradeoff_metrics.get("num_placements")
                    )
                    row["tradeoff_greedy_placements_at_cloud"] = safe_float(
                        tradeoff_metrics.get("placements_at_cloud")
                    )
                    row["tradeoff_greedy_average_cost_per_placement"] = safe_float(
                        tradeoff_metrics.get("average_cost_per_placement")
                    )

                # Add run parameters
                row["all_push_latency_reference"] = safe_float(
                    run_params.get("all_push_latency")
                )
                cost_focused_weights = run_params.get("cost_focused_weights", {})
                row["cost_focused_cost_weight"] = safe_float(
                    cost_focused_weights.get("cost_weight")
                )
                row["cost_focused_latency_weight"] = safe_float(
                    cost_focused_weights.get("latency_weight")
                )
                tradeoff_weights = run_params.get("tradeoff_weights", {})
                row["tradeoff_cost_weight"] = safe_float(
                    tradeoff_weights.get("cost_weight")
                )
                row["tradeoff_latency_weight"] = safe_float(
                    tradeoff_weights.get("latency_weight")
                )

                # Add configuration parameters
                row["network_size"] = safe_float(self.config.network_size)
                row["event_skew"] = safe_float(self.config.event_skew)
                row["node_event_ratio"] = safe_float(self.config.node_event_ratio)
                row["max_parents"] = safe_float(self.config.max_parents)
                row["parent_factor"] = safe_float(self.config.parent_factor)
                row["num_event_types"] = safe_float(self.config.num_event_types)
                row["query_size"] = safe_float(self.config.query_size)
                row["query_length"] = safe_float(self.config.query_length)
                row["xi"] = safe_float(self.config.xi)
                row["mode"] = (
                    self.config.mode.value
                    if hasattr(self.config.mode, "value")
                    else str(self.config.mode)
                )
                row["algorithm"] = (
                    self.config.algorithm.value
                    if hasattr(self.config.algorithm, "value")
                    else str(self.config.algorithm)
                )

                # Create DataFrame
                df = pd.DataFrame([row])

                # Define explicit PyArrow schema for trade-off study
                schema_fields = [
                    # Cost-focused greedy metrics
                    pa.field("cost_focused_greedy_status", pa.string()),
                    pa.field("cost_focused_greedy_cost", pa.float64()),
                    pa.field("cost_focused_greedy_transmission_latency", pa.float64()),
                    pa.field("cost_focused_greedy_processing_latency", pa.float64()),
                    pa.field("cost_focused_greedy_computing_time", pa.float64()),
                    pa.field("cost_focused_greedy_workload_cost", pa.float64()),
                    pa.field("cost_focused_greedy_num_placements", pa.float64()),
                    pa.field("cost_focused_greedy_placements_at_cloud", pa.float64()),
                    pa.field(
                        "cost_focused_greedy_average_cost_per_placement", pa.float64()
                    ),
                    # Trade-off greedy metrics
                    pa.field("tradeoff_greedy_status", pa.string()),
                    pa.field("tradeoff_greedy_cost", pa.float64()),
                    pa.field("tradeoff_greedy_transmission_latency", pa.float64()),
                    pa.field("tradeoff_greedy_processing_latency", pa.float64()),
                    pa.field("tradeoff_greedy_computing_time", pa.float64()),
                    pa.field("tradeoff_greedy_workload_cost", pa.float64()),
                    pa.field("tradeoff_greedy_num_placements", pa.float64()),
                    pa.field("tradeoff_greedy_placements_at_cloud", pa.float64()),
                    pa.field(
                        "tradeoff_greedy_average_cost_per_placement", pa.float64()
                    ),
                    # Run parameters
                    pa.field("all_push_latency_reference", pa.float64()),
                    pa.field("cost_focused_cost_weight", pa.float64()),
                    pa.field("cost_focused_latency_weight", pa.float64()),
                    pa.field("tradeoff_cost_weight", pa.float64()),
                    pa.field("tradeoff_latency_weight", pa.float64()),
                    # Configuration parameters
                    pa.field("network_size", pa.float64()),
                    pa.field("event_skew", pa.float64()),
                    pa.field("node_event_ratio", pa.float64()),
                    pa.field("max_parents", pa.float64()),
                    pa.field("parent_factor", pa.float64()),
                    pa.field("num_event_types", pa.float64()),
                    pa.field("query_size", pa.float64()),
                    pa.field("query_length", pa.float64()),
                    pa.field("xi", pa.float64()),
                    pa.field("mode", pa.string()),
                    pa.field("algorithm", pa.string()),
                ]

                # Only include fields that exist in the DataFrame
                schema_fields = [
                    field for field in schema_fields if field.name in df.columns
                ]
                explicit_schema = pa.schema(schema_fields)

                # Convert to PyArrow table
                table = pa.Table.from_pandas(
                    df, schema=explicit_schema, preserve_index=False
                )

                # Write to parquet
                output_dir = Path(
                    f"result/{output_dataset_name or 'latency_tradeoff_study'}.parquet"
                )
                output_dir.mkdir(parents=True, exist_ok=True)
                pq.write_to_dataset(table, root_path=str(output_dir))

                print(f"--- Trade-off study results written to {output_dir} ---")
                return

            # Normal simulation result writing
            populate_basic("all_push", self.all_push_results)
            if self.inev_results is not None:
                populate_basic("inev", self.inev_results)
            if self.ines_results is not None:
                populate_basic("ines", self.ines_results)
            populate_basic("prepp", self.prepp_from_cloud_result)

            if self.kraken_results and "strategies" in self.kraken_results:
                for strategy_name, strategy_result in self.kraken_results[
                    "strategies"
                ].items():
                    prefix = f"kraken_{strategy_name}"
                    status = strategy_result.get("status", "unknown")
                    metrics = (
                        strategy_result.get("metrics", {})
                        if status == "success"
                        else {}
                    )

                    print(
                        f"DEBUG _write_results: Adding columns for strategy '{strategy_name}' with prefix '{prefix}'"
                    )

                    row[f"{prefix}_status"] = status
                    row[f"{prefix}_cost"] = safe_float(metrics.get("total_cost"))
                    row[f"{prefix}_transmission_latency"] = safe_float(
                        metrics.get("max_latency")
                    )
                    row[f"{prefix}_processing_latency"] = safe_float(
                        metrics.get("cumulative_processing_latency")
                    )
                    row[f"{prefix}_computing_time"] = safe_float(
                        strategy_result.get("execution_time_seconds")
                    )
                    row[f"{prefix}_workload_cost"] = safe_float(
                        metrics.get("workload_cost")
                    )
                    row[f"{prefix}_num_placements"] = safe_float(
                        metrics.get("num_placements")
                    )
                    row[f"{prefix}_placements_at_cloud"] = safe_float(
                        metrics.get("placements_at_cloud")
                    )
                    row[f"{prefix}_average_cost_per_placement"] = safe_float(
                        metrics.get("average_cost_per_placement")
                    )

            print(
                f"DEBUG _write_results: Row contains these kraken columns: {[k for k in row.keys() if 'kraken' in k]}"
            )

            # Add configuration information to results (cast all to float for consistency)
            row["network_size"] = safe_float(self.config.network_size)
            row["event_skew"] = safe_float(self.config.event_skew)
            row["node_event_ratio"] = safe_float(self.config.node_event_ratio)
            row["max_parents"] = safe_float(self.config.max_parents)
            row["parent_factor"] = safe_float(self.config.parent_factor)
            row["num_event_types"] = safe_float(self.config.num_event_types)
            row["query_size"] = safe_float(self.config.query_size)
            row["query_length"] = safe_float(self.config.query_length)
            row["xi"] = safe_float(self.config.xi)
            row["latency_threshold"] = safe_float(self.config.latency_threshold)
            row["mode"] = (
                self.config.mode.value
                if hasattr(self.config.mode, "value")
                else str(self.config.mode)
            )
            row["algorithm"] = (
                self.config.algorithm.value
                if hasattr(self.config.algorithm, "value")
                else str(self.config.algorithm)
            )
            row["graph_density"] = safe_float(getattr(self, "graph_density", None))

            row["entire_simulation_time"] = safe_float(
                getattr(self, "entire_simulation_time", None)
            )
            row["setup_time"] = safe_float(getattr(self, "setup_time", None))
            row["combigen_computation_time"] = safe_float(
                getattr(self, "combigen_computation_time", None)
            )
            row["average_selectivity"] = safe_float(
                getattr(self, "average_selectivity", None)
            )

            if not row:
                print("--- No results to write ---")
                return

            # Create DataFrame from row
            df = pd.DataFrame([row])
            print(
                f"DEBUG: DataFrame columns (total {len(df.columns)}): {[c for c in df.columns if 'kraken' in c]}"
            )

            # Define explicit PyArrow schema to prevent type inference issues
            # All numeric columns are explicitly set to float64 (double in PyArrow)
            schema_fields = [
                # All Push metrics
                pa.field("all_push_status", pa.string()),
                pa.field("all_push_cost", pa.float64()),
                pa.field("all_push_transmission_latency", pa.float64()),
                pa.field("all_push_processing_latency", pa.float64()),
                pa.field("all_push_computing_time", pa.float64()),
                # INEv metrics
                pa.field("inev_status", pa.string()),
                pa.field("inev_cost", pa.float64()),
                pa.field("inev_transmission_latency", pa.float64()),
                pa.field("inev_processing_latency", pa.float64()),
                pa.field("inev_computing_time", pa.float64()),
                # INES metrics
                pa.field("ines_status", pa.string()),
                pa.field("ines_cost", pa.float64()),
                pa.field("ines_transmission_latency", pa.float64()),
                pa.field("ines_processing_latency", pa.float64()),
                pa.field("ines_computing_time", pa.float64()),
                # PrePP metrics
                pa.field("prepp_status", pa.string()),
                pa.field("prepp_cost", pa.float64()),
                pa.field("prepp_transmission_latency", pa.float64()),
                pa.field("prepp_processing_latency", pa.float64()),
                pa.field("prepp_computing_time", pa.float64()),
                # Kraken metrics (dynamic strategy names handled below)
                # Greedy strategy
                pa.field("kraken_greedy_status", pa.string()),
                pa.field("kraken_greedy_cost", pa.float64()),
                pa.field("kraken_greedy_transmission_latency", pa.float64()),
                pa.field("kraken_greedy_processing_latency", pa.float64()),
                pa.field("kraken_greedy_computing_time", pa.float64()),
                pa.field("kraken_greedy_workload_cost", pa.float64()),
                pa.field("kraken_greedy_num_placements", pa.float64()),
                pa.field("kraken_greedy_placements_at_cloud", pa.float64()),
                pa.field("kraken_greedy_average_cost_per_placement", pa.float64()),
                # K-Beam strategy
                pa.field("kraken_k_beam_status", pa.string()),
                pa.field("kraken_k_beam_cost", pa.float64()),
                pa.field("kraken_k_beam_transmission_latency", pa.float64()),
                pa.field("kraken_k_beam_processing_latency", pa.float64()),
                pa.field("kraken_k_beam_computing_time", pa.float64()),
                pa.field("kraken_k_beam_workload_cost", pa.float64()),
                pa.field("kraken_k_beam_num_placements", pa.float64()),
                pa.field("kraken_k_beam_placements_at_cloud", pa.float64()),
                pa.field("kraken_k_beam_average_cost_per_placement", pa.float64()),
                # Configuration parameters
                pa.field("network_size", pa.float64()),
                pa.field("event_skew", pa.float64()),
                pa.field("node_event_ratio", pa.float64()),
                pa.field("max_parents", pa.float64()),
                pa.field("parent_factor", pa.float64()),
                pa.field("num_event_types", pa.float64()),
                pa.field("query_size", pa.float64()),
                pa.field("query_length", pa.float64()),
                pa.field("xi", pa.float64()),
                pa.field("latency_threshold", pa.float64()),
                pa.field("mode", pa.string()),
                pa.field("algorithm", pa.string()),
                pa.field("graph_density", pa.float64()),
                # Timing metrics
                pa.field("entire_simulation_time", pa.float64()),
                pa.field("setup_time", pa.float64()),
                pa.field("combigen_computation_time", pa.float64()),
                pa.field("average_selectivity", pa.float64()),
            ]

            # Only include fields that exist in the DataFrame
            original_field_count = len(schema_fields)
            schema_fields = [
                field for field in schema_fields if field.name in df.columns
            ]
            print(
                f"DEBUG: Schema filtering: {original_field_count} -> {len(schema_fields)} fields"
            )
            kraken_schema_fields = [f.name for f in schema_fields if "kraken" in f.name]
            print(f"DEBUG: Kraken columns in final schema: {kraken_schema_fields}")
            explicit_schema = pa.schema(schema_fields)

            # Convert DataFrame to PyArrow table with explicit schema
            table = pa.Table.from_pandas(
                df, schema=explicit_schema, preserve_index=False
            )

            output_dir = Path(
                f"result/{output_dataset_name or 'unified_results'}.parquet"
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            existing_files = {file.name for file in output_dir.glob("*.parquet")}

            pq.write_to_dataset(table, root_path=str(output_dir))

            new_files = [
                file
                for file in output_dir.glob("*.parquet")
                if file.name not in existing_files
            ]
            if not new_files and existing_files:
                new_files = sorted(
                    output_dir.glob("*.parquet"),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )[:1]

            for file_path in new_files:
                try:
                    pq.read_table(file_path)
                except Exception as validation_error:  # noqa: BLE001
                    logger.error(
                        "Parquet validation failed for %s",
                        file_path,
                        exc_info=validation_error,
                    )
                    raise RuntimeError(
                        f"Parquet validation failed for {file_path}"
                    ) from validation_error

            print(f"--- Results written to {output_dir} ---")
        except Exception as e:
            logger.error("Failed to write unified results", exc_info=e)
            raise

    # ==================== HELPER METHODS ====================

    def _calculate_sum_of_primitive_input_rates_per_query(self) -> Dict:
        """
        Calculate the sum of all primitive input rates for each query.

        For each query, this method identifies all primitive events used in the query
        and sums their global input rates. This value represents the total data volume
        that would be transmitted if all primitive events were pushed to the query
        processing location.

        Returns:
            Dictionary mapping each query object to the sum of its primitive event rates.
            Example: {query1: 1845.0, query2: 1002.0, ...}
        """
        from core.proj_string import filter_numbers

        sum_of_input_rates = {}

        for query in self.h_mycombi:
            # Get unique event types (e.g., ['A1', 'A2', 'B'] -> {0, 1} for A and B)
            unique_indices = {
                ord(filter_numbers(event_name)) - ord("A")
                for event_name in query.leafs()
            }

            # Sum rates for unique indices
            sum_of_input_rates[query] = sum(
                self.primitiveEvents[idx]
                for idx in unique_indices
                if idx < len(self.primitiveEvents)
            )

        return sum_of_input_rates

    def _create_optimized_rate_lookup(self) -> Dict[str, Dict[int, float]]:
        """
        Create optimized data structure for O(1) rate lookups.

        Returns:
            Dictionary structure:
            {
                'A': {6: 1000.0, 8: 0.0, 10: 0.0},  # Local rates for event A per node
                'B': {7: 2.0, 10: 0.0},              # Local rates for event B per node
                'C': {7: 45.0, 8: 45.0, 11: 0.0},   # etc.
                ...
            }
        """
        local_rate_lookup = {}

        # For each primitive event type
        for event_type, node_list in self.h_nodes.items():
            local_rate_lookup[event_type] = {}

            # For each node that has this event type
            for node_id in node_list:
                # Calculate local rate for this event at this node
                if node_id < len(self.network):
                    node = self.network[node_id]
                    # Get the index of this event type (A=0, B=1, etc.)
                    event_index = ord(event_type) - ord("A")
                    if event_index < len(node.eventrates):
                        local_rate = float(node.eventrates[event_index])
                        local_rate_lookup[event_type][node_id] = local_rate
                    else:
                        local_rate_lookup[event_type][node_id] = 0.0
                else:
                    local_rate_lookup[event_type][node_id] = 0.0

        return local_rate_lookup

    def _initialize_network_topology(self):
        """Create network topology based on configuration mode."""
        if self.config.is_topology_fixed():
            self.root, self.network, self.eList = create_hardcoded_tree()
        else:
            self.root, self.network, self.eList = create_random_tree(
                self.nwSize, self.eventrates, self.node_event_ratio, self.max_parents
            )

    def _convert_node_eventrates_to_python(self):
        """Convert all node eventrates from numpy types to Python native types.

        This prevents 'np.int64(...)' representations from appearing in stringified buffers.
        """
        for node in self.network:
            if hasattr(node, "eventrates") and node.eventrates:
                # Convert each element to Python native type
                node.eventrates = [
                    int(x)
                    if isinstance(
                        x, (np.integer, np.int64, np.int32, np.int16, np.int8)
                    )
                    else float(x)
                    if isinstance(x, (np.floating, np.float64, np.float32))
                    else x
                    for x in node.eventrates
                ]

    def _initialize_network_graph(self):
        """Initialize network graph and distance calculations."""
        self.graph = create_fog_graph(self.network)
        self.allPairs = populate_all_pairs(self.graph)
        self.h_longestPath = get_longest(self.allPairs)

    def _initialize_query_workload(self):
        """Generate query workload based on configuration mode."""
        if self.config.is_workload_fixed():
            self.query_workload = generate_hardcoded_workload()
        else:
            self.query_workload = generate_workload(
                self.query_size, self.query_length, self.primitiveEvents
            )

    def _initialize_selectivities(self):
        """Initialize selectivities based on configuration mode."""
        if self.config.is_selectivities_fixed():
            self.selectivities, self.selectivitiesExperimentData = (
                generate_hardcoded_selectivities()
            )
        else:
            self.selectivities, self.selectivitiesExperimentData = (
                initialize_selectivities(self.primitiveEvents)
            )
