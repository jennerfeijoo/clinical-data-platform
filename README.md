# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.12.0` adds a reproducible Synthea generation and adaptation workflow.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates how healthcare-like source files become auditable, analysis-ready, terminology-linked datasets.

The repository uses only synthetic data. It is intended for engineering review and learning, not for identifiable patient data, clinical decisions, epidemiological inference, or production healthcare deployment.

## Architecture

```text
Pinned Synthea profile or external CSV source
            │
            ├── upstream release, commit, seeds, date, geography
            ├── source schema and SHA-256 manifest
            └── deterministic six-entity adapter
            │
            ▼
CLI command
    ├── structured JSON logs to stderr
    └── correlation_id propagated through the workflow
            │
            ▼
Immutable raw capture
    ├── SHA-256 content object
    └── append-only receipt manifest
            │
            ▼
Versioned executable TOML contract
            │
            ▼
Hash-chained local execution journal
            │
            ▼
Generic validation pipeline
    ├── valid rows
    ├── quarantined rows
    ├── normalized errors
    └── quality report: validated
            │
            ▼
Formal PostgreSQL migrations V001–V008
            │
            ▼
Durable execution audit
    ├── current run state
    ├── ordered event timeline
    └── failures retained after clinical rollback
            │
            ▼
Terminology resolution and clinical persistence
            │
            ▼
Versioned cohort SQL and feature export
```

There is no patient-specific pipeline, no Synthea-specific persistence path, and no monolithic schema installer.

## Reproducible Synthea dataset

The packaged profile is:

```text
src/clinical_data_platform/synthea_profiles/reproducible_small.toml
```

It pins:

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

It also creates `terminology.csv` and `synthea-adaptation-manifest.json`. Missing source-event identifiers are generated deterministically with UUIDv5. Parent relationships, exact source headers, output contracts, omitted-row counts, terminology concepts, hashes, and fingerprints are verified.

The current observation adapter deliberately retains only:

| LOINC source | Internal code |
|---|---|
| 8480-6 | `SYSTOLIC_BP` |
| 8462-4 | `DIASTOLIC_BP` |
| 8867-4 | `HEART_RATE` |

Other observations are counted as outside the supported subset rather than silently coerced.

Inspect the profile:

```powershell
clinical-data synthea-profile
```

Generate and adapt:

```powershell
.\scripts\generate_synthea.ps1
```

Load the adapted population through the existing platform controls:

```powershell
clinical-data synthea-load `
  data/synthea/synthea-us-small-v1/normalized `
  --processed-root data/processed/synthea `
  --raw-root data/raw
