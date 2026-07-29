# Clinical Data Platform

> Status: active development toward `1.0.0` — the validation and persistence architecture is now dataset-generic.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates the path from raw healthcare-like records to an auditable analysis-ready dataset.

The repository uses only synthetic data. It is intended for engineering review and learning, not for identifiable patient data, clinical decision-making, or production healthcare use.

## Current architectural milestone

The original implementation had one pipeline for patients and a second pipeline for encounters, diagnoses, and observations. That duplication has been removed.

All datasets now use the same two operations:

```python
run_dataset_validation(...)
persist_dataset_validation_outputs(...)
```

Dataset-specific behavior is registered through `DatasetDefinition` objects.

```text
Dataset registry
    ├── patients
    ├── encounters
    ├── diagnoses
    └── observations
          │
          ▼
Generic validation pipeline
          │
          ▼
Generic PostgreSQL persistence
```

There is no patient-specific pipeline or persistence path.

## What the project does

```text
Synthetic CSV files
        │
        ▼
Dataset registry lookup
        │
        ▼
Schema and clinical validation
        │
        ├── valid rows
        ├── quarantined rows
        ├── normalized errors
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

- generic dataset registry;
- one validation pipeline for all registered datasets;
- one persistence workflow for all registered datasets;
- normalized cross-dataset validation errors;
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

## Generic dataset definition

Every supported dataset is represented by a `DatasetDefinition`:

```python
DatasetDefinition(
    name="patients",
    columns=(...),
    id_column="patient_id",
    validator=...,
    row_builder=...,
    upsert_sql=...,
)
```

The generic pipeline does not know patient-specific columns or clinical rules. It retrieves that behavior from the registry.

The extension test in `tests/test_registry.py` registers a temporary `labs` dataset and runs it through the existing pipeline without modifying `pipeline.py`.

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
clinical-data validate-dataset
clinical-data load-dataset
clinical-data build-hypertension-cohort
clinical-data run-demo
```

Validate patients through the generic command:

```powershell
clinical-data validate-dataset patients data/sample/patients.csv `
  --output-dir data/processed/patients `
  --reference-date 2026-07-29
```

Validate observations through the same command:

```powershell
clinical-data validate-dataset observations data/sample/observations.csv `
  --output-dir data/processed/observations `
  --reference-date 2026-07-29
```

Load any validated dataset:

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

Integration tests use PostgreSQL and are executed automatically in GitHub Actions.

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
│   ├── learning/
│   │   └── generic-dataset-architecture-es.md
│   └── data-contracts/
├── scripts/
├── sql/
├── src/clinical_data_platform/
│   ├── clinical_entities.py
│   ├── cohort.py
│   ├── database.py
│   ├── demo.py
│   ├── ingestion.py
│   ├── models.py
│   ├── pipeline.py
│   ├── registry.py
│   └── validation.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md): generic system architecture and design trade-offs;
- [`docs/learning/generic-dataset-architecture-es.md`](docs/learning/generic-dataset-architecture-es.md): Spanish study guide, interview explanations, and exercises;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): technical review sequence and SQL queries;
- [`docs/database.md`](docs/database.md): persistence and idempotency;
- [`docs/hypertension-cohort.md`](docs/hypertension-cohort.md): cohort definition and variables;
- [`docs/data-contracts/`](docs/data-contracts/): source schemas and validation rules.

## Current limitations

The repository is not yet version `1.0.0`. The next architectural steps include:

- declarative and versioned data contracts;
- schema migration tooling;
- immutable raw-data storage;
- large-scale loading and benchmarks;
- expanded entities and terminology normalization;
- stronger operational observability;
- additional cohort definitions and attrition reporting.

It also intentionally excludes identifiable patient data, production clinical decision support, enterprise authentication, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
