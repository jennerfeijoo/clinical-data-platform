# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.7.0` adds an explicit hybrid clinical-history policy.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates how healthcare-like source files can become auditable, analysis-ready datasets.

The repository uses only synthetic data. It is intended for engineering review and learning, not for identifiable patient data, clinical decisions, or production healthcare deployment.

## Architecture

```text
External CSV source
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
Generic validation pipeline
        ├── valid rows
        ├── quarantined rows
        ├── normalized errors
        └── quality report
        │
        ▼
Formal PostgreSQL migrations
        │
        ▼
Hybrid clinical persistence
        ├── patient current snapshot + SCD2 history
        └── immutable clinical events
        │
        ▼
Versioned cohort SQL and feature export
```

There is no patient-specific validation pipeline and no monolithic schema installer.

## Clinical history policy

The persistence model is explicit rather than relying on generic destructive upserts.

| Dataset | Policy | Behavior |
|---|---|---|
| patients | SCD Type 2 snapshot | current state in `clinical.patients`; business changes append versions to `clinical.patient_history` |
| encounters | immutable event | exact duplicate is a no-op; same ID with different content is rejected |
| diagnoses | immutable event | exact duplicate is a no-op; same ID with different content is rejected |
| observations | immutable event | exact duplicate is a no-op; same ID with different content is rejected |

Every current clinical row has a `record_sha256` calculated from normalized business content. Lineage fields are excluded so that re-receiving the same clinical content does not create a false historical change.

Patient changes close the previous history version and append a new current version. Immutable-event conflicts raise a PostgreSQL integrity error and roll back the complete dataset load, including its pending audit row.

The policy is declared in `src/clinical_data_platform/history.py` and enforced by migration V005.

## Immutable raw landing zone

Sources are captured before parsing under:

```text
data/raw/
├── objects/
│   └── sha256/<prefix>/<sha256>/source.csv
└── receipts/
    └── <dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

The object path is derived from the file bytes. Identical files share one object, while every receipt event receives its own append-only manifest.

The landing implementation provides:

- SHA-256 and byte-size verification;
- content-based deduplication;
- staging plus atomic publication;
- no replacement of existing final paths;
- local read-only permissions;
- receipt and object integrity verification;
- path traversal protection;
- validation from the captured raw object rather than the external source;
- PostgreSQL lineage for the raw receipt and object.

Local read-only permissions are not equivalent to certified WORM storage. The project does not claim protection from administrators, regulatory retention, object-store durability, or production PHI controls.

## Executable contracts

Active contract versions are selected by:

```text
src/clinical_data_platform/contracts/manifest.toml
```

Published contracts are retained:

```text
src/clinical_data_platform/contracts/
├── patients/v1.0.0.toml
├── encounters/v1.0.0.toml
├── diagnoses/v1.0.0.toml
└── observations/v1.0.0.toml
```

The contract engine executes structural, required-value, uniqueness, type, vocabulary, temporal, unit, and plausible-range rules. Every validation run records contract path, semantic version, and SHA-256.

## PostgreSQL migrations

The database is created and upgraded through immutable packaged migrations:

```text
src/clinical_data_platform/migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
├── V003__add_contract_lineage.sql
├── V004__add_raw_landing_lineage.sql
└── V005__add_clinical_history_policy.sql
```

Migration history is stored in `public.schema_migrations`. The engine verifies contiguous ordering, names, checksums, current structure, and pending versions. Migrations execute transactionally under a PostgreSQL advisory lock.

## Implemented capabilities

- generic contract-governed validation for all datasets;
- active contract manifest and retained contract versions;
- immutable content-addressed raw capture and append-only receipts;
- normalized validation errors and rejected-record quarantine;
- source, raw, contract, run, record, and cohort lineage;
- formal PostgreSQL migrations with install, upgrade, baseline, and drift tests;
- patients, encounters, diagnoses, and observations;
- current patient snapshot plus SCD Type 2 patient history;
- immutable encounter, diagnosis, and observation semantics;
- transactional and run-idempotent persistence;
- referential integrity and database constraints;
- versioned hypertension cohort and baseline features;
- Docker, Docker Compose, PowerShell, and POSIX workflows;
- Ruff, strict mypy, pytest, coverage, PostgreSQL integration tests, and GitHub Actions.

## Fastest complete run

Requirements: Git and Docker with Docker Compose.

```bash
git clone https://github.com/jennerfeijoo/clinical-data-platform.git
cd clinical-data-platform
```

PowerShell:

```powershell
.\scripts\run_demo.ps1
```

POSIX shell:

```bash
sh scripts/run_demo.sh
```

The demo creates or reuses raw objects, writes new receipt manifests, migrates PostgreSQL, validates and loads all datasets, builds the cohort, and writes:

```text
data/raw/
data/processed/
data/analytics/
```

## Local Python development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

Copy-Item .env.example .env
docker compose up -d postgres
$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"
```

