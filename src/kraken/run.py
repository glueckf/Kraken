"""
Kraken 2.0 Entry Point and Orchestrator

This module serves as the main entry point for the Kraken 2.0 solver framework.
It orchestrates the problem setup, strategy execution, and result reporting with
a clean, modern interface.
"""

from typing import Any, Dict, List
import time
import uuid

from inev.process_combination import compute_dependencies
from core.all_pairs import create_routing_dict

from kraken.problem import PlacementProblem
from kraken.data.state import SolutionCandidate
from kraken.utils.results_logger import (
    initialize_logging,
    write_detailed_log,
    write_run_results,
    write_kraken_comparison_log,
)


def run_kraken_solver(
    simulation_context: Any,
    strategies_to_run: List[Any] = None,
    enable_detailed_logging: bool = False,
    compare_within_kraken: bool = False,
    run_latency_tradeoff_study: bool = False,
) -> Dict[str, Any]:
    """
    Main entry point for the Kraken 2.0 solver framework.

    Orchestrates the entire solving process: setup, execution, and reporting.

    Args:
        simulation_context: The simulation context object containing all problem data.
        strategies_to_run: List of strategy configurations (dicts or enums) specifying which strategies to execute.
        enable_detailed_logging: If True, logs every placement decision to CSV for analysis.
        compare_within_kraken: If True, logs all strategy results in a single wide-format row for comparison.
        run_latency_tradeoff_study: If True, runs dual-run experiment (baseline + constrained greedy).

    Returns:
        Dictionary containing execution results with the following structure:
        {
            "run_id": UUID,
            "strategies": {
                "GREEDY": {"status": "success", "solution": ..., "metrics": {...}},
                ...
            },
            "problem_info": {...},
            "best_solution": SolutionCandidate or None
        }
    """
    # Handle latency trade-off study mode
    if run_latency_tradeoff_study:
        # Validate preconditions
        if (
            not hasattr(simulation_context, "all_push_results")
            or not simulation_context.all_push_results
        ):
            raise ValueError(
                "All Push results are missing. Cannot run latency trade-off study."
            )

        all_push_latency = simulation_context.all_push_results.get(
            "transmission_latency", 0.0
        )
        if all_push_latency == 0.0:
            raise ValueError(
                "All Push latency is 0. Cannot calculate relative threshold."
            )

        # Get parameters
        latency_threshold_factor = simulation_context.config.latency_threshold
        original_cost_weight = simulation_context.config.cost_weight

        # Store original state
        original_config_threshold = simulation_context.latency_threshold

        # Calculate absolute threshold
        absolute_threshold = latency_threshold_factor * all_push_latency

        # Setup common problem context
        context = _gather_problem_parameters(simulation_context)
        dependencies = compute_dependencies(
            simulation_context, simulation_context.h_mycombi, simulation_context.h_criticalMSTypes
        )
        processing_order = sorted(dependencies.keys(), key=lambda x: dependencies[x])

        # Run 1: Baseline (no latency constraint)
        print("--- Running Baseline Greedy (no latency constraint) ---")
        simulation_context.latency_threshold = None
        context_baseline = _gather_problem_parameters(simulation_context)
        problem_baseline = PlacementProblem(processing_order, context_baseline, False)

        baseline_results = {}
        try:
            from kraken.search.greedy import GreedySearch

            strategy = GreedySearch()
            baseline_start = time.time()
            solution = strategy.solve(problem_baseline)
            baseline_end = time.time()

            metrics = _calculate_solution_metrics(
                solution, problem_baseline, simulation_context
            )
            baseline_results = {
                "status": "success",
                "solution": solution,
                "metrics": metrics,
                "execution_time_seconds": baseline_end - baseline_start,
            }
        except Exception as e:
            baseline_results = {
                "status": "failed",
                "error": str(e),
                "execution_time_seconds": 0.0,
            }

        # Run 2: Constrained (with latency constraint)
        print(
            f"--- Running Constrained Greedy (threshold={absolute_threshold:.2f}) ---"
        )
        simulation_context.latency_threshold = absolute_threshold
        context_constrained = _gather_problem_parameters(simulation_context)
        problem_constrained = PlacementProblem(
            processing_order, context_constrained, False
        )

        constrained_results = {}
        try:
            from kraken.search.greedy import GreedySearch

            strategy = GreedySearch()
            constrained_start = time.time()
            solution = strategy.solve(problem_constrained)
            constrained_end = time.time()

            metrics = _calculate_solution_metrics(
                solution, problem_constrained, simulation_context
            )
            constrained_results = {
                "status": "success",
                "solution": solution,
                "metrics": metrics,
                "execution_time_seconds": constrained_end - constrained_start,
            }
        except Exception as e:
            constrained_results = {
                "status": "failed",
                "error": str(e),
                "execution_time_seconds": 0.0,
            }

        # Restore original state
        simulation_context.latency_threshold = original_config_threshold

        # Return special dictionary
        return {
            "is_tradeoff_study": True,
            "baseline_greedy_results": baseline_results,
            "constrained_greedy_results": constrained_results,
            "run_parameters": {
                "latency_threshold_factor": latency_threshold_factor,
                "latency_threshold_absolute": absolute_threshold,
                "cost_weight": original_cost_weight,
                "latency_weight": 1.0 - original_cost_weight,
            },
        }

    # Normal multi-strategy run
    run_id = uuid.uuid4()
    start_time = time.time()

    # Initialize detailed logging if enabled
    if enable_detailed_logging:
        initialize_logging()

    # Phase 1: Setup & Data Gathering
    context = _gather_problem_parameters(simulation_context)

    # Calculate processing order using dependency computation
    dependencies = compute_dependencies(
        simulation_context, simulation_context.h_mycombi, simulation_context.h_criticalMSTypes
    )

    processing_order = sorted(dependencies.keys(), key=lambda x: dependencies[x])

    # Phase 2: Problem Instantiation
    problem = PlacementProblem(processing_order, context, enable_detailed_logging)

    # Phase 3: Strategy Execution Loop
    strategy_results = {}
    master_log_data = []  # Accumulate logs across all strategies

    for strategy_config in strategies_to_run:
        # Get config, default to string if old format is used
        if isinstance(strategy_config, dict):
            algorithm_name = strategy_config.get("name")
            k_value = strategy_config.get("k", None)
            use_upper_bound = strategy_config.get("use_upper_bound", True)
            disable_heuristic = strategy_config.get("disable_heuristic", False)
        else:
            algorithm_name = (
                str(strategy_config.value)
                if hasattr(strategy_config, "value")
                else str(strategy_config)
            )
            k_value = None
            use_upper_bound = True
            disable_heuristic = False

        # Generate a unique strategy name for logging
        if algorithm_name == "k_beam" and k_value is not None:
            strategy_name = f"k_beam_k={k_value}"
        elif algorithm_name == "dag_star":
            base = "dag_star_h0" if disable_heuristic else "dag_star"
            strategy_name = f"{base}_b" if use_upper_bound else base
        elif algorithm_name:
            strategy_name = algorithm_name
        else:
            # Handle bad config
            strategy_results["unknown_strategy"] = {
                "status": "failure",
                "error": "Invalid strategy config. Must be dict or enum.",
                "execution_time_seconds": 0.0,
                "k_value": None,
            }
            continue

        # Select and execute strategy
        strategy_start = time.time()
        try:
            # Pass the dict config directly to the factory
            strategy = _select_strategy(strategy_config)
            solution = strategy.solve(problem)
            strategy_end = time.time()

            # Calculate solution metrics
            metrics = _calculate_solution_metrics(solution, problem, simulation_context)

            strategy_results[strategy_name] = {
                "status": "success",
                "solution": solution,
                "metrics": metrics,
                "execution_time_seconds": strategy_end - strategy_start,
                "k_value": k_value,
            }

            # Collect and enrich detailed logs if enabled
            if enable_detailed_logging and hasattr(problem, "detailed_log"):
                enriched_log = _enrich_log_with_solution(
                    problem.detailed_log, solution, str(run_id), strategy_name, problem
                )
                master_log_data.extend(enriched_log)

        except (ValueError, NotImplementedError) as e:
            strategy_end = time.time()
            strategy_results[strategy_name] = {
                "status": "failure",
                "error": str(e),
                "execution_time_seconds": strategy_end - strategy_start,
                "k_value": k_value,
            }

    # Write detailed logs to Parquet if enabled
    if enable_detailed_logging and master_log_data:
        write_detailed_log(str(run_id), master_log_data)

    # Phase 4: Final Report Assembly
    end_time = time.time()

    # Prepare and write run results summary
    if compare_within_kraken:
        # Build the wide-format, single-row summary
        comparison_data = _prepare_kraken_comparison_summary(
            str(run_id), strategy_results, problem, simulation_context
        )
        if comparison_data:
            write_kraken_comparison_log(comparison_data)
    else:
        # Use the standard, long-format summary
        run_results_data = _prepare_run_results_summary(
            str(run_id), strategy_results, problem, simulation_context
        )
        if run_results_data:
            write_run_results(run_results_data)

    # Select best solution (lowest cost among successful strategies)
    best_solution = _select_best_solution(strategy_results)

    final_report = {
        "run_id": str(run_id),
        "total_execution_time_seconds": end_time - start_time,
        "strategies": strategy_results,
        "problem_info": {
            "num_projections": len(processing_order),
            "num_queries": len(simulation_context.query_workload),
            "latency_threshold": context.get("latency_threshold", None),
            "network_size": len(simulation_context.network),
            "detailed_logging_enabled": enable_detailed_logging,
        },
        "best_solution": best_solution,
    }

    return final_report


