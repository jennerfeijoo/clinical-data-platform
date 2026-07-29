# PostgreSQL loading benchmark

Generated: `2026-07-29T16:22:46.849797Z`

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
- Repetitions: `6`
- Warm-ups: `1`
- Seed: `20260729`

## Environment

- Package: `0.14.0`
- Git commit: `6a16037674386d7c33ca811ecff5a9dd02f19b14`
- Python: `3.11.15`
- PostgreSQL: `16.14`
- OS: `Linux-6.17.0-1020-azure-x86_64-with-glibc2.39`
- CPU: `AMD EPYC 7763 64-Core Processor`
- Logical CPUs: `4`
- Physical memory bytes: `16766418944`

## Aggregate results

| Patients | Clinical rows | Method | n | Median ms | Min ms | Max ms | Median rows/s |
|---:|---:|---|---:|---:|---:|---:|---:|
| 250 | 3750 | copy | 6 | 825.694 | 791.260 | 963.099 | 4541.8 |
| 250 | 3750 | executemany | 6 | 1083.028 | 1056.377 | 1093.184 | 3462.6 |
| 1000 | 15000 | copy | 6 | 3183.671 | 3038.401 | 3205.135 | 4711.5 |
| 1000 | 15000 | executemany | 6 | 4341.867 | 4189.997 | 4373.181 | 3454.8 |
| 2500 | 37500 | copy | 6 | 7936.444 | 7559.864 | 7970.342 | 4725.0 |
| 2500 | 37500 | executemany | 6 | 10955.541 | 10616.640 | 11063.774 | 3422.9 |

## COPY comparison

| Patients | Clinical rows | COPY median ms | executemany median ms | COPY speedup | Elapsed reduction |
|---:|---:|---:|---:|---:|---:|
| 250 | 3750 | 825.694 | 1083.028 | 1.312x | 23.76% |
| 1000 | 15000 | 3183.671 | 4341.867 | 1.364x | 26.68% |
| 2500 | 37500 | 7936.444 | 10955.541 | 1.380x | 27.56% |

## Interpretation limits

- Environment-specific engineering measurements, not universal PostgreSQL constants.
- GitHub-hosted runner hardware and contention can vary between runs.
- `executemany` is the previous application reference path, not every batching strategy.
- Initial governed loading only; no updates, concurrency or end-to-end pipeline latency.
- No peak-memory claim because Python allocation tracking omits PostgreSQL and native-driver memory.
- Descriptive medians only; the repetition count does not support inferential confidence intervals.
