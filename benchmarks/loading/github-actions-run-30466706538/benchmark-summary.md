# PostgreSQL loading benchmark

Generated: `2026-07-29T15:39:49.565568Z`

## Protocol

- Synthetic deterministic six-entity workload.
- Actual governed clinical tables and active triggers/constraints.
- COPY uses temporary staging plus set-based merge.
- Reference uses psycopg `executemany` with the equivalent upsert.
- Warm-up per method; measured method order alternates by repetition.
- Timing includes row conversion, transfer, triggers, constraints, merge/upsert and commit.
- Timing excludes generation, raw capture, contract validation, audit registration and verification queries.

## Configuration

- Patient counts: `[250, 1000, 2500]`
- Repetitions: `5`
- Warm-ups: `1`
- Seed: `20260729`

## Environment

- Package: `0.13.0`
- Git commit: `7efadba8f634132d34444fc501fa1602c298a1d6`
- Python: `3.11.15`
- PostgreSQL: `16.14`
- OS: `Linux-6.17.0-1020-azure-x86_64-with-glibc2.39`
- CPU: `AMD EPYC 9V74 80-Core Processor`
- Logical CPUs: `4`
- Physical memory bytes: `16766423040`

## Aggregate results

| Patients | Clinical rows | Method | n | Median ms | Min ms | Max ms | Median rows/s |
|---:|---:|---|---:|---:|---:|---:|---:|
| 250 | 3750 | copy | 5 | 671.737 | 669.966 | 677.948 | 5582.5 |
| 250 | 3750 | executemany | 5 | 928.806 | 917.692 | 953.615 | 4037.4 |
| 1000 | 15000 | copy | 5 | 2615.950 | 2593.090 | 2618.514 | 5734.1 |
| 1000 | 15000 | executemany | 5 | 3693.506 | 3667.627 | 3703.682 | 4061.2 |
| 2500 | 37500 | copy | 5 | 6465.960 | 6443.684 | 6493.249 | 5799.6 |
| 2500 | 37500 | executemany | 5 | 9176.855 | 8913.382 | 9250.612 | 4086.4 |

## COPY comparison

| Patients | Clinical rows | COPY median ms | executemany median ms | COPY speedup | Elapsed reduction |
|---:|---:|---:|---:|---:|---:|
| 250 | 3750 | 671.737 | 928.806 | 1.383x | 27.68% |
| 1000 | 15000 | 2615.950 | 3693.506 | 1.412x | 29.17% |
| 2500 | 37500 | 6465.960 | 9176.855 | 1.419x | 29.54% |

## Interpretation limits

- Environment-specific engineering measurements, not universal PostgreSQL constants.
- GitHub-hosted runner hardware and contention can vary between runs.
- `executemany` is the previous application reference path, not every batching strategy.
- Initial governed loading only; no updates, concurrency or end-to-end pipeline latency.
- No peak-memory claim because Python allocation tracking omits PostgreSQL and native-driver memory.
- Descriptive medians only; the repetition count does not support inferential confidence intervals.