def _gather_problem_parameters(simulation_context: Any) -> Dict[str, Any]:
    """
    Extract problem parameters from simulation context into clean dictionary format.

    Args:
        simulation_context: The simulation context object.

    Returns:
        Dictionary containing all necessary problem parameters.
    """
    context = {
        # Query and workload
        "query_workload": simulation_context.query_workload,
        "dependencies_per_projection": simulation_context.h_mycombi,
        # Network topology and routing
        "pairwise_distance_matrix": simulation_context.allPairs,
        "all_pairs": simulation_context.allPairs,  # Alias for cost calculator
        "graph": simulation_context.graph,
        "routing_dict": create_routing_dict(simulation_context.graph),
        # Network and event data
        "network_data": simulation_context.h_network_data,
        "event_nodes": simulation_context.h_eventNodes,
        "event_distribution_matrix": simulation_context.h_eventNodes,
        "index_event_nodes": simulation_context.h_IndexEventNodes,
        "global_event_rates": simulation_context.h_rates_data,
        # Projection and selectivity
        "projection_rates_selectivity": simulation_context.h_projrates,
        "pairwise_selectivities": simulation_context.selectivities,
        "filter_by_projection": simulation_context.h_projFilterDict,
        # Node information
        "network_data_nodes": simulation_context.network,
        "primitive_events_per_projection": simulation_context.h_primitive_events,
        "nodes_per_primitive_event": simulation_context.h_nodes,
        # Sink nodes (cloud is typically node 0)
        "sink_nodes": [0],
        # Optimization structures
        "local_rate_lookup": simulation_context.h_local_rate_lookup,
        "sum_of_input_rates_per_query": simulation_context.sum_of_input_rates_per_query,
        # Simulation mode
        "simulation_mode": simulation_context.config.mode,
        # Latency
        "latency_threshold": simulation_context.latency_threshold,
        "latency_weighting_factor": simulation_context.config.xi,
        "cost_weight": getattr(simulation_context.config, "cost_weight", 0.5),
        "latency_weight": 1 - getattr(simulation_context.config, "cost_weight", 0.5),
        # Pre-computed baselines (populated by simulation_environment before kraken runs)
        "prepp_from_cloud_result": getattr(
            simulation_context, "prepp_from_cloud_result", None
        ),
    }

    return context


