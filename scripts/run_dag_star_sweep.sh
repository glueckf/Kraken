#!/usr/bin/env bash
# Run the DAG* sweep on the current host. Designed to drop straight onto a
# cluster after an rsync of the repo.
#
# Usage:
#   ./scripts/run_dag_star_sweep.sh                    # prod sweep, full
#   PROFILE=dev ./scripts/run_dag_star_sweep.sh        # dev sweep, single n=50
#   RUNS=100 ./scripts/run_dag_star_sweep.sh           # prod with 100 runs
#   NETWORK_SIZES=200,500 ./scripts/run_dag_star_sweep.sh   # subset of sizes
#   MAX_WORKERS=64 ./scripts/run_dag_star_sweep.sh     # override worker count
#   DATASET_NAME=my_sweep ./scripts/run_dag_star_sweep.sh   # custom output
#
# What this writes:
#   src/result/<DATASET_NAME>.parquet/       per-run unified rows
#   src/result/kraken_comparison.parquet/    wide-format rows w/ baselines
#                                            (the file to analyse downstream)
#
# Tip: clear stale output before a fresh sweep so you don't merge with prior runs:
#   rm -rf src/result/kraken_comparison.parquet src/result/dag_star_sweep.parquet

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}/src"

export KRAKEN_PROFILE="${PROFILE:-prod}"
[[ -n "${RUNS:-}" ]]          && export KRAKEN_RUNS="${RUNS}"
[[ -n "${NETWORK_SIZES:-}" ]] && export KRAKEN_NETWORK_SIZES="${NETWORK_SIZES}"
[[ -n "${MAX_WORKERS:-}" ]]   && export KRAKEN_MAX_WORKERS="${MAX_WORKERS}"
[[ -n "${DATASET_NAME:-}" ]]  && export KRAKEN_DATASET_NAME="${DATASET_NAME}"

echo "[sweep] starting at $(date)"
echo "[sweep] profile=${KRAKEN_PROFILE}"
echo "[sweep] runs=${KRAKEN_RUNS:-<profile default>}"
echo "[sweep] network_sizes=${KRAKEN_NETWORK_SIZES:-<profile default>}"
echo "[sweep] max_workers=${KRAKEN_MAX_WORKERS:-<profile default>}"
echo "[sweep] dataset_name=${KRAKEN_DATASET_NAME:-dag_star_sweep}"
echo

python start_simulation.py 2>&1 | tee "../sweep_$(date +%Y%m%d_%H%M%S).log"

echo "[sweep] done at $(date)"
