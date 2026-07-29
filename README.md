# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.13.0` adds PostgreSQL `COPY` bulk loading with temporary staging and governed set-based merges.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates how healthcare-like source files become auditable, analysis-ready, terminology-linked datasets.

The repository uses only synthetic data. It is intended for engineering review and learning, not for identifiable patient data, clinical decisions, epidemiological inference, or production healthcare deployment.

## Architecture

```text
Pinned Synthea profile or external CSV source
            │
            ├── release, commit, seeds, date, geography
            ├── source schema and SHA-256 manifest
            └── deterministic six-entity adapter
            │
            ▼
Immutable raw capture
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
    ├── normalized errors
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
            ├── terminology triggers
            ├── record hashes
            ├── patient SCD Type 2 history
            ├── immutable-event guards
            ├── foreign keys and checks
            └── source-run lineage
            │
            ▼
Versioned cohort SQL and feature export
```

Structured JSON logs observe each operation, while PostgreSQL stores the authoritative execution state and failure timeline.

There is no patient-specific pipeline, no Synthea-specific persistence path, no permanent staging schema, and no monolithic schema installer.

## PostgreSQL COPY loading

Validated outputs are inspected and counted without retaining a persistence batch in memory. They are then reopened as streaming iterators, converted to typed Python values one row at a time, and transmitted using psycopg `COPY FROM STDIN`.

Clinical rows follow:

```text
valid_<dataset>.csv
→ streaming iterator
→ COPY to temporary table
→ set-based target merge
→ target triggers and constraints
```

COPY does not write directly to the governed target because direct COPY cannot express the required `ON CONFLICT` policies. Temporary staging separates efficient transfer from clinical reconciliation.

Each staging table:

```text
has PostgreSQL target column types
has a unique session-local name
uses ON COMMIT DROP
has no copied indexes, constraints, or triggers
```

The subsequent target merge keeps all target controls active. This preserves:

```text
patients
→ current snapshot + SCD Type 2 history

events
→ exact duplicate tolerance + conflicting identity rejection

coded entities
→ terminology resolution

all entities
→ foreign keys, checks, lineage, audit, rollback, and retries
```

Validation errors are also loaded with COPY inside the same clinical transaction. A COPY, merge, terminology, history, or constraint failure rolls back the clinical work and is stored as a durable failed attempt in a separate transaction.

This milestone proves that the platform uses a correct bulk-loading route. It does not yet claim a measured performance improvement; the documented benchmark is the next roadmap milestone.

See [`docs/bulk-loading.md`](docs/bulk-loading.md).

## Reproducible Synthea dataset

The packaged profile is:

```text
src/clinical_data_platform/synthea_profiles/reproducible_small.toml
```

| Control | Value |
|---|---|
| Synthea release | `v4.0.0` |
| population | 100 |
| random seed | 20260729 |
| clinician seed | 20260730 |
| reference date | 2026-07-29 |
| geography | Massachusetts |
| threads | 1 |
| retained history | complete |
| export | six CSV files |

Generation records the resolved upstream commit, Java version, normalized command, exact headers, row counts, byte sizes, per-file SHA-256 values, and a dataset fingerprint.

The adapter converts:

```text
Synthea patients.csv      → patients.csv
Synthea encounters.csv    → encounters.csv
Synthea conditions.csv    → diagnoses.csv
Synthea observations.csv  → observations.csv
Synthea medications.csv   → medications.csv
Synthea procedures.csv    → procedures.csv
```

It also creates `terminology.csv` and `synthea-adaptation-manifest.json`. Missing source-event identifiers use deterministic UUIDv5 values. Parent relationships, exact source headers, output contracts, omitted-row counts, terminology concepts, hashes, and fingerprints are verified.

The observation adapter deliberately retains only:

| LOINC source | Internal code |
|---|---|
| `8480-6` | `SYSTOLIC_BP` |
| `8462-4` | `DIASTOLIC_BP` |
| `8867-4` | `HEART_RATE` |

Other observations are counted as outside the supported subset rather than silently coerced.

Generate and adapt:

```powershell
.\scripts\generate_synthea.ps1
```

Load the normalized population through the same COPY persistence route:

```powershell
clinical-data synthea-load `
  data/synthea/synthea-us-small-v1/normalized `
  --processed-root data/processed/synthea `
  --raw-root data/raw
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

Synthea source concepts absent from the curated subset are imported explicitly as `unverified`, not presented as independently verified terminology content.

## Complete execution lifecycle

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