def _select_strategy(strategy_config: Any):
    """
    Factory function to instantiate the appropriate search strategy.

    Args:
        strategy_config: A dictionary (e.g., {"name": "k_beam", "k": 3})
                         or a legacy enum/string.

    Returns:
        Instance of the corresponding SearchStrategy implementation.

    Raises:
        NotImplementedError: If the strategy is not yet implemented.
        ValueError: If the algorithm enum is not recognized.
    """
    from kraken.search import GreedySearch, BeamSearch, DagStarSearch

    k_value = None
    if isinstance(strategy_config, dict):
        algorithm_name = strategy_config.get("name")
        k_value = strategy_config.get("k")
    else:
        # Fallback for legacy enum/string
        algorithm_name = (
            strategy_config.value
            if hasattr(strategy_config, "value")
            else str(strategy_config)
        )

    if algorithm_name == "greedy":
        return GreedySearch()
    elif algorithm_name == "k_beam":
        # Use k_value from config, or default (from BeamSearch class)
        k_to_use = k_value if k_value is not None else 3
        return BeamSearch(k=int(k_to_use))
    elif algorithm_name == "dag_star":
        use_upper_bound = True
        disable_heuristic = False
        if isinstance(strategy_config, dict):
            use_upper_bound = strategy_config.get("use_upper_bound", True)
            disable_heuristic = strategy_config.get("disable_heuristic", False)
        return DagStarSearch(
            use_upper_bound=use_upper_bound,
            disable_heuristic=disable_heuristic,
        )
    elif algorithm_name == "backtracking":
        raise NotImplementedError("Backtracking search not yet implemented")
    elif algorithm_name == "branch_and_cut":
        raise NotImplementedError("Branch and cut search not yet implemented")
    else:
        raise ValueError(
            f"Unknown placement algorithm: {algorithm_name}. "
            f"Valid options: greedy, k_beam, backtracking, branch_and_cut"
        )