Apply and validate migrations:

```powershell
clinical-data database-migrate
clinical-data database-validate
```

Run the complete workflow:

```powershell
clinical-data run-demo --repository-root .
```

## Raw commands

Capture one source independently:

```powershell
clinical-data raw-capture patients data/sample/patients.csv `
  --raw-root data/raw
```

Verify a receipt using its path relative to `data/raw`:

```powershell
clinical-data raw-verify `
  receipts/patients/2026/07/29/<receipt-uuid>.json `
  --raw-root data/raw
```

Validation captures automatically and then reads the captured object:

```powershell
clinical-data validate-dataset patients data/sample/patients.csv `
  --raw-root data/raw `
  --output-dir data/processed/patients `
  --reference-date 2026-07-29
```

Persistence verifies the raw receipt and object before opening the write transaction:

```powershell
clinical-data load-dataset patients `
  --raw-root data/raw `
  --output-dir data/processed/patients
```

## Main CLI

```text
clinical-data list-contracts
clinical-data show-contract
clinical-data validate-contracts
clinical-data raw-capture
clinical-data raw-verify
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
clinical-data validate-dataset
clinical-data load-dataset
clinical-data build-hypertension-cohort
clinical-data run-demo
```

## Expected bundled sample

| Dataset | Received | Valid | Invalid | Errors | Contract |
|---|---:|---:|---:|---:|---:|
| Patients | 8 | 5 | 3 | 3 | 1.0.0 |
| Encounters | 8 | 7 | 1 | 1 | 1.0.0 |
| Diagnoses | 7 | 6 | 1 | 2 | 1.0.0 |
| Observations | 14 | 13 | 1 | 1 | 1.0.0 |

The default hypertension cohort contains `P001` and `P002`.

## Inspect clinical history

Current snapshots:

```sql
SELECT
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    record_sha256,
    source_run_id
FROM clinical.patients
ORDER BY patient_id;
```

Patient history:

```sql
SELECT
    patient_id,
    sex_at_birth,
    death_date,
    valid_from_run_id,
    valid_to_run_id,
    valid_from,
    valid_to,
    is_current,
    record_sha256
FROM clinical.patient_history
ORDER BY patient_id, patient_version_id;
```

Immutable events retain their original accepted lineage:

```sql
SELECT
    encounter_id,
    patient_id,
    record_sha256,
    source_run_id,
    loaded_at
FROM clinical.encounters
ORDER BY encounter_id;
```

## Lineage recorded per run

`quality_report.json` contains:

```text
run_id
input_path
input_sha256
raw_storage_version
raw_receipt_id
raw_received_at
raw_manifest_path
raw_manifest_sha256
raw_object_path
raw_size_bytes
contract_path
contract_version
contract_sha256
reference_date
row counts and rule counts
```

`audit.pipeline_runs` persists the same raw and contract lineage. Clinical tables add `record_sha256`, and patient history records the runs that opened and closed each version.

## Quality checks

```bash
clinical-data validate-contracts
clinical-data database-migrate
clinical-data database-validate
python -m ruff check .
python -m mypy src
python -m pytest --cov=clinical_data_platform --cov-report=term-missing
docker build --tag clinical-data-platform:local .
```

CI exercises migrations, raw capture, contract validation, history semantics, immutable-event conflict rollback, and container smoke tests.

## Documentation

- [`docs/architecture.md`](docs/architecture.md): system architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md): operational history policy;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): technical review sequence and SQL;
- [`docs/learning/generic-dataset-architecture-es.md`](docs/learning/generic-dataset-architecture-es.md);
- [`docs/learning/versioned-executable-contracts-es.md`](docs/learning/versioned-executable-contracts-es.md);
- [`docs/learning/database-migrations-es.md`](docs/learning/database-migrations-es.md);
- [`docs/learning/immutable-raw-landing-zone-es.md`](docs/learning/immutable-raw-landing-zone-es.md);
- [`docs/learning/clinical-history-policy-es.md`](docs/learning/clinical-history-policy-es.md);
- [`docs/hypertension-cohort.md`](docs/hypertension-cohort.md).

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- medications and procedures as the fifth and sixth clinical entities;
- terminology normalization;
- complete execution states and structured logging;
- reproducible Synthea datasets;
- bulk PostgreSQL `COPY` loading and benchmarks;
- an additional cohort with attrition and missingness reporting;
- stronger coverage, multi-version CI, security, container, and release hardening.

The history policy does not yet model tombstones, bitemporal valid time, formal correction messages, patient identity merges, or event supersession.

It intentionally excludes identifiable patient data, production decision support, enterprise authentication, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
