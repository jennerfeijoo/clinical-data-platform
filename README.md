# Clinical Data Platform

> Status: portfolio MVP complete — synthetic clinical data can be validated, persisted, traced, transformed into a reproducible cohort, and exported for analysis.

Clinical Data Platform is a compact clinical data engineering project that demonstrates the path from raw healthcare-like records to an auditable analysis-ready dataset.

The repository uses only synthetic data. It is designed for engineering review and learning, not for identifiable patient data, clinical decision-making, or production healthcare use.

## What the project does

```text
Synthetic CSV files
        │
        ▼
Schema and clinical validation
        │
        ├── valid rows
        ├── quarantined rows
        ├── structured errors
        └── quality reports
        │
        ▼
Transactional PostgreSQL loading
        │
        ├── normalized clinical tables
        └── persistent run lineage
        │
        ▼
Versioned hypertension cohort SQL
        │
        ▼
Analysis-ready feature table + metadata
```

## Implemented capabilities

- Python package and command-line interface;
- synthetic patients, encounters, diagnoses, and observations;
- documented data contracts;
- UTF-8 CSV ingestion;
- required-field and uniqueness checks;
- categorical and vocabulary validation;
- ISO date and timezone-aware datetime validation;
- temporal-consistency rules;
- measurement-unit and clinical-plausibility rules;
- rejected-record quarantine outputs;
- structured validation errors;
- run UUIDs and source SHA-256 checksums;
- normalized PostgreSQL clinical, audit, and analytics schemas;
- transactional, idempotent loading;
- referential-integrity enforcement;
- persistent pipeline and cohort lineage;
- version-controlled hypertension cohort construction;
- baseline feature generation and CSV export;
- Docker and Docker Compose execution;
- PowerShell and POSIX demo scripts;
- Ruff, mypy, pytest, coverage, PostgreSQL integration tests, and GitHub Actions.

## Fastest way to run the complete MVP

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

The scripts start PostgreSQL, build the application image, run the complete workflow, and write generated files under:

```text
data/processed/
data/analytics/
```

Reset the local database when needed:

```bash
docker compose down -v
```

## Expected bundled-sample result

Validated rows:

| Dataset | Received | Valid | Invalid | Errors |
|---|---:|---:|---:|---:|
| Patients | 8 | 5 | 3 | 3 |
| Encounters | 8 | 7 | 1 | 1 |
| Diagnoses | 7 | 6 | 1 | 2 |
| Observations | 14 | 13 | 1 | 1 |

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

The analytical stage produces:

```text
data/analytics/
├── hypertension_features.csv
└── hypertension_cohort_metadata.json
```

The metadata file records the cohort run UUID, definition version, parameters, source run UUIDs, generation time, and row count.

## PostgreSQL model

### Clinical schema

```text
clinical.patients
clinical.encounters
clinical.diagnoses
clinical.observations
```

### Audit schema

```text
audit.pipeline_runs
audit.validation_errors
audit.cohort_runs
audit.cohort_source_runs
```

### Analytics schema

```text
analytics.hypertension_features
```

The database preserves the source run and source checksum for every persisted clinical record. Cohort runs reference the latest successful run for each required source dataset.

## Local Python development

Create and activate a virtual environment:

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
clinical-data validate-patients
clinical-data load-patients
clinical-data validate-entity
clinical-data load-entity
clinical-data build-hypertension-cohort
clinical-data run-demo
```

Example entity validation:

```powershell
clinical-data validate-entity observations data/sample/observations.csv `
  --output-dir data/processed/observations `
  --reference-date 2026-07-29
```

Example cohort build after loading all source datasets:

```powershell
clinical-data build-hypertension-cohort `
  --sql sql/cohorts/hypertension.sql `
  --output-dir data/analytics
```

## Quality checks

```bash
python -m ruff check .
python -m mypy src
python -m pytest --cov=clinical_data_platform --cov-report=term-missing
docker build --tag clinical-data-platform:local .
```

Integration tests use PostgreSQL and are executed automatically in GitHub Actions.

## Repository structure

```text
clinical-data-platform/
├── .github/workflows/ci.yml
├── data/sample/
│   ├── patients.csv
│   ├── encounters.csv
│   ├── diagnoses.csv
│   └── observations.csv
├── docs/
│   ├── architecture.md
│   ├── analysis-guide.md
│   ├── database.md
│   ├── hypertension-cohort.md
│   └── data-contracts/
├── scripts/
│   ├── run_demo.ps1
│   └── run_demo.sh
├── sql/
│   ├── schema.sql
│   └── cohorts/hypertension.sql
├── src/clinical_data_platform/
│   ├── clinical_entities.py
│   ├── cohort.py
│   ├── database.py
│   ├── demo.py
│   ├── entity_database.py
│   ├── entity_pipeline.py
│   ├── ingestion.py
│   ├── pipeline.py
│   └── validation.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md): system layers and design boundaries;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): recommended technical review and SQL queries;
- [`docs/database.md`](docs/database.md): persistence and idempotency;
- [`docs/hypertension-cohort.md`](docs/hypertension-cohort.md): cohort definition and variables;
- [`docs/data-contracts/`](docs/data-contracts/): source schemas and validation rules.

## Deliberate limitations

The MVP does not claim production clinical readiness. It does not include:

- identifiable patient data;
- authentication or authorization;
- encryption key management;
- FHIR interfaces;
- external terminology services;
- workflow orchestration platforms;
- schema-migration tooling;
- production monitoring and alerting;
- a general-purpose cohort-definition language.

These constraints keep the repository small enough to review while still demonstrating ingestion, data quality, SQL, relational modeling, containers, testing, lineage, cohort derivation, and feature engineering.

## License

MIT License. See [`LICENSE`](LICENSE).