def _calculate_solution_metrics(
    solution: SolutionCandidate,
    problem: PlacementProblem,
    simulation_context: Any,
) -> Dict[str, Any]:
    """
    Calculate comprehensive metrics for a solution.

    Args:
        solution: The solution candidate to analyze.
        problem: The placement problem for context.
        simulation_context: Simulation context for workload information.

    Returns:
        Dictionary containing metrics:
        - total_cost: Total cost across all placements
        - workload_cost: Cost only for workload root queries
        - max_latency: Maximum end-to-end latency
        - cumulative_processing_latency: Total processing latency across all placements
        - num_placements: Number of placement decisions
        - placements_at_cloud: Number of placements at cloud node (0)
        - average_cost_per_placement: Mean cost per placement
    """
    total_cost = solution.cumulative_cost

    # Calculate cost only for workload roots
    workload_set = set(simulation_context.query_workload)
    workload_cost = sum(
        info.individual_cost
        for proj, info in solution.placements.items()
        if proj in workload_set
    )

    # Calculate maximum latency
    max_latency = solution.get_critical_path_latency(problem)

    # Get cumulative processing latency
    cumulative_processing_latency = solution.cumulative_processing_latency

    # Count placements at cloud
    placements_at_cloud = sum(
        1 for info in solution.placements.values() if info.node == 0
    )

    # Calculate average cost
    num_placements = len(solution.placements)
    avg_cost = total_cost / num_placements if num_placements > 0 else 0.0

    return {
        "total_cost": total_cost,
        "workload_cost": workload_cost,
        "max_latency": max_latency,
        "cumulative_processing_latency": cumulative_processing_latency,
        "num_placements": num_placements,
        "placements_at_cloud": placements_at_cloud,
        "average_cost_per_placement": avg_cost,
    }


