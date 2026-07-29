# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.5.0` adds formal, checksum-verified PostgreSQL migrations.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates the path from healthcare-like source records to an auditable analysis-ready dataset.

The repository uses only synthetic data. It is intended for engineering review and learning, not for identifiable patient data, clinical decision-making, or production healthcare use.

## Current architecture

The platform separates four concerns:

```text
Versioned TOML contracts
        │
        ▼
Generic validation pipeline
        │
        ├── valid rows
        ├── quarantined rows
        ├── normalized errors
        └── source + contract lineage
        │
        ▼
Formal PostgreSQL migrations
        │
        ▼
Registry-controlled persistence
        │
        ▼
Versioned cohort SQL and feature export
```

There is no patient-specific pipeline and no monolithic schema installer.

## Executable data contracts

Active contracts are selected explicitly by:

```text
src/clinical_data_platform/contracts/manifest.toml
```

Published versions are retained:

```text
src/clinical_data_platform/contracts/
├── manifest.toml
├── patients/v1.0.0.toml
├── encounters/v1.0.0.toml
├── diagnoses/v1.0.0.toml
└── observations/v1.0.0.toml
```

The contract engine executes:

- required and unexpected-column rules;
- required-value and uniqueness rules;
- string, date, timezone-aware datetime, and finite-number types;
- categorical vocabularies;
- temporal ordering and not-in-future rules;
- conditional units and plausible measurement ranges.

Each validation run records source and contract paths, versions, SHA-256 hashes, reference date, and run UUID.

## Formal database migrations

The database is created and upgraded through packaged SQL migrations:

```text
src/clinical_data_platform/migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
└── V003__add_contract_lineage.sql
```

The migration engine:

- enforces contiguous `VNNN__name.sql` ordering;
- stores history in `public.schema_migrations`;
- verifies migration names and SHA-256 checksums;
- applies pending migrations transactionally;
- uses a PostgreSQL advisory lock to prevent concurrent migration races;
- supports explicit target versions for upgrade testing;
- rejects downgrades and history drift;
- supports explicit baselining of recognized pre-migration schemas.

Applied migrations are immutable. A schema change is introduced by adding a new migration rather than editing an applied one.

## Implemented capabilities

- active contract manifest and immutable contract resources;
- executable structural, categorical, temporal, and measurement rules;
- generic validation and persistence workflows;
- normalized validation errors and rejected-record quarantine;
- source and contract lineage with SHA-256 checksums;
- formal transactional PostgreSQL migrations;
- fresh-install, upgrade, baseline, and drift validation;
- normalized clinical, audit, and analytics schemas;
- transactional, idempotent dataset loading;
- referential-integrity enforcement;
- version-controlled hypertension cohort construction;
- baseline feature generation and CSV export;
- Docker and Docker Compose execution;
- PowerShell and POSIX demo scripts;
- Ruff, strict mypy, pytest, coverage, PostgreSQL integration tests, and GitHub Actions.

## Fastest complete run

Requirements:

- Git;
- Docker with Docker Compose.

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

The workflow starts PostgreSQL, builds the image, migrates the database, validates and loads all datasets, constructs the cohort, and writes:

```text
data/processed/
data/analytics/
```

Reset a local development database:

```bash
docker compose down -v
```

## Local Python development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Start PostgreSQL:

```powershell
Copy-Item .env.example .env
docker compose up -d postgres
$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"
```

Inspect database state before modifying it:

```powershell
clinical-data database-status
```

Apply all pending migrations:

```powershell
clinical-data database-migrate
clinical-data database-validate
```

Run the workflow:

```powershell
clinical-data run-demo --repository-root .
```

### Existing local database from version 0.4.0 or earlier

The migrator will not silently claim ownership of pre-existing platform tables. Review the database, then either reset the development volume or explicitly baseline a recognized schema:

```powershell
clinical-data database-migrate --baseline-existing
```

A partial or unrecognized schema is rejected.

## Main CLI commands

