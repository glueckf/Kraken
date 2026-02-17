"""
Results Logger for Detailed Placement Decision Tracking

This module handles Parquet file operations for logging placement decisions
and run results. It provides high-performance, scalable storage for algorithm
analysis and debugging using the Apache Parquet columnar format.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Header Definitions (maintain exact column names for compatibility)
DETAILED_LOG_HEADER = [
    # Run metadata
    "run_id",
    "strategy_name",
    "workload",
    "processing_order",
    # Placement identifiers
    "projection_index",
    "projection",
    "candidate_node",
    # Decision
    "communication_strategy",
    "is_pruned",
    "is_part_of_final_solution",
    # Individual cost and latency
    "individual_cost",
    "individual_transmission_latency",
    "individual_processing_latency",
    # Cumulative metrics before this placement
    "cumulative_cost_before",
    "cumulative_processing_latency_before",
    # Cumulative metrics after this placement
    "cumulative_cost_after",
    "cumulative_processing_latency_after",
    # Overall latency
    "max_latency_so_far",
]

RUN_RESULTS_HEADER = [
    # Run metadata
    "run_id",
    "strategy_name",
    "workload",
    "status",
    "execution_time_seconds",
    # Cost metrics
    "total_cost",
    "workload_cost",
    "average_cost_per_placement",
    # Latency metrics
    "max_latency",
    "cumulative_processing_latency",
    # Placement metrics
    "num_placements",
    "placements_at_cloud",
    # Strategy parameters
    "beam_width_k",
    # Configuration parameters
    "network_size",
    "event_skew",
    "node_event_ratio",
    "max_parents",
    "parent_factor",
    "num_event_types",
    "query_size",
    "query_length",
    "xi",
    "latency_threshold",
    "mode",
    "algorithm",
    "graph_density",
]

OUTPUT_DIRECTORY = "result"
RUN_RESULTS_DIR = "run_results.parquet"
DETAILED_LOG_DIR = "detailed_run_log.parquet"
KRAKEN_COMPARISON_DIR = "kraken_comparison.parquet"

logger = logging.getLogger(__name__)


def initialize_logging() -> None:
    """
    Ensure base directories for Parquet datasets exist.

    Creates the output directory structure for both run results
    and detailed logs if they don't already exist. This function
    should be called once at application startup.

    Raises:
        OSError: If directory creation fails.
    """
    base_path = Path(OUTPUT_DIRECTORY)
    (base_path / RUN_RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    (base_path / DETAILED_LOG_DIR).mkdir(parents=True, exist_ok=True)
    (base_path / KRAKEN_COMPARISON_DIR).mkdir(parents=True, exist_ok=True)


def write_detailed_log(run_id: str, detailed_log_data: List[Dict[str, Any]]) -> None:
    """
    Write detailed log entries for a single run to a dedicated Parquet file.

    Each run gets its own Parquet file named by run_id for easy identification
    and efficient querying.

    Args:
        run_id: Unique identifier for this solver run.
        detailed_log_data: List of log entry dictionaries containing
            the fields defined in DETAILED_LOG_HEADER.

    Raises:
        OSError: If file writing fails.
        ValueError: If log entries are missing required fields.
        RuntimeError: If the written Parquet file fails validation.
    """
    if not detailed_log_data:
        return

    df = pd.DataFrame(detailed_log_data)
    df = df[DETAILED_LOG_HEADER]

    # Convert projection objects to strings for Parquet compatibility
    df["projection"] = df["projection"].astype(str)

    file_path = Path(OUTPUT_DIRECTORY) / DETAILED_LOG_DIR / f"{run_id}.parquet"

    df.to_parquet(file_path, engine="pyarrow", compression="snappy", index=False)
    _validate_written_files([file_path])


def write_run_results(results_data: List[Dict[str, Any]]) -> None:
    """
    Append one or more run results to the run_results Parquet dataset.

    Results are written as a new Parquet file in the dataset directory,
    enabling efficient append operations without rewriting existing data.

    Args:
        results_data: List of result dictionaries containing the fields
            defined in RUN_RESULTS_HEADER.

    Raises:
        OSError: If file writing fails.
        ValueError: If result entries are missing required fields.
        RuntimeError: If a written dataset fragment fails validation.
    """
    if not results_data:
        return

    df = pd.DataFrame(results_data)
    df = df[RUN_RESULTS_HEADER]

    numeric_columns = [
        "total_cost",
        "workload_cost",
        "average_cost_per_placement",
        "max_latency",
        "cumulative_processing_latency",
        "num_placements",
        "placements_at_cloud",
        "beam_width_k",
        "network_size",
        "event_skew",
        "node_event_ratio",
        "max_parents",
        "parent_factor",
        "num_event_types",
        "query_size",
        "query_length",
        "xi",
        "latency_threshold",
        "graph_density",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    table = pa.Table.from_pandas(df, preserve_index=False)

    output_dir = Path(OUTPUT_DIRECTORY) / RUN_RESULTS_DIR

    _write_dataset_with_validation(table, output_dir)


def write_kraken_comparison_log(results_data: List[Dict[str, Any]]) -> None:
    """
    Write a single-row, wide-format comparison of Kraken strategies.

    This log does not use a fixed header, as columns are generated
    dynamically based on the strategies being compared.

    Args:
        results_data: List containing a single dictionary with the
            wide-format comparison row.

    Raises:
        OSError: If file writing fails.
        ValueError: If result entries are missing required fields.
        RuntimeError: If a written dataset fragment fails validation.
    """
    if not results_data:
        return

    # Convert the single-row dictionary into a DataFrame
    df = pd.DataFrame(results_data)

    # Ensure run_id and workload are strings
    if "run_id" in df.columns:
        df["run_id"] = df["run_id"].astype(str)
    if "workload" in df.columns:
        df["workload"] = df["workload"].astype(str)

    table = pa.Table.from_pandas(df, preserve_index=False)

    output_dir = Path(OUTPUT_DIRECTORY) / KRAKEN_COMPARISON_DIR

    _write_dataset_with_validation(table, output_dir)


def _write_dataset_with_validation(table: pa.Table, output_dir: Path) -> None:
    """
    Write a pyarrow table to a Parquet dataset and validate the new fragments.

    Validation ensures freshly written files can be read back immediately, catching
    partial writes or corruption while the producing process is still running.

    Raises:
        RuntimeError: If validation of the written fragments fails.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_files = {file.name for file in output_dir.glob("*.parquet")}

    pq.write_to_dataset(table, root_path=str(output_dir))

    new_files = [
        file for file in output_dir.glob("*.parquet") if file.name not in existing_files
    ]

    # Fallback: if the dataset writer reused an existing filename, validate the most recent file
    if not new_files and existing_files:
        candidates = sorted(
            output_dir.glob("*.parquet"), key=lambda f: f.stat().st_mtime, reverse=True
        )
        new_files = candidates[:1]

    _validate_written_files(new_files)


def _validate_written_files(files: List[Path]) -> None:
    """Attempt to read back written parquet files to detect corruption early."""
    for file_path in files:
        try:
            pq.read_table(file_path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Parquet validation failed for %s", file_path, exc_info=exc)
            raise RuntimeError(f"Parquet validation failed for {file_path}") from exc