```

See [`docs/synthea.md`](docs/synthea.md).

## Structured application logging

The console entrypoint emits operational telemetry to `stderr`. JSON is the default representation.

```json
{
  "schema_version": "1.0.0",
  "timestamp": "2026-07-29T12:45:01.123Z",
  "level": "info",
  "event": "pipeline.validation.completed",
  "component": "pipeline",
  "message": "Completed validate_records_against_contract.",
  "correlation_id": "3b86c4bd-9e79-4fa9-a31a-59b31a4bb5ef",
  "run_id": "6aa89516-f724-4dc9-b259-510abc11075a",
  "dataset": "patients",
  "operation": "validate_records_against_contract",
  "outcome": "success",
  "duration_ms": 4
}
```

Configuration:

```text
CLINICAL_DATA_LOG_LEVEL  = DEBUG | INFO | WARNING | ERROR | CRITICAL
CLINICAL_DATA_LOG_FORMAT = json | text
```

Logs record operations, stages, outcomes, durations, aggregate counts, exception types, and SQLSTATE codes. Defensive sanitization removes clinical identifiers, rejected values, credentials, database URLs, PostgreSQL key values, and DETAIL lines.

Structured logs are not the durable audit. `audit.pipeline_runs` and `audit.pipeline_run_events` remain authoritative for execution state and loading attempts.

See [`docs/structured-logging.md`](docs/structured-logging.md).

## Complete execution lifecycle

```text
created
→ raw_captured
→ validating
→ validated
→ loading
→ completed
```

A failed loading attempt remains auditable and can retry:

```text
validated
→ loading       attempt 1
→ failed        attempt 1
→ loading       attempt 2
→ completed     attempt 2
```

Loading uses separate transaction boundaries:

1. validated run registration, journal import, and loading acquisition commit;
2. clinical rows, validation errors, and completed commit atomically;
3. after a clinical rollback, failed is stored in a new transaction.

This preserves both:

```text
no partial clinical data
+ durable evidence of failed attempts
```

See [`docs/execution-audit.md`](docs/execution-audit.md).

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

Every event references a patient and encounter. Exact duplicates preserve the original row and lineage. Conflicting identifier reuse rolls back the clinical transaction and leaves a failed execution timeline.

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

The Synthea adapter writes source concepts used by the generated population. Concepts absent from the curated subset are imported explicitly as `unverified`, not presented as independently verified terminology content.

## Immutable raw landing zone

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

Identical files share one content object, while each reception has a separate append-only receipt. The implementation verifies checksums, byte sizes, paths, and manifest lineage before persistence.

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

Synthea and structured logging do not require new database migrations because they add application workflows and output artifacts rather than persistent schema state.

## Implemented capabilities

- reproducible Synthea profile with pinned release, seeds, reference date, geography, and single-thread generation;
- generation and adaptation manifests with SHA-256 fingerprints;
- deterministic Synthea-to-contract adapter and UUIDv5 event identities;
- six contract-governed clinical datasets;
- structured JSON logging and correlation context;
- explicit run lifecycle, retries, and durable failure metadata;
- hash-chained local validation journals;
- minimal terminology registry and normalized concepts;
- immutable content-addressed raw capture;
- patient SCD Type 2 history and immutable clinical events;
- transactional, run-idempotent PostgreSQL persistence;
- versioned hypertension cohort and feature export;
- Docker, Compose, PowerShell, POSIX, Ruff, strict mypy, pytest, coverage, PostgreSQL integration, and GitHub Actions.

## Fastest bundled demo

Requirements: Git and Docker with Docker Compose.

```powershell
.\scripts\run_demo.ps1
```

The bundled demo uses the small checked-in project sample. The Synthea generation workflow is separate because it requires Java 17+, Git, upstream cloning, and generation time.

## Local Python development

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
clinical-data run-demo --repository-root .
```

Current migration state:

```text
detected=8
current=8
latest=8
pending=[]
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
clinical-data synthea-adapt tests/fixtures/synthea/csv --output-dir /tmp/synthea-normalized
clinical-data synthea-verify /tmp/synthea-normalized
clinical-data validate-contracts
clinical-data database-migrate
clinical-data database-validate
python -m ruff check .
python -m mypy src
python -m pytest --cov=clinical_data_platform --cov-report=term-missing
docker build --tag clinical-data-platform:local .
```

Normal CI validates the installed profile, exact Synthea CSV schema, deterministic adapter, manifest verification, terminology import, all existing platform controls, and PostgreSQL loading. It does not execute the full upstream Java generator.

## Documentation

- [`docs/synthea.md`](docs/synthea.md): generation, manifests, adapter, verification, and loading;
- [`docs/architecture.md`](docs/architecture.md): system architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/execution-audit.md`](docs/execution-audit.md): lifecycle, transactions, retries, and inspection;
- [`docs/structured-logging.md`](docs/structured-logging.md): logging schema and redaction;
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md): snapshot and immutable-event policy;
- [`docs/clinical-entities.md`](docs/clinical-entities.md): six-entity model;
- [`docs/terminology.md`](docs/terminology.md): terminology model and licensing boundary;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): repository review sequence;
- [`docs/learning/reproducible-synthea-es.md`](docs/learning/reproducible-synthea-es.md): Spanish Synthea reproducibility guide;
- additional learning guides under [`docs/learning/`](docs/learning/).

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- bulk PostgreSQL `COPY` loading;
- a documented benchmark using a larger generated population;
- an additional cohort with attrition and missingness reporting;
- coverage of at least 90%;
- multi-version CI, security, container, and release hardening.

The full Synthea generator is not executed in normal CI. The current adapter supports only six CSV files and three observation concepts. Newly discovered source concepts are retained as unverified. The logging layer has no centralized transport or OpenTelemetry. The project excludes identifiable patient data, production decision support, epidemiological validity claims, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
