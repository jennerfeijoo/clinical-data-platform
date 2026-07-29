# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.14.0` adds a reproducible, correctness-gated benchmark for governed PostgreSQL loading.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates how healthcare-like CSV sources become auditable, terminology-linked, analysis-ready datasets.

The repository uses synthetic data only. It is intended for engineering review and learning, not for identifiable patient data, clinical decisions, epidemiological inference, regulatory deployment, or production healthcare operations.

## Architecture

```text
Pinned Synthea profile or external CSV
            │
            ▼
Immutable raw landing zone
    ├── content-addressed object
    └── append-only receipt
            │
            ▼
Versioned executable contract
            │
            ▼
Generic validation pipeline
    ├── valid rows
    ├── quarantined rows
    ├── normalized validation errors
    ├── quality report
    └── hash-chained local execution journal
            │
            ▼
Durable loading attempt
            │
            ▼
Streaming type conversion
            │
            ▼
PostgreSQL COPY FROM STDIN
            │
            ▼
Temporary typed staging table
            │
            ▼
INSERT ... SELECT ... ON CONFLICT
            │
            ├── terminology resolution
            ├── record hashes
            ├── patient SCD Type 2 history
            ├── immutable-event guards
            ├── foreign keys and checks
            └── source-run lineage
            │
            ▼
Versioned cohort SQL and feature export
```

Structured JSON logs observe operations. PostgreSQL stores authoritative execution states, ordered events, retries, and durable failure evidence.

There is no patient-specific pipeline, no Synthea-specific persistence path, no permanent staging schema, and no monolithic schema installer.

## Governed loading benchmark

The benchmark compares the current production loading kernel:

```text
typed row iterator
→ COPY FROM STDIN
→ temporary typed staging
→ set-based INSERT ... SELECT ... ON CONFLICT
```

with the previous application reference:

```text
typed row iterator
→ psycopg executemany
→ equivalent INSERT ... ON CONFLICT
```

Both methods write to the same migrated clinical tables with terminology triggers, record hashes, patient history, event immutability, indexes, constraints, lineage foreign keys, WAL durability settings, and commits active.

### Protocol

| Control | Value |
|---|---|
| Data | deterministic synthetic six-entity workload |
| Seed | `20260729` |
| Reference date | `2026-07-29` |
| Patient sizes | 250, 1,000, 2,500 |
| Clinical rows | 3,750, 15,000, 37,500 |
| Warm-ups | 1 per method and size |
| Measured repetitions | 6 per method and size |
| Starting-position balance | COPY first 3 times; `executemany` first 3 times |
| Writer concurrency | 1 |

Every trial must pass exact row-count, patient-history, terminology-binding, record-hash, and database-content fingerprint checks before its timing is accepted.

### Balanced reference result

GitHub Actions workflow run `30470147850` produced:

| Patients | Rows | COPY median | `executemany` median | COPY speedup | Time reduction |
|---:|---:|---:|---:|---:|---:|
| 250 | 3,750 | 825.694 ms | 1,083.028 ms | 1.312× | 23.76% |
| 1,000 | 15,000 | 3,183.671 ms | 4,341.867 ms | 1.364× | 26.68% |
| 2,500 | 37,500 | 7,936.444 ms | 10,955.541 ms | 1.380× | 27.56% |

This supports a limited engineering statement: on the recorded hosted-runner environment, COPY reduced median governed initial-load time by approximately **23.8–27.6%** relative to the former `executemany` path.

It does not show that the complete pipeline is faster by the same amount, nor that these rates apply to production, remote PostgreSQL, concurrent writers, updates, millions of rows, or identifiable clinical data.

Permanent evidence:

```text
benchmarks/loading/github-actions-run-30470147850/
├── benchmark-summary.md
├── benchmark-trials.csv
└── reference-run.json
```

The earlier five-repetition evidence remains in its original directory as superseded provenance; the balanced six-repetition run is the project reference.

Technical protocol: [`docs/loading-benchmark.md`](docs/loading-benchmark.md).

Spanish study guide: [`docs/learning/benchmark-carga-postgresql-es.md`](docs/learning/benchmark-carga-postgresql-es.md).

### Safety boundary

The benchmark is destructive by design because it resets platform tables between trials. The CLI requires:

```text
--allow-destructive-reset
```

After migrations, it inspects every base table in the `audit`, `clinical`, and `analytics` schemas. It refuses to run when any of those tables contains rows. Use a dedicated disposable database.

Run the bundled local profile:

```powershell
.\scripts\run_benchmark.ps1
```

or:

```bash
./scripts/run_benchmark.sh
```

Direct invocation:

```powershell
clinical-data-benchmark `
    --allow-destructive-reset `
    --patients 250 1000 2500 `
    --repetitions 6 `
    --warmups 1 `
    --seed 20260729 `
    --output-dir data/benchmarks/loading
```

## PostgreSQL COPY loading

Validated outputs are inspected and counted without retaining the persistence batch in memory. They are reopened as iterators, converted to typed Python values one row at a time, and transmitted with psycopg `COPY FROM STDIN`.