def _select_best_solution(strategy_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Select the best solution from all successful strategy executions.

    The best solution is defined as the one with the lowest workload cost.

    Args:
        strategy_results: Dictionary of results from each strategy.

    Returns:
        Dictionary containing the best solution with keys:
        - strategy_name: Name of the winning strategy
        - solution: The SolutionCandidate object
        - metrics: The calculated metrics
        Or None if no successful solutions exist.
    """
    successful_results = [
        (name, result)
        for name, result in strategy_results.items()
        if result["status"] == "success"
    ]

    if not successful_results:
        return None

    # Find solution with minimum workload cost
    best_name, best_result = min(
        successful_results, key=lambda x: x[1]["metrics"]["workload_cost"]
    )

    return {
        "strategy_name": best_name,
        "solution": best_result["solution"],
        "metrics": best_result["metrics"],
    }


def _enrich_log_with_solution(
    detailed_log: List[Dict[str, Any]],
    solution: SolutionCandidate,
    run_id: str,
    strategy_name: str,
    problem: Any,
) -> List[Dict[str, Any]]:
    """
    Enrich log entries with solution context and metadata.

    Marks which placement decisions were part of the final solution path
    and adds run identification metadata and problem context.

    Args:
        detailed_log: Raw log entries from problem expansion.
        solution: The final solution candidate.
        run_id: Unique identifier for this run.
        strategy_name: Name of the strategy that generated this solution.
        problem: PlacementProblem instance for accessing workload/processing_order.

    Returns:
        List of enriched log entry dictionaries ready for CSV export.
    """
    # Create a set of (projection, node, strategy) tuples from final solution
    solution_set = {
        (info.projection, info.node, info.strategy)
        for info in solution.placements.values()
    }

    # Format workload and processing_order once for all entries
    workload_str = ";".join(str(q) for q in problem.query_workload)
    processing_order_str = ";".join(str(p) for p in problem.processing_order)

    enriched_log = []
    for entry in detailed_log:
        # Check if this decision was part of the final solution
        decision_tuple = (
            entry["projection"],
            entry["candidate_node"],
            entry["communication_strategy"],
        )
        entry["is_part_of_final_solution"] = decision_tuple in solution_set

        # Add run metadata (same for all entries in this run)
        entry["run_id"] = run_id
        entry["strategy_name"] = strategy_name
        entry["workload"] = workload_str
        entry["processing_order"] = processing_order_str

        enriched_log.append(entry)

    return enriched_log


def _get_strategy_prefix(strategy_name: str, result: Dict[str, Any]) -> str:
    """Generate a Parquet-friendly column prefix for a strategy.

    Args:
        strategy_name: The name of the strategy (e.g., "greedy", "k_beam_k=3").
        result: The result dictionary containing k_value if applicable.

    Returns:
        A column prefix string (e.g., "kraken_greedy", "kraken_k_3_beam").
    """
    name = strategy_name.lower()
    if name == "greedy":
        return "kraken_greedy"
    elif name.startswith("k_beam"):
        k_value = result.get("k_value")
        if k_value is not None:
            # Replaces 'k_beam_k=3' with 'kraken_k_3_beam'
            return f"kraken_k_{k_value}_beam"
        else:
            return "kraken_k_beam_unknown"
    elif name == "dag_star_b":
        return "kraken_dag_star_b"
    elif name == "dag_star":
        return "kraken_dag_star"
    elif name == "dag_star_h0_b":
        return "kraken_dag_star_h0_b"
    elif name == "dag_star_h0":
        return "kraken_dag_star_h0"
    # Fallback for other strategies
    return f"kraken_{name.replace('=', '_').replace('-', '_')}"


def _prepare_kraken_comparison_summary(
    run_id: str,
    strategy_results: Dict[str, Any],
    problem: PlacementProblem,
    simulation_context: Any,
) -> List[Dict[str, Any]]:
    """
    Prepare a single-row, wide-format summary for Kraken strategy comparison.

    Args:
        run_id: Unique identifier for this run.
        strategy_results: Dictionary of results from each strategy execution.
        problem: PlacementProblem instance for workload information.
        simulation_context: Simulation context for configuration information.

    Returns:
        List containing a single dictionary with all comparison metrics.
    """
    if not strategy_results:
        return []

    # Start with common run information
    comparison_row = {
        "run_id": run_id,
        "workload": ";".join(str(q) for q in problem.query_workload),
    }

    # Add config data (same as in _prepare_run_results_summary)
    config = simulation_context.config
    cost_weight = getattr(config, "cost_weight", 0.5)
    cost_weight = max(0.0, min(cost_weight, 1.0))
    latency_weight = 1.0 - cost_weight

    comparison_row.update(
        {
            "network_size": config.network_size,
            "event_skew": config.event_skew,
            "node_event_ratio": config.node_event_ratio,
            "max_parents": config.max_parents,
            "parent_factor": config.parent_factor,
            "num_event_types": config.num_event_types,
            "query_size": config.query_size,
            "query_length": config.query_length,
            "xi": config.xi,
            "latency_threshold": config.latency_threshold,
            "cost_weight": cost_weight,
            "latency_weight": latency_weight,
            "mode": config.mode.value
            if hasattr(config.mode, "value")
            else str(config.mode),
            "algorithm": config.algorithm.value
            if hasattr(config.algorithm, "value")
            else str(config.algorithm),
            "graph_density": getattr(simulation_context, "graph_density", None),
            "average_selectivity": getattr(
                simulation_context, "average_selectivity", None
            ),
        }
    )

    # Fold in non-Kraken baselines so this dataset is fully self-contained
    # (cost-ratio analysis vs. all-push, comparison against PrePP-from-cloud,
    # etc. without needing a second join against the unified results dataset).
    for prefix, attr in [
        ("all_push", "all_push_results"),
        ("prepp", "prepp_from_cloud_result"),
        ("inev", "inev_results"),
        ("sequential", "sequential_results"),
    ]:
        baseline = getattr(simulation_context, attr, None)
        if isinstance(baseline, dict):
            for src, dst in [
                ("status", "status"),
                ("cost", "cost"),
                ("transmission_latency", "transmission_latency"),
                ("processing_latency", "processing_latency"),
                ("computing_time", "computing_time"),
            ]:
                comparison_row[f"{prefix}_{dst}"] = baseline.get(src)
        else:
            for dst in [
                "status",
                "cost",
                "transmission_latency",
                "processing_latency",
                "computing_time",
            ]:
                comparison_row[f"{prefix}_{dst}"] = None

    # Iterate over each strategy and add its metrics with a unique prefix
    for strategy_name, result in strategy_results.items():
        prefix = _get_strategy_prefix(strategy_name, result)

        # Add general metrics
        comparison_row[f"{prefix}_status"] = result["status"]
        comparison_row[f"{prefix}_computing_time"] = result["execution_time_seconds"]

        if result["status"] == "success":
            metrics = result["metrics"]
            comparison_row[f"{prefix}_cost"] = metrics["total_cost"]
            comparison_row[f"{prefix}_workload_cost"] = metrics["workload_cost"]
            comparison_row[f"{prefix}_transmission_latency"] = metrics["max_latency"]
            comparison_row[f"{prefix}_processing_latency"] = metrics[
                "cumulative_processing_latency"
            ]
            comparison_row[f"{prefix}_num_placements"] = metrics["num_placements"]
            comparison_row[f"{prefix}_placements_at_cloud"] = metrics[
                "placements_at_cloud"
            ]
            comparison_row[f"{prefix}_average_cost_per_placement"] = metrics[
                "average_cost_per_placement"
            ]
        else:
            # Fill failed strategy metrics with None
            comparison_row[f"{prefix}_cost"] = None
            comparison_row[f"{prefix}_workload_cost"] = None
            comparison_row[f"{prefix}_transmission_latency"] = None
            comparison_row[f"{prefix}_processing_latency"] = None
            comparison_row[f"{prefix}_num_placements"] = None
            comparison_row[f"{prefix}_placements_at_cloud"] = None
            comparison_row[f"{prefix}_average_cost_per_placement"] = None

    return [comparison_row]


def _prepare_run_results_summary(
    run_id: str,
    strategy_results: Dict[str, Any],
    problem: PlacementProblem,
    simulation_context: Any,
) -> List[Dict[str, Any]]:
    """
    Prepare summary data for run results from strategy executions.

    Extracts key metrics from each strategy execution and formats them
    for storage in the run_results Parquet dataset.

    Args:
        run_id: Unique identifier for this run.
        strategy_results: Dictionary of results from each strategy execution.
        problem: PlacementProblem instance for workload information.
        simulation_context: Simulation context for configuration information.

    Returns:
        List of dictionaries containing run result summaries.
    """
    workload_str = ";".join(str(q) for q in problem.query_workload)
    results_data = []

    # Extract config information once for all results
    config = simulation_context.config
    cost_weight = getattr(config, "cost_weight", 0.5)
    cost_weight = max(0.0, min(cost_weight, 1.0))
    latency_weight = 1.0 - cost_weight

    config_data = {
        "network_size": config.network_size,
        "event_skew": config.event_skew,
        "node_event_ratio": config.node_event_ratio,
        "max_parents": config.max_parents,
        "parent_factor": config.parent_factor,
        "num_event_types": config.num_event_types,
        "query_size": config.query_size,
        "query_length": config.query_length,
        "xi": config.xi,
        "latency_threshold": config.latency_threshold,
        "cost_weight": cost_weight,
        "latency_weight": latency_weight,
        "mode": config.mode.value
        if hasattr(config.mode, "value")
        else str(config.mode),
        "algorithm": config.algorithm.value
        if hasattr(config.algorithm, "value")
        else str(config.algorithm),
        "graph_density": getattr(simulation_context, "graph_density", None),
    }

    for strategy_name, result in strategy_results.items():
        result_entry = {
            "run_id": run_id,
            "strategy_name": strategy_name,
            "workload": workload_str,
            "status": result["status"],
            "execution_time_seconds": result["execution_time_seconds"],
            "beam_width_k": result.get("k_value", None),
        }

        if result["status"] == "success":
            metrics = result["metrics"]
            result_entry.update(
                {
                    "total_cost": metrics["total_cost"],
                    "workload_cost": metrics["workload_cost"],
                    "average_cost_per_placement": metrics["average_cost_per_placement"],
                    "max_latency": metrics["max_latency"],
                    "cumulative_processing_latency": metrics[
                        "cumulative_processing_latency"
                    ],
                    "num_placements": metrics["num_placements"],
                    "placements_at_cloud": metrics["placements_at_cloud"],
                }
            )
        else:
            # Fill with None for failed strategies
            result_entry.update(
                {
                    "total_cost": None,
                    "workload_cost": None,
                    "average_cost_per_placement": None,
                    "max_latency": None,
                    "cumulative_processing_latency": None,
                    "num_placements": None,
                    "placements_at_cloud": None,
                }
            )

        # Add config data to each result entry
        result_entry.update(config_data)

        results_data.append(result_entry)

    return results_data
