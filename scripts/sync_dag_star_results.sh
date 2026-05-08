#!/usr/bin/env bash
# Pull the DAG* sweep results back from the dima.tu-berlin cluster.
#
# Usage (defaults match the cluster you usually run on — just call it):
#   ./scripts/sync_dag_star_results.sh
#
# Override any of:
#   SERVER            ssh target  (default: glueck-ldap@cloud-11.dima.tu-berlin.de)
#   SERVER_PATH       repo root on the cluster (default: /home/glueck-ldap/INES)
#   LOCAL_RESULT_DIR  destination (default: <repo>/src/result)
#   DATASET_NAME      sweep dataset name on the server (default: dag_star_sweep)
#   BACKUP_ROOT       extra mirror destination (default: ~/Desktop/Bachelorarbeit/Backups)
#                     set BACKUP_ROOT="" to skip the backup step entirely
#
# What this pulls:
#   - <DATASET_NAME>.parquet/        per-run unified rows (baselines)
#   - kraken_comparison.parquet/     wide-format comparison rows
#                                    (this is the dataset you'll analyse — it
#                                     contains every kraken strategy plus the
#                                     all-push / prepp / inev / sequential
#                                     baselines on every row)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVER="${SERVER:-glueck-ldap@cloud-11.dima.tu-berlin.de}"
SERVER_PATH="${SERVER_PATH:-/home/glueck-ldap/INES}"
LOCAL_RESULT_DIR="${LOCAL_RESULT_DIR:-${REPO_ROOT}/src/result}"
DATASET_NAME="${DATASET_NAME:-dag_star_sweep}"
BACKUP_ROOT="${BACKUP_ROOT:-/Users/finn/Desktop/Bachelorarbeit/Backups}"

mkdir -p \
  "${LOCAL_RESULT_DIR}/${DATASET_NAME}.parquet" \
  "${LOCAL_RESULT_DIR}/kraken_comparison.parquet"

echo "=== Step 1: Syncing from ${SERVER}:${SERVER_PATH}/src/result ==="
echo

echo "Syncing kraken_comparison.parquet/ ..."
rsync -avzP --no-perms --no-owner --no-group \
  "${SERVER}:${SERVER_PATH}/src/result/kraken_comparison.parquet/" \
  "${LOCAL_RESULT_DIR}/kraken_comparison.parquet/"

echo
echo "Syncing ${DATASET_NAME}.parquet/ ..."
rsync -avzP --no-perms --no-owner --no-group \
  "${SERVER}:${SERVER_PATH}/src/result/${DATASET_NAME}.parquet/" \
  "${LOCAL_RESULT_DIR}/${DATASET_NAME}.parquet/"

if [[ -n "${BACKUP_ROOT}" ]]; then
  echo
  echo "=== Step 2: Mirroring to ${BACKUP_ROOT} ==="
  mkdir -p \
    "${BACKUP_ROOT}/kraken_comparison.parquet" \
    "${BACKUP_ROOT}/${DATASET_NAME}.parquet"
  rsync -a --delete \
    "${LOCAL_RESULT_DIR}/kraken_comparison.parquet/" \
    "${BACKUP_ROOT}/kraken_comparison.parquet/"
  rsync -a --delete \
    "${LOCAL_RESULT_DIR}/${DATASET_NAME}.parquet/" \
    "${BACKUP_ROOT}/${DATASET_NAME}.parquet/"
else
  echo
  echo "(skipping backup — BACKUP_ROOT is empty)"
fi

echo
echo "=== Done. Local fragment counts: ==="
python3 - <<PY
from pathlib import Path
for d in [Path("${LOCAL_RESULT_DIR}/kraken_comparison.parquet"),
          Path("${LOCAL_RESULT_DIR}/${DATASET_NAME}.parquet")]:
    if d.is_dir():
        n = sum(1 for _ in d.glob("*.parquet"))
        print(f"  {d.name:40s} {n:>5d} fragments")
PY