```text
valid_<dataset>.csv
→ streaming iterator
→ COPY to temporary table
→ set-based target merge
→ target triggers and constraints
```

COPY does not write directly to governed targets because direct COPY cannot express the required conflict policies. Temporary staging separates efficient transfer from clinical reconciliation.

Each staging table:

```text
has target PostgreSQL column types
has a unique session-local name
uses ON COMMIT DROP
has no copied indexes, constraints, or triggers
```

The target merge preserves:

```text
patients
→ current snapshot + SCD Type 2 history

events
→ exact duplicate tolerance + conflicting identity rejection

coded entities
→ terminology resolution

all entities
→ foreign keys, checks, lineage, rollback, and retries
```

Validation errors are also loaded with COPY inside the same clinical transaction. A COPY, merge, terminology, history, or constraint failure rolls back clinical changes and is stored as a durable failed attempt in a separate transaction.

See [`docs/bulk-loading.md`](docs/bulk-loading.md).

## Reproducible Synthea workflow

The packaged profile pins:

| Control | Value |
|---|---|
| Synthea release | `v4.0.0` |
| Population | 100 |
| Random seed | 20260729 |
| Clinician seed | 20260730 |
| Reference date | 2026-07-29 |
| Geography | Massachusetts |
| Threads | 1 |
| Retained history | complete |
| Export | six CSV files |

The adapter converts:

```text
Synthea patients.csv      → patients.csv
Synthea encounters.csv    → encounters.csv
Synthea conditions.csv    → diagnoses.csv
Synthea observations.csv  → observations.csv
Synthea medications.csv   → medications.csv
Synthea procedures.csv    → procedures.csv
```

It also produces `terminology.csv` and `synthea-adaptation-manifest.json`. Missing source-event identifiers use deterministic UUIDv5 values. Parent relationships, source headers, contracts, omissions, terminology concepts, hashes, and fingerprints are verified.

The observation adapter deliberately retains only:

| LOINC source | Internal code |
|---|---|
| `8480-6` | `SYSTOLIC_BP` |
| `8462-4` | `DIASTOLIC_BP` |
| `8867-4` | `HEART_RATE` |

Generate and adapt:

```powershell
.\scripts\generate_synthea.ps1
```

See [`docs/synthea.md`](docs/synthea.md).

## Six clinical entities

```text
patients
   └── encounters
          ├── diagnoses
          ├── observations
          ├── medications
          └── procedures
```

| Dataset | Storage policy | Primary identifier |
|---|---|---|
| patients | current snapshot + SCD Type 2 history | `patient_id` |
| encounters | immutable event | `encounter_id` |
| diagnoses | immutable event + terminology binding | `diagnosis_id` |
| observations | immutable event + terminology binding | `observation_id` |
| medications | immutable event + terminology binding | `medication_id` |
| procedures | immutable event + terminology binding | `procedure_id` |

Every event references a patient and encounter. Exact duplicates preserve the original record and lineage. Conflicting identifier reuse rolls back the clinical transaction and leaves a failed execution timeline.

## Minimal terminology layer

V007 provides:

```text
terminology.code_systems
terminology.system_aliases
terminology.concepts
terminology.concept_mappings
terminology.normalized_clinical_codes
```

The local registry contains small subsets of ICD-10-CM, LOINC, RxNorm, ATC, SNOMED CT, CPT, and ICD-10-PCS. It is not a complete terminology server.

Synthea source concepts absent from the curated subset are imported explicitly as `unverified`.

## Execution lifecycle

```text
created
→ raw_captured
→ validating
→ validated
→ loading
→ completed
```

A failed loading attempt remains auditable and may retry:

```text
validated
→ loading       attempt 1
→ failed        attempt 1
→ loading       attempt 2
→ completed     attempt 2
```

Loading uses separate transaction boundaries:

1. Validated-run registration, journal import, and loading acquisition commit.
2. COPY staging, target merge, validation-error COPY, and completion commit atomically.
3. After rollback, failed status is stored in a new transaction.

Completed runs are idempotent: a repeated load returns before staging or row writes.

## Structured logging

The console entrypoint emits operational telemetry to `stderr`; JSON is the default.

```text
CLINICAL_DATA_LOG_LEVEL  = DEBUG | INFO | WARNING | ERROR | CRITICAL
CLINICAL_DATA_LOG_FORMAT = json | text
```

COPY events include:

```text
persistence.copy.started
persistence.copy.completed
persistence.copy.failed
persistence.validation_error_copy.started
persistence.validation_error_copy.completed
persistence.validation_error_copy.failed
```

Clinical rows and identifiers are not intentionally logged. Structured logs are not the durable audit; `audit.pipeline_runs` and `audit.pipeline_run_events` remain authoritative.

## Raw landing zone

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

Identical files share one content object, while each reception has a separate append-only receipt. This is application-level local immutability, not certified WORM storage.

## Executable contracts

