# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.15.0` adds a second independently seeded, reproducible Synthea cohort with identifier-disjoint comparison and pair loading.

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

## Two reproducible Synthea cohorts

Version `0.15.0` packages two matched-design Synthea profiles:

| Control | Cohort A | Cohort B |
|---|---|---|
| Profile | `synthea-us-small-v1` | `synthea-us-small-cohort-b-v1` |
| Synthea release | `v4.0.0` | `v4.0.0` |
| Population | 100 | 100 |
| Random seed | `20260729` | `20260829` |
| Clinician seed | `20260730` | `20260830` |
| Reference date | `2026-07-29` | `2026-07-29` |
| Geography | Massachusetts | Massachusetts |
| Threads | 1 | 1 |
| Retained history | complete | complete |

The two profiles deliberately keep software version, geography, date, size, export scope, thread count, and retained history fixed. Only the patient and clinician seeds change. Cohort B is therefore an independent stochastic replica under the same controlled design.

Each cohort independently records and verifies:

```text
profile SHA-256
resolved Synthea commit
exact generation command
six source CSV hashes and row counts
source dataset fingerprint
seven adapted output hashes
adaptation fingerprint
contract validity
explicit omission counts
terminology concept count
```

The pair comparison additionally requires:

```text
distinct profile hashes
AND distinct random seeds
AND distinct clinician seeds
AND distinct adaptation fingerprints
AND zero overlap in:
    patient_id
    encounter_id
    diagnosis_id
    observation_id
    medication_id
    procedure_id
```

A stable comparison fingerprint covers the controlled design, both profile identities, both adaptation fingerprints, row counts, omission counts, terminology counts, identifier counts, identifier-set fingerprints, and overlap counts. It excludes timestamps, absolute paths, and PostgreSQL run UUIDs.

Generate and verify both cohorts:

```powershell
.\scripts\generate_synthea_cohorts.ps1
```

Load both through the governed pipeline:

```powershell
.\scripts\load_synthea_cohorts.ps1 -ReplaceComparison
```

Direct comparison:

```powershell
clinical-data-cohort compare `
  data/synthea/synthea-us-small-v1/normalized `
  data/synthea/synthea-us-small-cohort-b-v1/normalized `
  --output-dir data/synthea/cohort-comparison
```

A complete pair load creates twelve separate completed pipeline runs:

```text
6 datasets × 2 cohorts = 12 run_ids
```

Before loading, the pair loader checks the target database for identifiers belonging to either cohort. Any collision causes refusal before new validation or persistence runs are created.

Technical protocol: [`docs/synthea-cohorts.md`](docs/synthea-cohorts.md).

Spanish study guide: [`docs/learning/segunda-cohorte-synthea-es.md`](docs/learning/segunda-cohorte-synthea-es.md).

## Reproducible Synthea adaptation

Synthea exports are adapted as follows:

```text
Synthea patients.csv      → patients.csv
Synthea encounters.csv    → encounters.csv
Synthea conditions.csv    → diagnoses.csv
Synthea observations.csv  → observations.csv
Synthea medications.csv   → medications.csv
Synthea procedures.csv    → procedures.csv
```

The adapter also writes `terminology.csv` and `synthea-adaptation-manifest.json`. Missing source-event identifiers use deterministic UUIDv5 values. Parent relationships, exact source headers, executable contracts, omissions, terminology concepts, hashes, and fingerprints are verified.

The observation adapter intentionally retains only:

| LOINC source | Internal code |
|---|---|
| `8480-6` | `SYSTOLIC_BP` |
| `8462-4` | `DIASTOLIC_BP` |
| `8867-4` | `HEART_RATE` |

Other observations are explicitly counted as omitted rather than silently forced into the narrow contract.

See [`docs/synthea.md`](docs/synthea.md).

## Governed PostgreSQL loading benchmark

The benchmark compares:

```text
current route
record iterator
→ COPY FROM STDIN
→ temporary typed staging
→ set-based INSERT ... SELECT ... ON CONFLICT
```

with:

```text
former reference
record iterator
→ psycopg executemany
→ equivalent INSERT ... ON CONFLICT
```

Both routes write to the same migrated tables with terminology triggers, record hashes, patient SCD Type 2 history, immutable-event guards, indexes, constraints, lineage foreign keys, WAL durability settings, and transaction commits active.

### Balanced reference protocol

| Control | Value |
|---|---|
| Data | deterministic six-entity synthetic workload |
| Seed | `20260729` |
| Reference date | `2026-07-29` |
| Patient sizes | 250, 1,000, 2,500 |
| Clinical rows | 3,750, 15,000, 37,500 |
| Warm-ups | 1 per method and size |
| Measured repetitions | 6 per method and size |
| Starting-position balance | COPY first 3 times; `executemany` first 3 times |
| Writer concurrency | 1 |

Every trial must pass exact row-count, history, terminology-binding, record-hash, and database-content fingerprint checks before its timing is accepted.

GitHub Actions workflow run `30470147850` produced:

| Patients | Rows | COPY median | `executemany` median | COPY speedup | Time reduction |
|---:|---:|---:|---:|---:|---:|
| 250 | 3,750 | 825.694 ms | 1,083.028 ms | 1.312× | 23.76% |
| 1,000 | 15,000 | 3,183.671 ms | 4,341.867 ms | 1.364× | 26.68% |
| 2,500 | 37,500 | 7,936.444 ms | 10,955.541 ms | 1.380× | 27.56% |

This supports a limited engineering statement: on the recorded hosted-runner environment, COPY reduced median governed initial-load time by approximately **23.8–27.6%** relative to the former `executemany` path.

It does not establish complete-pipeline speed, production capacity, concurrent performance, remote-database behavior, or hospital-scale throughput.

Permanent evidence:

```text
benchmarks/loading/github-actions-run-30470147850/
├── benchmark-summary.md
├── benchmark-trials.csv
└── reference-run.json
```

Technical protocol: [`docs/loading-benchmark.md`](docs/loading-benchmark.md).

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

Completed runs are idempotent. The two-cohort orchestration is stricter: it rejects a pair when any of its identifiers already exists in the target database.

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

## Minimal terminology layer

```text
terminology.code_systems
terminology.system_aliases
terminology.concepts
terminology.concept_mappings
terminology.normalized_clinical_codes
```

The local registry contains small subsets of ICD-10-CM, LOINC, RxNorm, ATC, SNOMED CT, CPT, and ICD-10-PCS. It is not a complete terminology server. Synthea concepts absent from the curated subset are imported explicitly as `unverified`.

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

The second cohort requires no V009 because it adds packaged generation profiles, application orchestration, comparison evidence, and existing pipeline runs rather than permanent database objects.

Expected state:

```text
detected=8
current=8
latest=8
pending=[]
```

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

## Quality checks

```bash
clinical-data validate-contracts
clinical-data database-migrate
clinical-data database-validate
clinical-data-cohort list-profiles
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

