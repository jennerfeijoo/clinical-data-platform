# Governed PostgreSQL loading benchmark

## Purpose

This benchmark measures the loading kernel introduced by the PostgreSQL COPY milestone. It answers a narrow engineering question:

> For the same deterministic six-entity synthetic workload and the same governed clinical tables, how does COPY-to-temporary-staging followed by a set merge compare with the previous psycopg `executemany` upsert path?

It does not benchmark the complete clinical data pipeline.

## Compared methods

### COPY method

```text
typed row iterator
→ COPY FROM STDIN
→ session-local temporary staging table
→ INSERT ... SELECT ... ON CONFLICT
→ governed clinical target
→ COMMIT
```

### Reference method

```text
typed row iterator
→ psycopg executemany
→ equivalent INSERT ... ON CONFLICT
→ governed clinical target
→ COMMIT
```

`executemany` is the former application implementation. It is a useful internal reference, not a claim about every possible PostgreSQL batch-loading strategy.

## Governed target state

Both methods write to the actual migrated clinical model. The benchmark leaves active:

- foreign keys;
- check constraints;
- indexes;
- terminology-resolution triggers;
- normalized concept assignment;
- record SHA-256 generation;
- patient SCD Type 2 history;
- immutable-event conflict guards;
- transaction commits;
- lineage foreign keys through `source_run_id`;
- PostgreSQL durability settings such as `fsync` and `synchronous_commit`.

The benchmark does not disable triggers, change `session_replication_role`, or write directly to history tables.

## Measurement boundary

Measured time includes:

```text
contract-compatible string-to-type conversion
Python/psycopg transfer
COPY staging or executemany upsert
set-based merge for COPY
clinical triggers
constraints and indexes
transaction commit
```

Measured time excludes:

```text
synthetic workload generation
Synthea generation
immutable raw capture
contract validation
quality-report creation
full durable execution-audit lifecycle
post-load verification queries
artifact serialization
```

The result therefore describes a governed persistence kernel, not end-to-end pipeline latency.

## Deterministic workload

The workload generator is implemented in:

```text
src/clinical_data_platform/benchmark.py
```

For each patient it creates:

| Dataset | Rows per patient |
|---|---:|
| patients | 1 |
| encounters | 2 |
| diagnoses | 2 |
| observations | 6 |
| medications | 2 |
| procedures | 2 |
| Total | 15 |

The reference profile fixes:

| Control | Value |
|---|---|
| Seed | `20260729` |
| Reference date | `2026-07-29` |
| Patient sizes | 250, 1,000, 2,500 |
| Clinical row sizes | 3,750, 15,000, 37,500 |
| Warm-ups | 1 per method and size |
| Measured repetitions | 6 per method and size |
| Method order | alternating AB/BA |
| COPY starts first | 3 repetitions |
| `executemany` starts first | 3 repetitions |
| Writer concurrency | 1 |

Every workload has a SHA-256 fingerprint derived from its configuration and canonical record content.

## Balanced ordering

A fixed order would confound method with execution position. Cache residency, runner contention, CPU frequency, background activity, and page state can change over time.

The six measured repetitions use:

```text
repetition 1: COPY → executemany
repetition 2: executemany → COPY
repetition 3: COPY → executemany
repetition 4: executemany → COPY
repetition 5: COPY → executemany
repetition 6: executemany → COPY
```

Each method therefore appears first three times and second three times.

## Database safety gate

The benchmark resets platform state between trials. It must never be pointed casually at a working database.

The CLI requires:

```text
--allow-destructive-reset
```

After applying migrations, it enumerates every base table in:

```text
audit
clinical
analytics
```

It counts rows in each table and refuses to start if any table is populated. The terminology schema is excluded because migrations intentionally seed its local reference subset and the benchmark does not truncate it.

This creates two independent safeguards:

```text
explicit destructive confirmation
+
verified empty governed schemas
```

The benchmark should still be run only against a dedicated disposable database.

## Correctness gate

