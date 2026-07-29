#!/bin/sh
set -eu

WORKSPACE=${1:-data/synthea/synthea-us-small-v1}
REPLACE=${REPLACE:-false}

GENERATE_ARGS="--workspace $WORKSPACE"
ADAPT_REPLACE=""
if [ "$REPLACE" = "true" ]; then
  GENERATE_ARGS="$GENERATE_ARGS --replace"
  ADAPT_REPLACE="--replace"
fi

clinical-data synthea-profile
# shellcheck disable=SC2086
clinical-data synthea-generate $GENERATE_ARGS

CSV_DIRECTORY="$WORKSPACE/generated/csv"
NORMALIZED_DIRECTORY="$WORKSPACE/normalized"
GENERATION_MANIFEST="$WORKSPACE/synthea-generation-manifest.json"

# shellcheck disable=SC2086
clinical-data synthea-adapt "$CSV_DIRECTORY" \
  --output-dir "$NORMALIZED_DIRECTORY" \
  --generation-manifest "$GENERATION_MANIFEST" \
  $ADAPT_REPLACE
clinical-data synthea-verify "$NORMALIZED_DIRECTORY"

printf 'Reproducible Synthea dataset ready at %s\n' "$NORMALIZED_DIRECTORY"