Normal CI uses small fixtures for both Synthea cohorts and for the benchmark. The full Java Synthea generator and the larger benchmark profile remain separate from ordinary CI.

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
- reproducible Synthea generation and deterministic adaptation;
- two matched-design independently seeded Synthea profiles;
- identifier-disjoint cohort comparison and stable pair fingerprint;
- separate two-cohort processing and run lineage;
- PostgreSQL COPY loading with temporary typed staging;
- bounded-memory persistence iteration;
- reproducible correctness-gated loading benchmark;
- versioned hypertension cohort and feature export;
- Docker, Compose, PowerShell, POSIX, Ruff, strict mypy, pytest, PostgreSQL integration, and GitHub Actions.

## Documentation

- [`docs/synthea-cohorts.md`](docs/synthea-cohorts.md): two-cohort protocol and boundaries;
- [`docs/synthea.md`](docs/synthea.md): Synthea generation and adaptation;
- [`docs/loading-benchmark.md`](docs/loading-benchmark.md): benchmark protocol and evidence;
- [`docs/bulk-loading.md`](docs/bulk-loading.md): COPY, staging, merge, and transactions;
- [`docs/architecture.md`](docs/architecture.md): architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/execution-audit.md`](docs/execution-audit.md): lifecycle and failure evidence;
- [`docs/structured-logging.md`](docs/structured-logging.md): logging schema and redaction;
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md): SCD2 and immutable events;
- [`docs/clinical-entities.md`](docs/clinical-entities.md): six-entity model;
- [`docs/terminology.md`](docs/terminology.md): terminology model and licensing boundary;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): repository review sequence;
- [`docs/learning/segunda-cohorte-synthea-es.md`](docs/learning/segunda-cohorte-synthea-es.md): Spanish second-cohort guide;
- [`docs/learning/benchmark-carga-postgresql-es.md`](docs/learning/benchmark-carga-postgresql-es.md): Spanish benchmark guide;
- [`docs/learning/postgresql-copy-es.md`](docs/learning/postgresql-copy-es.md): Spanish COPY guide;
- [`docs/learning/reproducible-synthea-es.md`](docs/learning/reproducible-synthea-es.md): Spanish Synthea guide.

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- attrition and missingness reports;
- coverage of at least 90%;
- multi-version Python CI;
- dependency and security scanning;
- non-root container hardening;
- final documentation and release `1.0.0`.

The two-cohort load is not one global transaction: each dataset retains its existing durable transaction boundaries. Contract validation still materializes the complete source dataset. The full Synthea generator is not executed in normal CI. The benchmark measures initial single-writer loading, not end-to-end latency, updates, concurrency, remote databases, WAL volume, or peak memory. The logging layer has no centralized transport or OpenTelemetry.

## License

MIT License. See [`LICENSE`](LICENSE).
