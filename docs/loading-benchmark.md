# Governed PostgreSQL loading benchmark

## Purpose

This benchmark measures the loading kernel introduced by the PostgreSQL COPY milestone. It answers a narrow engineering question:

> For the same deterministic six-entity synthetic workload and the same governed clinical tables, how does COPY-to-temporary-staging followed by a set merge compare with the previous psycopg `executemany` upsert path?

It does not benchmark the complete clinical data pipeline.

## What is compared

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

`executemany` is the previous application implementation and therefore a useful internal reference. It is not a claim that every possible PostgreSQL batching strategy behaves identically.

## Governed target state

Both methods write to the actual migrated clinical model. The benchmark leaves active:

- foreign keys;
- check constraints;
- terminology-resolution triggers;
- normalized concept assignment;
- record SHA-256 generation;
- patient SCD Type 2 history;
- immutable-event conflict guards;
- transaction commits;
- lineage foreign keys through `source_run_id`.

The benchmark does not disable triggers, constraints, WAL durability settings, or synchronous commits.

## Measurement boundary

Measured time includes:

```text
contract-compatible string-to-type conversion
Python/psycopg transfer
COPY staging or executemany upsert
set merge for COPY
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
post-load row-count and fingerprint verification
artifact serialization
```

The benchmark is therefore a governed persistence-kernel benchmark, not an end-to-end pipeline benchmark.

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

The documented profile uses:

| Control | Value |
|---|---|
| Seed | `20260729` |
| Reference date | `2026-07-29` |
| Patient sizes | 250, 1,000, 2,500 |
| Clinical row sizes | 3,750, 15,000, 37,500 |
| Warm-ups | 1 per method and size |
| Measured repetitions | 5 per method and size |
| Method order | Alternating AB/BA |
| Writer concurrency | 1 |

Every generated workload has a SHA-256 fingerprint derived from its configuration and canonical record content.

## Why method order alternates

Always running COPY first or always running it second would confound method with order. Cache state, background activity, database page residency, CPU frequency, and runner contention can change during execution.

Measured repetitions therefore use:

```text
repetition 1: COPY → executemany
repetition 2: executemany → COPY
repetition 3: COPY → executemany
repetition 4: executemany → COPY
repetition 5: COPY → executemany
```

This does not eliminate all environmental variation, but it prevents a fixed ordering bias.

## Correctness gate

A faster method is irrelevant if it produces different data. After every trial the benchmark verifies:

- exact row counts for all six entities;
- patient-history row count;
- exactly one current patient-history row per patient;
- terminology binding count;
- ordered aggregate digest of `record_sha256` values per entity;
- one combined database-content fingerprint.

For each population size, all COPY and `executemany` trials must produce the same database fingerprint. The benchmark fails before publishing results when fingerprints differ.

The reference execution produced one stable fingerprint per size across all ten measured trials:

| Patients | Database-content fingerprint |
|---:|---|
| 250 | `d8774d0544ed3e54645ab416d457bc71d148de15d82b998b397cfaa287ba6671` |
| 1,000 | `0de3fb68be7f9d01ddc6cf6d7ce929ecf7c15c1f1b8a5bd0f4d780b633cf8b2a` |
| 2,500 | `c224fd2dac09e27af51186c2986d3efb05a305fb0d68a8356b8af6061821a8e7` |

These are fingerprints of governed database content, not hashes of the source workload files.

## Metrics

For each trial:

```text
elapsed_ms = measured wall-clock nanoseconds / 1,000,000
rows_per_second = total clinical rows / elapsed seconds
```

For each method and workload size, the benchmark reports:

- minimum elapsed time;
- maximum elapsed time;
- arithmetic mean;
- standard deviation;
- median elapsed time;
- median throughput;
- median elapsed time by dataset.

The headline comparison uses medians:

```text
COPY speedup = executemany median / COPY median

elapsed reduction (%) =
    (1 - COPY median / executemany median) × 100
```

Median is used as the headline statistic because it is less sensitive than the mean to an isolated slow trial on shared infrastructure.

## Reference environment

The committed reference execution was GitHub Actions workflow run `30466706538`.

| Property | Value |
|---|---|
| Workflow head SHA | `db4975cf09a5eec6b8ec7e18a292fc13234821ab` |
| Recorded GitHub merge-ref SHA | `7efadba8f634132d34444fc501fa1602c298a1d6` |
| Package version during measurement | `0.13.0` |
| Python | CPython 3.11.15 |
| PostgreSQL | 16.14 |
| Runner OS | Ubuntu 24.04 generation, Linux 6.17 Azure kernel |
| CPU model | AMD EPYC 9V74 80-Core Processor |
| Logical CPUs visible | 4 |
| Physical memory visible | 16,766,423,040 bytes |
| `fsync` | on |
| `full_page_writes` | on |
| `synchronous_commit` | on |
| `wal_level` | replica |
| `shared_buffers` | 128 MB |

The CPU model describes the host family. The job had four logical CPUs available; it did not have exclusive access to eighty cores.

## Reference results

