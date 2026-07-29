#!/usr/bin/env bash
set -euo pipefail

root="${1:-data/synthea}"
replace_flag=()
if [[ "${REPLACE:-0}" == "1" ]]; then
  replace_flag=(--replace)
fi

profiles=(
  "synthea-us-small-v1"
  "synthea-us-small-cohort-b-v1"
)

for profile in "${profiles[@]}"; do
  workspace="${root}/${profile}"
  clinical-data-cohort generate "${profile}" \
    --workspace "${workspace}" \
    "${replace_flag[@]}"
  clinical-data-cohort adapt "${profile}" \
    "${workspace}/generated/csv" \
    --output-dir "${workspace}/normalized" \
    --generation-manifest "${workspace}/synthea-generation-manifest.json" \
    "${replace_flag[@]}"
  clinical-data-cohort verify "${profile}" "${workspace}/normalized"
done

clinical-data-cohort compare \
  "${root}/synthea-us-small-v1/normalized" \
  "${root}/synthea-us-small-cohort-b-v1/normalized" \
  --output-dir "${root}/cohort-comparison" \
  "${replace_flag[@]}"

echo "Two verified disjoint Synthea cohorts are ready under ${root}"
