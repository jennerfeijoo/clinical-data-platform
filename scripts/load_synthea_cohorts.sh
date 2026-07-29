#!/usr/bin/env bash
set -euo pipefail

root="${1:-data/synthea}"
processed_root="${PROCESSED_ROOT:-data/processed/synthea-cohorts}"
raw_root="${RAW_ROOT:-data/raw}"
replace_flag=()
if [[ "${REPLACE_COMPARISON:-0}" == "1" ]]; then
  replace_flag=(--replace)
fi

clinical-data-cohort load-pair \
  "${root}/synthea-us-small-v1/normalized" \
  "${root}/synthea-us-small-cohort-b-v1/normalized" \
  --processed-root "${processed_root}" \
  --raw-root "${raw_root}" \
  --output-dir "${root}/cohort-comparison" \
  "${replace_flag[@]}"