| Patients | Clinical rows | COPY median | `executemany` median | COPY throughput | Reference throughput | Speedup | Time reduction |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 250 | 3,750 | 671.737 ms | 928.806 ms | 5,582.5 rows/s | 4,037.4 rows/s | 1.383× | 27.68% |
| 1,000 | 15,000 | 2,615.950 ms | 3,693.506 ms | 5,734.1 rows/s | 4,061.2 rows/s | 1.412× | 29.17% |
| 2,500 | 37,500 | 6,465.960 ms | 9,176.855 ms | 5,799.6 rows/s | 4,086.4 rows/s | 1.419× | 29.54% |

Within this environment and workload, COPY was consistently faster. The measured advantage increased modestly with workload size.

## Per-dataset observations

At 2,500 patients, the median COPY times were:

| Dataset | Rows | Median time |
|---|---:|---:|
| patients | 2,500 | 321.863 ms |
| encounters | 5,000 | 450.492 ms |
| diagnoses | 5,000 | 925.393 ms |
| observations | 15,000 | 2,834.134 ms |
| medications | 5,000 | 980.865 ms |
| procedures | 5,000 | 954.076 ms |

Observations dominate total time because they contain three times as many rows as each two-per-patient event table. Medication, diagnosis, and procedure loads also execute terminology and immutability logic.

These component times overlap with no other dataset because datasets are loaded sequentially. Their sum is close to, but need not exactly equal, total elapsed time due to timer placement and Python loop overhead.

## Replication evidence

An earlier independent workflow execution, run `30466367453`, used the same workload and environment profile and observed:

| Patients | COPY speedup | Time reduction |
|---:|---:|---:|
| 250 | 1.380× | 27.52% |
| 1,000 | 1.407× | 28.94% |
| 2,500 | 1.423× | 29.73% |

The close results support repeatability on two adjacent hosted-runner executions. Two runs are still insufficient to characterize long-term runner variance.

## Evidence files

Permanent reference evidence is stored under:

```text
benchmarks/loading/github-actions-run-30466706538/
├── benchmark-summary.md
├── benchmark-trials.csv
└── reference-run.json
```

`reference-run.json` contains:

- workflow and artifact provenance;
- artifact digest;
- hashes of the original generated files;
- benchmark configuration;
- environment metadata;
- workload fingerprints;
- aggregate results;
- comparisons;
- interpretation limits.

The original workflow artifact was:

```text
artifact id:      8729938736
artifact name:    governed-loading-benchmark
artifact digest:  sha256:928281815f5c26481a5f7a762826e481cc4047f216cfecdd9f5560239c04e163
```

GitHub artifact retention is finite. The committed evidence remains available after artifact expiration.

## Run locally

Requirements:

- Python 3.11 or later;
- PostgreSQL accessible through `DATABASE_URL`;
- migrated platform schema;
- an isolated database whose benchmark data may be deleted.

The benchmark truncates platform run state with cascading deletion before each trial. It must not be pointed at a database containing data that must be retained.

PowerShell:

```powershell
python -m pip install -e ".[dev]"
docker compose up -d postgres

$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"

clinical-data-benchmark `
    --patients 250 1000 2500 `
    --repetitions 5 `
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
  --patients 250 1000 2500 \
  --repetitions 5 \
  --warmups 1 \
  --seed 20260729 \
  --output-dir data/benchmarks/loading
```

## Automated workflow

The dedicated workflow is:

```text
.github/workflows/benchmark.yml
```

It runs when:

- manually dispatched;
- benchmark implementation paths change in a pull request;
- benchmark implementation paths change on `main`.

The workflow writes the Markdown summary to the GitHub job summary and uploads all generated evidence as the `governed-loading-benchmark` artifact.

Normal CI does not run the full 37,500-row protocol on every unrelated change. It runs a small PostgreSQL integration benchmark to verify method equivalence and artifact generation.

## Interpretation rules

The measured values support this statement:

> On the recorded GitHub Actions environment, for deterministic initial loading of 3,750–37,500 rows into the governed six-entity schema, COPY-to-temporary-staging plus set merge reduced median loading time by 27.68–29.54% relative to the previous psycopg `executemany` reference path.

They do not support these statements:

```text
COPY is always 30% faster.
The full pipeline is 30% faster.
The application can load a hospital database at 5,800 rows/s.
Memory use was reduced by a known percentage.
The result applies unchanged to concurrent writers or updates.
The result proves production capacity.
```

## Known limitations

1. GitHub-hosted runners are shared and can vary between executions.
2. Five repetitions provide descriptive evidence, not inferential confidence intervals.
3. Only initial inserts are measured; update-heavy conflict paths are not.
4. Only one writer is active.
5. Network distance is minimal because PostgreSQL runs as a local service container.
6. Workload values are synthetic and deliberately regular.
7. The largest measured workload contains 37,500 rows, not millions.
8. The full validation and audit lifecycle is outside the timed region.
9. Peak memory is not reported because Python-only allocation tracking would omit native driver and PostgreSQL memory.
10. Database storage growth, WAL bytes, CPU utilization, and I/O counters are not yet measured.

## Future benchmark extensions

Possible future experiments include:

- end-to-end validation plus persistence;
- Synthea populations larger than 2,500 patients;
- update and exact-duplicate workloads;
- concurrent loaders;
- remote PostgreSQL latency;
- WAL-volume comparison;
- container CPU and memory limits;
- cold-start versus warm-cache profiles;
- PostgreSQL versions other than 16;
- alternative batch sizes and prepared-statement strategies.

These extensions should remain separate profiles rather than being silently mixed into the current reference benchmark.
