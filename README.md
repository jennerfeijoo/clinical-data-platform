# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.6.0` adds an immutable, content-addressed raw landing zone.

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
Generic transactional persistence
        │
        ▼
Versioned cohort SQL and feature export
```

There is no patient-specific pipeline and no monolithic schema installer.

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
└── V004__add_raw_landing_lineage.sql
```

Migration history is stored in `public.schema_migrations`. The engine verifies contiguous ordering, names, checksums, current structure, and pending versions. Migrations execute transactionally under a PostgreSQL advisory lock.

## Implemented capabilities

- immutable content-addressed raw capture and append-only receipts;
- generic contract-governed validation for all datasets;
- active contract manifest and retained contract versions;
- normalized validation errors and rejected-record quarantine;
- source, raw, contract, run, and cohort lineage;
- formal PostgreSQL migrations with install, upgrade, baseline, and drift tests;
- patients, encounters, diagnoses, and observations;
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

`audit.pipeline_runs` persists the same raw and contract lineage. Older pre-V004 rows receive explicit `legacy/unmanaged` values rather than fabricated receipts.

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

CI also exercises raw capture and verification through the CLI and inside the built container.

## Documentation

- [`docs/architecture.md`](docs/architecture.md): system architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): technical review sequence and SQL;
- [`docs/learning/generic-dataset-architecture-es.md`](docs/learning/generic-dataset-architecture-es.md);
- [`docs/learning/versioned-executable-contracts-es.md`](docs/learning/versioned-executable-contracts-es.md);
- [`docs/learning/database-migrations-es.md`](docs/learning/database-migrations-es.md);
- [`docs/learning/immutable-raw-landing-zone-es.md`](docs/learning/immutable-raw-landing-zone-es.md);
- [`docs/hypertension-cohort.md`](docs/hypertension-cohort.md).

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- historical clinical-record versioning;
- larger synthetic datasets and performance benchmarks;
- additional entities and terminology normalization;
- stronger operational observability;
- additional cohorts, attrition, and missingness reporting;
- security, dependency, and release hardening.

It intentionally excludes identifiable patient data, production decision support, enterprise authentication, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