```text
contracts/
├── patients/v1.0.0.toml
├── encounters/v1.0.0.toml
├── diagnoses/v1.0.0.toml
├── observations/v1.0.0.toml
├── medications/v1.0.0.toml
└── procedures/v1.0.0.toml
```

The engine executes structural, required-value, uniqueness, type, categorical, temporal, unit, and plausible-range rules. Every validation run records contract path, version, and SHA-256.

## PostgreSQL migrations

```text
V001 core schemas and patients
V002 encounters, diagnoses, observations, cohorts
V003 contract lineage
V004 raw lineage
V005 patient SCD2 and immutable-event policy
V006 medications and procedures
V007 minimal terminology integration
V008 execution lifecycle and durable failure audit
```

COPY loading and benchmarking require no V009 because they add application workflows, temporary tables, and evidence artifacts rather than permanent database objects.

Expected state:

```text
detected=8
current=8
latest=8
pending=[]
```

## Implemented capabilities

- generic contract-governed architecture;
- versioned executable contracts;
- formal PostgreSQL migrations;
- immutable content-addressed raw landing zone;
- patient SCD Type 2 history and immutable events;
- six clinical entities;
- minimal terminology integration;
- complete execution states, retries, and durable failures;
- structured JSON logging;
- reproducible Synthea generation and adaptation;
- PostgreSQL COPY loading with temporary typed staging;
- bounded-memory persistence iteration;
- reproducible correctness-gated benchmark;
- balanced method ordering and empty-database safety guard;
- committed trial-level benchmark evidence;
- versioned hypertension cohort and feature export;
- Docker, Compose, PowerShell, POSIX, Ruff, strict mypy, pytest, PostgreSQL integration, and GitHub Actions.

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

Copy-Item .env.example .env
docker compose up -d postgres
$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"
$env:CLINICAL_DATA_LOG_LEVEL = "INFO"
$env:CLINICAL_DATA_LOG_FORMAT = "json"

clinical-data database-migrate
clinical-data database-validate
clinical-data run-demo --repository-root . 2> data/clinical-data.jsonl
```

## Expected bundled sample

| Dataset | Received | Valid | Invalid | Persisted |
|---|---:|---:|---:|---:|
| Patients | 8 | 5 | 3 | 5 |
| Encounters | 8 | 7 | 1 | 7 |
| Diagnoses | 7 | 6 | 1 | 6 |
| Observations | 14 | 13 | 1 | 13 |
| Medications | 7 | 6 | 1 | 6 |
| Procedures | 7 | 6 | 1 | 6 |

The clean bundled demo produces six completed runs, 31 normalized terminology bindings, and a hypertension cohort containing `P001` and `P002`.

## Quality checks

```bash
clinical-data synthea-profile
clinical-data validate-contracts
clinical-data database-migrate
clinical-data database-validate
clinical-data-benchmark \
  --allow-destructive-reset \
  --patients 8 \
  --repetitions 2 \
  --warmups 0 \
  --output-dir /tmp/benchmark
python -m ruff check .
python -m mypy src
python -m pytest --cov=clinical_data_platform --cov-report=term-missing
docker build --tag clinical-data-platform:local .
```

Normal CI runs a small benchmark integration test. The dedicated Benchmark workflow runs the larger documented profile and uploads JSON, CSV, and Markdown evidence.

## Documentation

- [`docs/loading-benchmark.md`](docs/loading-benchmark.md): protocol, evidence, results, and limits;
- [`docs/bulk-loading.md`](docs/bulk-loading.md): COPY, staging, merge, and transactions;
- [`docs/synthea.md`](docs/synthea.md): generation, adaptation, and verification;
- [`docs/architecture.md`](docs/architecture.md): architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/execution-audit.md`](docs/execution-audit.md): lifecycle and failure evidence;
- [`docs/structured-logging.md`](docs/structured-logging.md): logging schema and redaction;
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md): SCD2 and immutable events;
- [`docs/clinical-entities.md`](docs/clinical-entities.md): six-entity model;
- [`docs/terminology.md`](docs/terminology.md): terminology model and licensing boundary;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): repository review sequence;
- [`docs/learning/benchmark-carga-postgresql-es.md`](docs/learning/benchmark-carga-postgresql-es.md): Spanish benchmark guide;
- [`docs/learning/postgresql-copy-es.md`](docs/learning/postgresql-copy-es.md): Spanish COPY guide;
- [`docs/learning/reproducible-synthea-es.md`](docs/learning/reproducible-synthea-es.md): Spanish Synthea guide.

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- a second reproducible cohort;
- attrition and missingness reports;
- coverage of at least 90%;
- multi-version Python CI;
- dependency and security scanning;
- non-root container hardening;
- final documentation and release `1.0.0`.

The benchmark measures initial single-writer loading, not end-to-end latency, updates, concurrency, remote databases, WAL volume, or peak memory. Contract validation still materializes the complete source dataset. The full Synthea generator is not executed in normal CI. The logging layer has no centralized transport or OpenTelemetry.

## License

MIT License. See [`LICENSE`](LICENSE).
