#!/usr/bin/env bash
set -euo pipefail

root="${1:-data/synthea}"
output_directory="${QUALITY_OUTPUT:-data/synthea/cohort-quality}"
replace_flag=()
if [[ "${REPLACE:-0}" == "1" ]]; then
  replace_flag=(--replace)
fi

clinical-data-cohort quality-report \
  "${root}/synthea-us-small-v1/normalized" \
  "${root}/synthea-us-small-cohort-b-v1/normalized" \
  --output-dir "${output_directory}" \
  "${replace_flag[@]}"