A method is not accepted as faster unless it produces equivalent governed content. After every trial the benchmark verifies:

- exact row counts for all six entities;
- patient-history row count;
- exactly one current history row per patient;
- terminology binding count;
- ordered aggregate digest of `record_sha256` values per entity;
- one combined database-content fingerprint.

For each population size, all twelve measured trials must produce one identical database fingerprint.

Reference fingerprints:

| Patients | Database-content fingerprint |
|---:|---|
| 250 | `d8774d0544ed3e54645ab416d457bc71d148de15d82b998b397cfaa287ba6671` |
| 1,000 | `0de3fb68be7f9d01ddc6cf6d7ce929ecf7c15c1f1b8a5bd0f4d780b633cf8b2a` |
| 2,500 | `c224fd2dac09e27af51186c2986d3efb05a305fb0d68a8356b8af6061821a8e7` |

These identify governed database content, not source files or real patients.

## Metrics

For one trial:

```text
elapsed_ms = measured wall-clock nanoseconds / 1,000,000
rows_per_second = total clinical rows / elapsed seconds
```

For each method and workload size, the report stores:

- minimum elapsed time;
- maximum elapsed time;
- arithmetic mean;
- standard deviation;
- median elapsed time;
- median throughput;
- median elapsed time by dataset.

The headline comparison uses:

```text
COPY speedup = executemany median / COPY median

elapsed reduction (%) =
    (1 - COPY median / executemany median) × 100
```

The median is less sensitive than the mean to one unusually slow hosted-runner trial.

## Balanced reference environment

The project reference is GitHub Actions workflow run `30470147850`.

| Property | Value |
|---|---|
| Workflow head SHA | `e265dc00413688752ce652ef26a3b324bc3564c2` |
| Recorded GitHub merge-ref SHA | `6a16037674386d7c33ca811ecff5a9dd02f19b14` |
| Package | `0.14.0` |
| Python | CPython 3.11.15 |
| PostgreSQL | 16.14 |
| OS | Linux 6.17 Azure kernel on Ubuntu runner image |
| CPU model | AMD EPYC 7763 64-Core Processor |
| Logical CPUs visible | 4 |
| Physical memory visible | 16,766,418,944 bytes |
| `fsync` | on |
| `full_page_writes` | on |
| `synchronous_commit` | on |
| `wal_level` | replica |
| `shared_buffers` | 128 MB |

The CPU model names the host processor family. The job had four logical CPUs visible, not sixty-four exclusive cores.

## Balanced reference results

| Patients | Clinical rows | COPY median | `executemany` median | COPY throughput | Reference throughput | Speedup | Time reduction |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 250 | 3,750 | 825.694 ms | 1,083.028 ms | 4,541.8 rows/s | 3,462.6 rows/s | 1.312× | 23.76% |
| 1,000 | 15,000 | 3,183.671 ms | 4,341.867 ms | 4,711.5 rows/s | 3,454.8 rows/s | 1.364× | 26.68% |
| 2,500 | 37,500 | 7,936.444 ms | 10,955.541 ms | 4,725.0 rows/s | 3,422.9 rows/s | 1.380× | 27.56% |

Within this environment and workload, COPY was faster at all three sizes. The relative advantage increased with workload size.

## Per-dataset observations

At 2,500 patients, COPY median component times were:

| Dataset | Rows | Median time |
|---|---:|---:|
| patients | 2,500 | 412.744 ms |
| encounters | 5,000 | 565.922 ms |
| diagnoses | 5,000 | 1,134.315 ms |
| observations | 15,000 | 3,467.419 ms |
| medications | 5,000 | 1,196.348 ms |
| procedures | 5,000 | 1,150.883 ms |

Observations dominate because they contain three times as many rows as each two-per-patient event table. Coded entities also execute terminology and immutability logic.

## Prior evidence

An earlier five-repetition run produced stronger-looking speedups, approximately 1.38–1.42×. It is retained under:

```text
benchmarks/loading/github-actions-run-30466706538/
```

