#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:=postgresql://clinical_user:clinical_password@localhost:5432/clinical_data}"
export DATABASE_URL

python -m pip install -e '.[dev]'
docker compose up -d postgres

clinical-data-benchmark \
  --allow-destructive-reset \
  --patients 250 1000 2500 \
  --repetitions 6 \
  --warmups 1 \
  --seed 20260729 \
  --output-dir data/benchmarks/loading

printf '%s\n' 'Benchmark evidence written to data/benchmarks/loading'
