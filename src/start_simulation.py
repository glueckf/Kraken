import itertools
import math
import os
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import time
import logging
import threading

from simulation_environment import SimulationConfig, SimulationMode

logger = logging.getLogger(__name__)


def _safe_float_convert(value: Any) -> float:
    """Safely convert value to float, handling numpy types and their string representations."""
    if value is None:
        return 0.0

    # If it's already a number, convert directly
    if isinstance(value, (int, float)):
        return float(value)

    # If it's a numpy type, get the item value
    if hasattr(value, "item"):
        return float(value.item())

    # If it's a string representation of numpy type like "np.int64(647)"
    if isinstance(value, str) and "np." in value:
        import re

        match = re.search(r"\(([^)]+)\)", value)
        if match:
            return float(match.group(1))

    # Last resort: direct conversion
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.warning(
            f"Could not convert {value} (type: {type(value)}) to float, returning 0.0"
        )
        return 0.0


# Global worker state for persistent initialization
_worker_state = {}
_worker_lock = threading.Lock()


def _setup_worker_path(parent_dir: str = None) -> None:
    """Set up sys.path for worker processes BEFORE any unpickling."""
    import sys

    if parent_dir is None:
        # Fallback: compute from __file__ if available
        script_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(script_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        print(f"[WORKER_PATH_SETUP] Added {parent_dir} to sys.path", flush=True)


def _initialize_worker() -> None:
    """
    Initialize worker process with expensive one-time setup.
    This runs once per worker process and caches expensive operations.
    """
    global _worker_state

    # Ensure sys.path is set up (should already be done by initializer, but double-check)
    _setup_worker_path()

    with _worker_lock:
        if "initialized" not in _worker_state:
            logger.info("[WORKER_INIT] Initializing worker process")

            # Pre-import heavy modules to avoid repeated imports
            try:
                import networkx as nx
                import numpy as np
                from simulation_environment import Simulation, calculate_graph_density

                _worker_state.update(
                    {
                        "initialized": True,
                        "networkx": nx,
                        "numpy": np,
                        "Simulation": Simulation,
                        "calculate_graph_density": calculate_graph_density,
                        "job_count": 0,
                    }
                )

                logger.info("[WORKER_INIT] Worker initialization completed")
            except ImportError as e:
                logger.error(f"[WORKER_INIT] Failed to import modules: {e}")
                raise


@dataclass
class SimulationJob:
    """Represents a single simulation job with all necessary data."""

    job_id: int
    config: SimulationConfig
    parameter_set_id: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize job for multiprocessing."""
        return {
            "job_id": self.job_id,
            "config": self.config,
            "parameter_set_id": self.parameter_set_id,
        }


def run_simulation_worker(job_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Worker function for parallel simulation execution.
    Executes a single simulation job and returns the complete results.

    Args:
        job_data: Dictionary containing serialized job data

    Returns:
        Dictionary with job results and status
    """
    global _worker_state

    # Initialize worker on first use
    _initialize_worker()

    try:
        job_id = job_data["job_id"]
        config = job_data["config"]
        parameter_set_id = job_data["parameter_set_id"]

        # Use cached modules from worker state
        Simulation_class = _worker_state["Simulation"]
        calculate_graph_density = _worker_state["calculate_graph_density"]

        # Execute simulation using cached class
        simulation = Simulation_class(config)

        # Run all placement strategies sequentially
        simulation.run()

        # Calculate graph density using cached function
        graph_density = calculate_graph_density(simulation.graph)

        # Return complete result data
        return {
            "job_id": job_id,
            "sequential_results": simulation.results,
            "integrated_results": simulation.kraken_results,
            "config": config,
            "graph_density": graph_density,
            "sequential_object": simulation,
            "success": True,
            "error_msg": None,
            "parameter_set_id": parameter_set_id,
        }

    except Exception as e:
        import traceback

        error_traceback = traceback.format_exc()
        error_message = f"Exception in job {job_data.get('job_id', 'unknown')}: {str(e)}\n{error_traceback}"
        logger.error(f"[WORKER_ERROR] {error_message}")

        return {
            "job_id": job_data.get("job_id", -1),
            "sequential_results": None,
            "integrated_results": None,
            "config": job_data.get("config"),
            "graph_density": None,
            "sequential_object": None,
            "success": False,
            "error_msg": error_message,
            "parameter_set_id": job_data.get("parameter_set_id", "unknown"),
        }


class ParallelSimulationExecutor:
    """
    Streamlined parallel simulation executor with direct job execution.

    Key features:
    - No batching overhead - one job per task
    - Direct parallel execution with ProcessPoolExecutor
    - Immediate result processing with as_completed
    - Minimal memory footprint and complexity
    """

    def __init__(
        self,
        enable_parallel: bool = True,
        max_workers: Optional[int] = None,
    ):
        self.enable_parallel = enable_parallel

        # Set worker count
        if max_workers is None:
            if enable_parallel:
                self.max_workers = multiprocessing.cpu_count()
            else:
                self.max_workers = 1
        else:
            self.max_workers = max_workers

        # Force single worker for sequential mode
        if not enable_parallel:
            self.max_workers = 1

        self.successful_jobs = 0
        self.failed_jobs = 0
        self.start_time = None

    def run_simulations(self, jobs: List[SimulationJob]) -> None:
        """
        Execute all simulation jobs using direct parallel execution.

        Args:
            jobs: List of SimulationJob objects to execute
        """
        total_jobs = len(jobs)
        logger.info(
            f"[SIMULATION] Starting {total_jobs} jobs with {self.max_workers} workers"
        )
        logger.info(
            f"[SIMULATION] Parallel: {'Enabled' if self.enable_parallel else 'Disabled'}"
        )

        self.start_time = time.time()

        if self.enable_parallel and self.max_workers > 1:
            self._run_parallel(jobs)
        else:
            self._run_sequential(jobs)

        # Print final statistics
        total_time = time.time() - self.start_time
        avg_time_per_job = total_time / total_jobs if total_jobs > 0 else 0

        logger.info(
            f"\n[RESULTS] All {total_jobs} jobs completed in {total_time:.1f}s "
            f"(avg: {avg_time_per_job:.1f}s per job)"
        )
        logger.info(
            f"[RESULTS] Successful: {self.successful_jobs}, Failed: {self.failed_jobs}"
        )

        if self.failed_jobs > 0:
            logger.warning(f"[RESULTS] Warning: {self.failed_jobs} job(s) failed")

    def _run_parallel(self, jobs: List[SimulationJob]) -> None:
        """
        Execute jobs in parallel with direct task submission.
        """
        # Ensure main process has correct path for unpickling
        import sys

        script_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(script_dir)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
            logger.info(f"[MAIN_PROCESS] Added {parent_dir} to sys.path")

        total_jobs = len(jobs)

        with ProcessPoolExecutor(
            max_workers=self.max_workers,
            initializer=_setup_worker_path,
            initargs=(parent_dir,),
        ) as executor:
            # Submit individual jobs (no batching)
            future_to_job = {
                executor.submit(run_simulation_worker, job.to_dict()): job
                for job in jobs
            }

            # Process results as they complete
            for future in as_completed(future_to_job):
                job = future_to_job[future]
                try:
                    result = future.result()
                    self._process_completed_job(result)

                    # Progress reporting
                    completed_jobs = self.successful_jobs + self.failed_jobs
                    if completed_jobs % 50 == 0:
                        elapsed = time.time() - self.start_time
                        logger.info(
                            f"[PROGRESS] {completed_jobs}/{total_jobs} jobs completed "
                            f"- {elapsed:.1f}s elapsed"
                        )

                except Exception as e:
                    import traceback

                    error_trace = traceback.format_exc()
                    logger.error(f"[ERROR] Job {job.job_id} execution failed: {str(e)}")
                    logger.error(f"[ERROR] Traceback:\n{error_trace}")
                    self.failed_jobs += 1

    def _run_sequential(self, jobs: List[SimulationJob]) -> None:
        """
        Execute jobs sequentially for debugging.
        """
        for i, job in enumerate(jobs):
            try:
                logger.info(
                    f"[SEQUENTIAL] Processing job {i + 1}/{len(jobs)} ({job.parameter_set_id})"
                )
                result = run_simulation_worker(job.to_dict())
                self._process_completed_job(result)

            except Exception as e:
                logger.error(f"[ERROR] Job {job.job_id} failed: {str(e)}")
                self.failed_jobs += 1

    def _process_completed_job(self, result: Dict[str, Any]) -> None:
        """
        Process a completed job result.
        Note: Results are written to parquet by the Simulation.run() method.
        """
        if result["success"]:
            # Results are already written to parquet by Simulation._write_results()
            self.successful_jobs += 1
        else:
            logger.error(
                f"[ERROR] Job {result['job_id']} ({result['parameter_set_id']}) "
                f"failed: {result['error_msg']}"
            )
            self.failed_jobs += 1


def run_single_simulation(
    network_size: int = 12,
    node_event_ratio: float = 0.5,
    num_event_types: int = 6,
    event_skew: float = 0.3,
    max_parents: int = 1,
    workload_size: int = 3,
    query_length: int = 5,
    num_runs: int = 50,
    mode: SimulationMode = SimulationMode.RANDOM,
    enable_parallel: bool = True,
    xi: float = 0.0,
    latency_threshold: float = None,
    max_workers: Optional[int] = None,
) -> None:
    """
    Run a single simulation configuration multiple times.

    This function creates jobs for the same configuration and executes them
    with the parallel simulation executor.

    Args:
        network_size: Number of nodes in the network topology
        node_event_ratio: Ratio of nodes that generate events
        num_event_types: Number of different event types
        event_skew: Skewness parameter for event distribution
        max_parents: Maximum number of parent nodes per node
        workload_size: Number of queries in the workload
        query_length: Average length of each query
        num_runs: Number of simulation runs to execute
        mode: Simulation mode determining what components are fixed/random
        enable_parallel: Whether to enable parallel processing
        xi: Xi value for processing latency weight (default 0.0)
        latency_threshold: Threshold for latency calculation
        max_workers: Maximum number of parallel workers (auto-detected if None)
    """
    # Calculate parent_factor from max_parents for consistency with parameter study
    import math

    parent_factor = (
        max_parents / math.ceil(math.log2(network_size)) if network_size > 1 else 1.0
    )

    logger.info(
        f"[SINGLE] Starting single simulation configuration with {num_runs} runs"
    )
    logger.info(
        f"[CONFIG] Network size: {network_size}, Workload: {workload_size}, Query length: {query_length}"
    )
    logger.info(
        f"[CONFIG] Mode: {mode.value}, Max parents: {max_parents}, Parent factor: {parent_factor:.2f}"
    )

    # Force single worker for debugging when parallel is disabled
    if not enable_parallel:
        max_workers = 1

    # Create simulation configuration
    config = SimulationConfig(
        network_size=network_size,
        node_event_ratio=node_event_ratio,
        num_event_types=num_event_types,
        event_skew=event_skew,
        max_parents=max_parents,
        parent_factor=parent_factor,
        query_size=workload_size,
        query_length=query_length,
        mode=mode,
        xi=xi,
        latency_threshold=latency_threshold,
    )

    # Generate jobs for the same configuration
    parameter_set_id = (
        f"single_n{network_size}_w{workload_size}_q{query_length}_p{max_parents}"
    )
    jobs = []

    for run_id in range(num_runs):
        job = SimulationJob(
            job_id=run_id,
            config=config,
            parameter_set_id=f"{parameter_set_id}_run{run_id + 1}",
        )
        jobs.append(job)

    # Execute with parallel executor
    executor = ParallelSimulationExecutor(
        enable_parallel=enable_parallel,
        max_workers=max_workers,
    )

    executor.run_simulations(jobs)
    logger.info(f"[SINGLE] Completed {len(jobs)} runs for single configuration")


def run_parameter_study(
    network_sizes: List[int] = [12],
    workload_sizes: List[int] = [5],
    parent_factors: List[float] = [1.8],
    query_lengths: List[int] = [5],
    runs_per_combination: int = 5,
    node_event_ratios: List[float] = [0.5],
    num_event_types: List[int] = [6],
    event_skews: List[float] = [2.0],
    xi: float = 0,
    latency_threshold: float = None,
    cost_weight: float = 0.5,
    mode: SimulationMode = SimulationMode.FULLY_DETERMINISTIC,
    enable_parallel: bool = False,
    max_workers: int = 1,
    run_latency_tradeoff_study: bool = False,
    output_dataset_name: Optional[str] = None,
) -> None:
    """
    Run a full parameter study, sorted by a complexity score.

    This function generates all parameter combinations, sorts them by a calculated
    score to run simpler experiments first, and then executes them.
    """
    logger.info(
        "[PARAMETER_STUDY] Starting full parameter study (sorted by complexity score)"
    )
    logger.info(f"[PARAMETER_STUDY] Network sizes: {network_sizes}")
    logger.info(f"[PARAMETER_STUDY] Workload sizes: {workload_sizes}")
    logger.info(f"[PARAMETER_STUDY] Parent factors: {parent_factors}")
    logger.info(f"[PARAMETER_STUDY] Query lengths: {query_lengths}")
    logger.info(f"[PARAMETER_STUDY] Runs per combination: {runs_per_combination}")

    # --- START: Modified Logic ---

    # 1. Generate combinations for the parameters included in the score
    scored_param_combinations = list(
        itertools.product(network_sizes, workload_sizes, query_lengths, num_event_types)
    )

    # 2. Calculate the score for each combination and store it
    scored_combinations_with_score = []
    for combo in scored_param_combinations:
        network_size, workload_size, query_length, num_event_type = combo
        # Your scoring formula
        score = math.log10(network_size) + workload_size + query_length + num_event_type
        scored_combinations_with_score.append((score, combo))

    # 3. Sort the combinations based on the score (ascending)
    scored_combinations_with_score.sort(key=lambda x: x[0])

    logger.info(
        f"Generated and sorted {len(scored_combinations_with_score)} parameter sets by complexity score."
    )

    # 4. Generate ALL jobs upfront based on the sorted order
    jobs = []
    job_id = 0

    # Iterate through the newly sorted combinations first
    for score, main_params in scored_combinations_with_score:
        network_size, workload_size, query_length, num_event_type = main_params

        # Now, iterate through the remaining parameters that were not part of the score
        for parent_factor in parent_factors:
            for node_event_ratio in node_event_ratios:
                for event_skew in event_skews:
                    # Calculate max_parents using same formula as original
                    max_parents = int(
                        parent_factor * math.ceil(math.log2(network_size))
                    )

                    # Create parameter set identifier
                    parameter_set_id = f"n{network_size}_w{workload_size}_q{query_length}_pf{parent_factor}_p{max_parents}_ner{node_event_ratio}_net{num_event_type}_es{event_skew}"

                    # Create configuration for this parameter combination
                    config = SimulationConfig(
                        network_size=network_size,
                        node_event_ratio=node_event_ratio,
                        num_event_types=num_event_type,
                        event_skew=event_skew,
                        max_parents=max_parents,
                        parent_factor=parent_factor,
                        query_size=workload_size,
                        query_length=query_length,
                        xi=xi,
                        mode=mode,
                        latency_threshold=latency_threshold,
                        cost_weight=cost_weight,
                        run_latency_tradeoff_study=run_latency_tradeoff_study,
                        output_dataset_name=output_dataset_name,
                    )

                    # Generate multiple runs for this combination
                    for run_num in range(runs_per_combination):
                        job = SimulationJob(
                            job_id=job_id,
                            config=config,
                            parameter_set_id=f"{parameter_set_id}_run{run_num + 1}",
                        )
                        jobs.append(job)
                        job_id += 1

    # --- END: Modified Logic ---

    total_jobs = len(jobs)
    expected_jobs = (
        len(network_sizes)
        * len(workload_sizes)
        * len(parent_factors)
        * len(query_lengths)
        * len(node_event_ratios)
        * len(num_event_types)
        * len(event_skews)
        * runs_per_combination
    )

    logger.info(
        f"[PARAMETER_STUDY] Generated {total_jobs} jobs (expected: {expected_jobs})"
    )
    assert total_jobs == expected_jobs, (
        f"Job count mismatch: generated {total_jobs}, expected {expected_jobs}"
    )

    # Execute all jobs with parallel executor
    executor = ParallelSimulationExecutor(
        enable_parallel=enable_parallel,
        max_workers=max_workers,
    )

    executor.run_simulations(jobs)
    logger.info(
        f"[PARAMETER_STUDY] Completed all {total_jobs} jobs across all parameter combinations"
    )


def main() -> None:
    """
    Main entry point for the DAG* validation experiment.

    Compares five Kraken strategies head-to-head on identical inputs:
      - greedy
      - k-beam (k=3, k=5)
      - DAG**b  (DAG* with PrePP-from-cloud upper-bound pruning)
      - DAG**   (DAG* with no upper-bound pruning)

    Starts at network size 50 (one level below the production 100) to keep
    iteration time manageable while we validate correctness.
    """
    # --- 1. Define Experiment Parameters ---
    runs = 50

    run_parameter_study(
        network_sizes=[50],
        workload_sizes=[5],
        parent_factors=[1.8],
        query_lengths=[3],
        runs_per_combination=runs,
        node_event_ratios=[0.4],
        num_event_types=[6],
        event_skews=[1.5],
        mode=SimulationMode.RANDOM,
        enable_parallel=True,
        max_workers=14,
        xi=0,
        cost_weight=1,
        output_dataset_name="dag_star_validation_n50_cached",
    )

if __name__ == "__main__":
    # Configure logging for server runs
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    main()