That run is no longer the project reference because five alternating repetitions gave COPY three first positions and `executemany` only two. It remains useful provenance but should not replace the balanced result.

## Evidence files

Balanced evidence is stored under:

```text
benchmarks/loading/github-actions-run-30470147850/
├── benchmark-summary.md
├── benchmark-trials.csv
└── reference-run.json
```

`reference-run.json` records:

- workflow and artifact provenance;
- artifact digest;
- hashes of original generated evidence files;
- configuration;
- environment metadata;
- workload fingerprints;
- aggregate results;
- comparisons;
- limitations.

Original artifact:

```text
artifact id:      8731378490
artifact name:    governed-loading-benchmark
artifact digest:  sha256:89b3a915252096bbe9b1ba3ccc02b88d73c34b8cb7a8dafff5faeb1a48bc00fa
```

GitHub artifact retention is finite. The committed evidence remains available after artifact expiration.

## Run locally

Requirements:

- Python 3.11 or later;
- PostgreSQL accessible through `DATABASE_URL`;
- a dedicated empty database;
- permission to migrate and truncate platform tables.

PowerShell:

```powershell
python -m pip install -e ".[dev]"
docker compose up -d postgres

$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"

clinical-data-benchmark `
    --allow-destructive-reset `
    --patients 250 1000 2500 `
    --repetitions 6 `
    --warmups 1 `
    --seed 20260729 `
    --output-dir data/benchmarks/loading
```

POSIX shell:

```bash
python -m pip install -e '.[dev]'
docker compose up -d postgres
export DATABASE_URL='postgresql://clinical_user:clinical_password@localhost:5432/clinical_data'

clinical-data-benchmark \
  --allow-destructive-reset \
  --patients 250 1000 2500 \
  --repetitions 6 \
  --warmups 1 \
  --seed 20260729 \
  --output-dir data/benchmarks/loading
```

Odd repetition counts are rejected by the CLI because they cannot balance the starting position of two methods.

## Automated workflow

The dedicated workflow is:

```text
.github/workflows/benchmark.yml
```

It runs when benchmark implementation paths change and can also be dispatched manually. It writes the Markdown summary to the GitHub job summary and uploads all generated evidence.

Normal CI runs a small two-repetition integration benchmark. The larger profile remains separate because performance evidence is slower and more environmentally variable than ordinary correctness tests.

## Responsible interpretation

The measured values support:

> On the recorded GitHub Actions environment, for deterministic initial loading of 3,750–37,500 rows into the governed six-entity schema, COPY-to-temporary-staging plus set merge reduced median loading time by 23.76–27.56% relative to the former psycopg `executemany` path.

They do not support:

```text
COPY is always 25% faster.
The complete pipeline is 25% faster.
The platform can sustain hospital production traffic.
The rate remains constant at millions of rows.
Peak memory was reduced by a known amount.
The result applies unchanged to remote or concurrent PostgreSQL.
```

## Limitations

1. GitHub-hosted runners are shared and vary between executions.
2. Six repetitions provide descriptive evidence, not robust inferential confidence intervals.
3. Only initial inserts are measured; update-heavy conflict paths are not.
4. Only one writer is active.
5. PostgreSQL runs as a local service container.
6. The workload is synthetic and deliberately regular.
7. The largest profile contains 37,500 rows, not millions.
8. Validation and the full execution-audit lifecycle are outside the timed region.
9. Peak memory is not reported because Python-only tracking omits native-driver and PostgreSQL memory.
10. WAL bytes, CPU utilization, storage growth, and I/O counters are not measured.

## Future extensions

Future profiles may cover:

- end-to-end validation plus persistence;
- larger Synthea populations;
- update and exact-duplicate workloads;
- conflicting immutable events;
- concurrent writers;
- remote PostgreSQL latency;
- WAL-volume comparison;
- explicit CPU and memory limits;
- cold-cache and warm-cache profiles;
- other PostgreSQL versions;
- alternative batching and prepared-statement strategies.

Those experiments should remain separate profiles rather than being silently mixed into this reference.