```text
clinical-data list-contracts
clinical-data show-contract
clinical-data validate-contracts
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
clinical-data validate-dataset
clinical-data load-dataset
clinical-data build-hypertension-cohort
clinical-data run-demo
```

List contracts:

```powershell
clinical-data list-contracts
clinical-data show-contract observations
clinical-data validate-contracts
```

Test an upgrade path:

```powershell
clinical-data database-migrate --target-version 1
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

Validate patients:

```powershell
clinical-data validate-dataset patients data/sample/patients.csv `
  --output-dir data/processed/patients `
  --reference-date 2026-07-29
```

Load patients. The command applies pending migrations first:

```powershell
clinical-data load-dataset patients `
  --output-dir data/processed/patients
```

## Expected sample result

| Dataset | Received | Valid | Invalid | Errors | Contract |
|---|---:|---:|---:|---:|---:|
| Patients | 8 | 5 | 3 | 3 | 1.0.0 |
| Encounters | 8 | 7 | 1 | 1 | 1.0.0 |
| Diagnoses | 7 | 6 | 1 | 2 | 1.0.0 |
| Observations | 14 | 13 | 1 | 1 | 1.0.0 |

The hypertension cohort contains:

| Patient | Baseline BP | Follow-up |
|---|---:|---:|
| `P001` | 146/92 mmHg | 95 days |
| `P002` | 151/96 mmHg | 37 days |

## Generated outputs

Each dataset produces:

```text
valid_<dataset>.csv
invalid_<dataset>.csv
validation_errors.csv
quality_report.json
```

The quality report includes:

```json
{
  "contract_path": "patients/v1.0.0.toml",
  "contract_version": "1.0.0",
  "contract_sha256": "...",
  "input_sha256": "...",
  "run_id": "..."
}
```

The analytical stage produces:

```text
data/analytics/
├── hypertension_features.csv
└── hypertension_cohort_metadata.json
```

## Migration history

Inspect applied versions:

```sql
SELECT
    version,
    name,
    checksum,
    execution_type,
    application_version,
    applied_at,
    execution_ms
FROM public.schema_migrations
ORDER BY version;
```

`execution_type = migration` means the runner executed the SQL. `execution_type = baseline` means an existing recognized schema was explicitly adopted without replaying historical DDL.

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

CI also tests migration installation, upgrade, explicit baseline, checksum drift rejection, packaged contract discovery, Docker construction, and container resource availability.

## Repository structure

```text
clinical-data-platform/
├── .github/workflows/ci.yml
├── data/sample/
├── docs/
│   ├── architecture.md
│   ├── analysis-guide.md
│   ├── database.md
│   ├── hypertension-cohort.md
│   └── learning/
│       ├── generic-dataset-architecture-es.md
│       ├── versioned-executable-contracts-es.md
│       └── database-migrations-es.md
├── scripts/
├── sql/cohorts/
├── src/clinical_data_platform/
│   ├── contracts/
│   ├── migrations/
│   ├── cohort.py
│   ├── contract.py
│   ├── database.py
│   ├── demo.py
│   ├── ingestion.py
│   ├── migration.py
│   ├── models.py
│   ├── pipeline.py
│   └── registry.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md): system architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, idempotency, and lineage;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): technical review sequence and SQL queries;
- [`docs/learning/generic-dataset-architecture-es.md`](docs/learning/generic-dataset-architecture-es.md): generic dataset architecture;
- [`docs/learning/versioned-executable-contracts-es.md`](docs/learning/versioned-executable-contracts-es.md): contract execution and versioning;
- [`docs/learning/database-migrations-es.md`](docs/learning/database-migrations-es.md): formal migration study guide;
- [`docs/hypertension-cohort.md`](docs/hypertension-cohort.md): cohort definition and variables.

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- immutable raw-data storage;
- historical record strategy;
- larger synthetic datasets and performance benchmarks;
- expanded entities and terminology normalization;
- stronger operational observability;
- additional cohort definitions, attrition, and missingness reporting;
- broader security and release hardening.

It intentionally excludes identifiable patient data, production clinical decision support, enterprise authentication, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
