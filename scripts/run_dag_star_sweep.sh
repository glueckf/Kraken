#!/usr/bin/env bash
# Run the DAG* sweep on the current host. Designed to drop straight onto a
# cluster after an rsync of the repo.
#
# Usage:
#   ./scripts/run_dag_star_sweep.sh                    # prod sweep, full
#   PROFILE=dev ./scripts/run_dag_star_sweep.sh        # dev sweep, single n=50
#   RUNS=100 ./scripts/run_dag_star_sweep.sh           # prod with 100 runs
#   NETWORK_SIZES=200,500 ./scripts/run_dag_star_sweep.sh
#   MAX_WORKERS=64 ./scripts/run_dag_star_sweep.sh
#   DATASET_NAME=my_sweep ./scripts/run_dag_star_sweep.sh
#
# Sweep mode:
#   SWEEP_MODE=param_study  per-axis parameter study around the
#                           prior search-strategy sweep's baseline
#                           (default for prod profile).
#   SWEEP_MODE=single       single workload config, varied only over
#                           network sizes (default for dev profile).
#
# Per-axis value overrides (param_study mode, each comma-separated):
#   AXIS_NETWORK_SIZE=10,30,50,100,200
#   AXIS_WORKLOAD_SIZE=3,5,7,10,20
#   AXIS_QUERY_LENGTH=3,5,8,10
#   AXIS_NUM_EVENT_TYPES=4,6,8,10
#
# Workload-shape overrides (single mode, each accepts a comma-separated list):
#   WORKLOAD_SIZES=5
#   QUERY_LENGTHS=3,5,7
#   NUM_EVENT_TYPES=4,6,8,10
#   EVENT_SKEWS=1.0,1.5,2.0
#   PARENT_FACTORS=1.8
#   NODE_EVENT_RATIOS=0.4,0.7
#
# Defaults in src/start_simulation.py main() match the prior search-strategy
# comparison sweep (workload=5, query_length=5, num_event_types=6,
# event_skew=2.0, parent_factor=1.8, node_event_ratio=0.7).
#
# PrePP-variance A/B flags:
#   PREPP_NONDETERMINISTIC=1  disable per-call RNG seeding in PrePP so it
#                             falls back to global `random.*`. Reintroduces
#                             the pre-deterministic-fix noise; the
#                             per-strategy cache clearing stays in place.
#   KRAKEN_STRATEGY_SET=noisy_compare  strip to {greedy, k=3, k=5, dag_star}.
#                                      Default "full" keeps all 6 strategies.
#
# What this writes:
#   src/result/<DATASET_NAME>.parquet/              per-run unified rows
#   src/result/<DATASET_NAME>_comparison.parquet/   wide-format rows w/ baselines
#
# Tip: clear stale output before a fresh sweep so you don't merge with prior runs:
#   rm -rf src/result/<DATASET_NAME>.parquet src/result/<DATASET_NAME>_comparison.parquet

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}/src"

export KRAKEN_PROFILE="${PROFILE:-prod}"
[[ -n "${RUNS:-}" ]]              && export KRAKEN_RUNS="${RUNS}"
[[ -n "${NETWORK_SIZES:-}" ]]     && export KRAKEN_NETWORK_SIZES="${NETWORK_SIZES}"
[[ -n "${MAX_WORKERS:-}" ]]       && export KRAKEN_MAX_WORKERS="${MAX_WORKERS}"
[[ -n "${DATASET_NAME:-}" ]]      && export KRAKEN_DATASET_NAME="${DATASET_NAME}"
[[ -n "${SWEEP_MODE:-}" ]]        && export KRAKEN_SWEEP_MODE="${SWEEP_MODE}"
[[ -n "${WORKLOAD_SIZES:-}" ]]    && export KRAKEN_WORKLOAD_SIZES="${WORKLOAD_SIZES}"
[[ -n "${QUERY_LENGTHS:-}" ]]     && export KRAKEN_QUERY_LENGTHS="${QUERY_LENGTHS}"
[[ -n "${NUM_EVENT_TYPES:-}" ]]   && export KRAKEN_NUM_EVENT_TYPES="${NUM_EVENT_TYPES}"
[[ -n "${EVENT_SKEWS:-}" ]]       && export KRAKEN_EVENT_SKEWS="${EVENT_SKEWS}"
[[ -n "${PARENT_FACTORS:-}" ]]    && export KRAKEN_PARENT_FACTORS="${PARENT_FACTORS}"
[[ -n "${NODE_EVENT_RATIOS:-}" ]] && export KRAKEN_NODE_EVENT_RATIOS="${NODE_EVENT_RATIOS}"
[[ -n "${AXIS_NETWORK_SIZE:-}" ]]    && export KRAKEN_AXIS_NETWORK_SIZE="${AXIS_NETWORK_SIZE}"
[[ -n "${AXIS_WORKLOAD_SIZE:-}" ]]   && export KRAKEN_AXIS_WORKLOAD_SIZE="${AXIS_WORKLOAD_SIZE}"
[[ -n "${AXIS_QUERY_LENGTH:-}" ]]    && export KRAKEN_AXIS_QUERY_LENGTH="${AXIS_QUERY_LENGTH}"
[[ -n "${AXIS_NUM_EVENT_TYPES:-}" ]] && export KRAKEN_AXIS_NUM_EVENT_TYPES="${AXIS_NUM_EVENT_TYPES}"
[[ -n "${PREPP_NONDETERMINISTIC:-}" ]] && export PREPP_NONDETERMINISTIC
[[ -n "${KRAKEN_STRATEGY_SET:-}" ]]    && export KRAKEN_STRATEGY_SET

echo "[sweep] starting at $(date)"
echo "[sweep] profile=${KRAKEN_PROFILE}"
echo "[sweep] runs=${KRAKEN_RUNS:-<profile default>}"
echo "[sweep] network_sizes=${KRAKEN_NETWORK_SIZES:-<profile default>}"
echo "[sweep] max_workers=${KRAKEN_MAX_WORKERS:-<profile default>}"
echo "[sweep] dataset_name=${KRAKEN_DATASET_NAME:-dag_star_sweep}"
echo "[sweep] prepp_mode=$([[ "${PREPP_NONDETERMINISTIC:-0}" == "1" ]] && echo "noisy" || echo "deterministic")"
echo "[sweep] strategy_set=${KRAKEN_STRATEGY_SET:-full}"
echo

python start_simulation.py 2>&1 | tee "../sweep_$(date +%Y%m%d_%H%M%S).log"

echo "[sweep] done at $(date)"