1. validated run registration, local-journal import, and loading acquisition commit;
2. COPY staging, target merge, validation-error COPY, and completion commit atomically;
3. after rollback, failed is stored in a new transaction.

This preserves:

```text
no partial clinical data
+ durable evidence of failed attempts
```

Completed runs are idempotent: a repeated load returns before creating staging or writing rows.

## Structured application logging

The console entrypoint emits operational telemetry to `stderr`. JSON is the default representation.

```text
CLINICAL_DATA_LOG_LEVEL  = DEBUG | INFO | WARNING | ERROR | CRITICAL
CLINICAL_DATA_LOG_FORMAT = json | text
```

COPY-specific events include:

```text
persistence.copy.started
persistence.copy.completed
persistence.copy.failed
persistence.validation_error_copy.started
persistence.validation_error_copy.completed
persistence.validation_error_copy.failed
```

Aggregate fields include `rows_copied`, `rows_merged`, `duration_ms`, `attempt_number`, and `loading_method=postgresql_copy`. Clinical rows are not intentionally logged.

Structured logs are not the durable audit. `audit.pipeline_runs` and `audit.pipeline_run_events` remain authoritative.

## Immutable raw landing zone

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

Identical files share one content object, while each reception has a separate append-only receipt. Checksums, byte sizes, paths, and manifest lineage are verified before persistence.

This is application-level local immutability, not certified WORM storage.

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

COPY loading does not require V009 because staging tables are temporary and no permanent database object changes.

Current migration state remains:

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
- six complete clinical entities;
- minimal terminology integration;
- complete execution states, retries, and durable failures;
- structured JSON logging and correlation context;
- reproducible Synthea generation and deterministic adaptation;
- PostgreSQL COPY loading with temporary typed staging;
- set-based target reconciliation with triggers preserved;
- bounded-memory persistence iteration;
- versioned hypertension cohort and feature export;
- Docker, Compose, PowerShell, POSIX, Ruff, strict mypy, pytest, PostgreSQL integration, and GitHub Actions.

## Fastest bundled demo

Requirements: Git and Docker with Docker Compose.

```powershell
.\scripts\run_demo.ps1
```

The bundled demo uses the small checked-in project sample. The full Synthea workflow is separate because it requires Java 17+, Git, upstream cloning, and generation time.

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

Inspect COPY events:

```powershell
Select-String -Path data/clinical-data.jsonl -Pattern 'persistence.copy'
```

Verify that temporary staging tables do not remain after commit:

```sql
SELECT schemaname, tablename
FROM pg_catalog.pg_tables
WHERE tablename LIKE '_cdp_%';
```

Expected after a completed transaction: zero rows.

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
python -m ruff check .
python -m mypy src
python -m pytest --cov=clinical_data_platform --cov-report=term-missing
docker build --tag clinical-data-platform:local .
```

Normal CI validates COPY staging and merge behavior, streaming CSV inspection, all six entities, terminology, history, immutable conflicts, retries, failure rollback, contracts, migrations, raw capture, Synthea adaptation, Docker, and container smoke tests.

## Documentation

- [`docs/bulk-loading.md`](docs/bulk-loading.md): COPY, staging, merge, transactions, and limitations;
- [`docs/synthea.md`](docs/synthea.md): generation, manifests, adapter, verification, and loading;
- [`docs/architecture.md`](docs/architecture.md): system architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/execution-audit.md`](docs/execution-audit.md): lifecycle, retries, and failure evidence;
- [`docs/structured-logging.md`](docs/structured-logging.md): logging schema and redaction;
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md): snapshot and immutable-event policy;
- [`docs/clinical-entities.md`](docs/clinical-entities.md): six-entity model;
- [`docs/terminology.md`](docs/terminology.md): terminology model and licensing boundary;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): repository review sequence;
- [`docs/learning/postgresql-copy-es.md`](docs/learning/postgresql-copy-es.md): guía de estudio en español;
- [`docs/learning/reproducible-synthea-es.md`](docs/learning/reproducible-synthea-es.md): guía de reproducibilidad Synthea.

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- a documented performance benchmark using larger reproducible populations;
- an additional reproducible cohort;
- attrition and missingness reports;
- coverage of at least 90%;
- multi-version Python CI;
- dependency and security scanning;
- non-root container hardening;
- final documentation and release `1.0.0`.

COPY currently uses psycopg row adaptation rather than binary COPY. Contract validation still materializes the complete source dataset. The full Synthea generator is not executed in normal CI. The adapter supports six CSV files and three observation concepts. The logging layer has no centralized transport or OpenTelemetry. The project excludes identifiable patient data, production decision support, epidemiological validity claims, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
