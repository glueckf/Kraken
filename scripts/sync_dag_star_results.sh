#!/usr/bin/env bash
# Pull the DAG* sweep results back from the cluster.
#
# Usage:
#   SERVER=user@host SERVER_PATH=/path/to/INES ./scripts/sync_dag_star_results.sh
#
# Optional env vars:
#   LOCAL_RESULT_DIR  destination (default: ./src/result)
#   DATASET_NAME      sweep dataset name on the server (default: dag_star_sweep)
#
# What this pulls:
#   - <DATASET_NAME>.parquet/        per-run unified rows (baselines)
#   - kraken_comparison.parquet/     wide-format comparison rows
#                                    (this is the dataset you'll analyse — it
#                                     contains every kraken strategy plus the
#                                     all-push / prepp / inev / sequential
#                                     baselines on every row)

set -euo pipefail

if [[ -z "${SERVER:-}" ]]; then
  echo "ERROR: set SERVER=user@host first." >&2
  exit 1
fi
if [[ -z "${SERVER_PATH:-}" ]]; then
  echo "ERROR: set SERVER_PATH=/path/to/INES on the cluster first." >&2
  exit 1
fi

LOCAL_RESULT_DIR="${LOCAL_RESULT_DIR:-./src/result}"
DATASET_NAME="${DATASET_NAME:-dag_star_sweep}"

mkdir -p "${LOCAL_RESULT_DIR}"

echo "[sync] pulling kraken_comparison.parquet/ ..."
rsync -av --delete \
  "${SERVER}:${SERVER_PATH}/src/result/kraken_comparison.parquet/" \
  "${LOCAL_RESULT_DIR}/kraken_comparison.parquet/"

echo "[sync] pulling ${DATASET_NAME}.parquet/ ..."
rsync -av --delete \
  "${SERVER}:${SERVER_PATH}/src/result/${DATASET_NAME}.parquet/" \
  "${LOCAL_RESULT_DIR}/${DATASET_NAME}.parquet/"

echo "[sync] done. local row counts:"
python -c "
import pandas as pd
from pathlib import Path
for d in Path('${LOCAL_RESULT_DIR}').glob('*.parquet'):
    if d.is_dir():
        try:
            n = sum(1 for _ in d.glob('*.parquet'))
            print(f'  {d.name:40s} {n:>4d} fragments')
        except Exception as e:
            print(f'  {d.name:40s} ERROR: {e}')
"
