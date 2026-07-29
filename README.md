# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.4.0` introduces executable, versioned dataset contracts.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates the path from raw healthcare-like records to an auditable analysis-ready dataset.

The repository uses only synthetic data. It is intended for engineering review and learning, not for identifiable patient data, clinical decision-making, or production healthcare use.

## Current architectural milestone

The platform now separates three concerns explicitly:

```text
Versioned data contract
        │
        ├── columns and order
        ├── required values
        ├── primary key and uniqueness
        ├── types and categories
        ├── temporal rules
        └── measurement profiles
        │
        ▼
Generic validation pipeline
        │
        ▼
Registry-controlled persistence
```

The contracts are TOML resources packaged with the application:

```text
src/clinical_data_platform/contracts/
├── manifest.toml
├── patients/v1.0.0.toml
├── encounters/v1.0.0.toml
├── diagnoses/v1.0.0.toml
└── observations/v1.0.0.toml
```

`manifest.toml` selects the active version for every dataset. Historical contract files remain available for reproducibility.

## Why the contracts are executable

The pipeline does not merely display the contracts. It uses them to determine whether each row is valid.

The contract engine currently executes:

- required and unexpected-column rules;
- required-value and uniqueness rules;
- string, date, timezone-aware datetime, and finite-number types;
- categorical vocabularies;
- dates that must not be in the future;
- temporal ordering between fields;
- conditional measurement units and plausible ranges.

Each validation run records:

```text
source_path
source_sha256
contract_path
contract_version
contract_sha256
reference_date
run_id
```

The loader recalculates the contract hash before writing to PostgreSQL. A quality report with inconsistent contract lineage is rejected.

## Data flow

```text
Synthetic CSV files
        │
        ▼
Active contract selected by manifest
        │
        ▼
Executable contract validation
        │
        ├── valid rows
        ├── quarantined rows
        ├── normalized errors
        └── quality report + source/contract lineage
        │
        ▼
Transactional PostgreSQL loading
        │
        ├── normalized clinical tables
        └── audit.pipeline_runs
        │
        ▼
Versioned hypertension cohort SQL
        │
        ▼
Analysis-ready feature table + metadata
```

## Implemented capabilities

- active contract manifest;
- immutable versioned contract resources;
- contract-definition validation;
- executable structural, categorical, temporal, and measurement rules;
- generic validation pipeline for all datasets;
- generic persistence workflow for all datasets;
- normalized cross-dataset validation errors;
- synthetic patients, encounters, diagnoses, and observations;
- rejected-record quarantine outputs;
- run UUIDs and SHA-256 checksums for source and contract files;
- PostgreSQL persistence of contract lineage;
- transactional, idempotent loading;
- referential-integrity enforcement;
- version-controlled hypertension cohort construction;
- baseline feature generation and CSV export;
- Docker and Docker Compose execution;
- PowerShell and POSIX demo scripts;
- Ruff, mypy, pytest, coverage, PostgreSQL integration tests, and GitHub Actions.

## Contract inspection commands

List active versions:

```powershell
clinical-data list-contracts
```

Show one parsed contract:

```powershell
clinical-data show-contract observations
```

Validate every active definition:

```powershell
clinical-data validate-contracts
```

Example output from `list-contracts` includes dataset, version, SHA-256, and resource path.

## Fastest way to run the complete workflow

Requirements:

- Git;
- Docker with Docker Compose.

Clone the repository:

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

The scripts start PostgreSQL, build the application image, validate and persist all datasets, construct the cohort, and write generated files under:

```text
data/processed/
data/analytics/
```

Reset the local database when needed:

```bash
docker compose down -v
```

## Expected bundled-sample result

| Dataset | Received | Valid | Invalid | Errors | Contract |
|---|---:|---:|---:|---:|---:|
| Patients | 8 | 5 | 3 | 3 | 1.0.0 |
| Encounters | 8 | 7 | 1 | 1 | 1.0.0 |
| Diagnoses | 7 | 6 | 1 | 2 | 1.0.0 |
| Observations | 14 | 13 | 1 | 1 | 1.0.0 |

The default hypertension cohort contains two patients:

| Patient | Baseline BP | Follow-up |
|---|---:|---:|
| `P001` | 146/92 mmHg | 95 days |
| `P002` | 151/96 mmHg | 37 days |

`P005` has hypertension and baseline blood pressure but is excluded because the synthetic dataset contains insufficient follow-up.

## Generated outputs

Each validated dataset produces:

```text
valid_<dataset>.csv
invalid_<dataset>.csv
validation_errors.csv
quality_report.json
```

The quality report includes contract lineage:

```json
{
  "contract_path": "patients/v1.0.0.toml",
  "contract_version": "1.0.0",
  "contract_sha256": "..."
}
```

The analytical stage produces:

```text
data/analytics/
├── hypertension_features.csv
└── hypertension_cohort_metadata.json
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

Run the complete workflow without the application container:

```powershell
clinical-data run-demo --repository-root .
```

## Main CLI commands

```text
clinical-data list-contracts
clinical-data show-contract
clinical-data validate-contracts
clinical-data validate-dataset
clinical-data load-dataset
clinical-data build-hypertension-cohort
clinical-data run-demo
```

Validate patients:

```powershell
clinical-data validate-dataset patients data/sample/patients.csv `
  --output-dir data/processed/patients `
  --reference-date 2026-07-29
```

Load validated patients:

```powershell
clinical-data load-dataset patients `
  --output-dir data/processed/patients `
  --schema sql/schema.sql
```

## Quality checks

```bash
python -m ruff check .
python -m mypy src
python -m pytest --cov=clinical_data_platform --cov-report=term-missing
docker build --tag clinical-data-platform:local .
```

Integration tests use PostgreSQL and run automatically in GitHub Actions.

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
│       └── versioned-executable-contracts-es.md
├── scripts/
├── sql/
├── src/clinical_data_platform/
│   ├── contracts/
│   ├── cohort.py
│   ├── contract.py
│   ├── database.py
│   ├── demo.py
│   ├── ingestion.py
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
- [`docs/learning/generic-dataset-architecture-es.md`](docs/learning/generic-dataset-architecture-es.md): generic registry architecture;
- [`docs/learning/versioned-executable-contracts-es.md`](docs/learning/versioned-executable-contracts-es.md): detailed Spanish guide to contract execution and versioning;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): technical review sequence and SQL queries;
- [`docs/database.md`](docs/database.md): persistence, idempotency, and lineage;
- [`docs/hypertension-cohort.md`](docs/hypertension-cohort.md): cohort definition and variables.

## Versioning policy for contracts

Published contract files are not overwritten.

```text
PATCH: non-behavioral correction
MINOR: backward-compatible addition
MAJOR: incompatible interface change
```

A new active version is introduced by adding a new file and updating `manifest.toml`.

## Current limitations

The repository is not yet version `1.0.0`. The next architectural steps include:

- database schema migration tooling;
- immutable raw-data storage;
- historical record strategy;
- larger synthetic datasets and benchmarks;
- expanded entities and terminology normalization;
- stronger operational observability;
- additional cohort definitions and attrition reporting.

It intentionally excludes identifiable patient data, production clinical decision support, enterprise authentication, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
