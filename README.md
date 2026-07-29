# Clinical Data Platform

> Status: early development — patient validation and PostgreSQL persistence are implemented.

Clinical Data Platform is a portfolio project for building reproducible clinical data engineering workflows with synthetic healthcare data.

The current implementation reads a patient CSV file, applies structural and clinical consistency rules, separates valid and invalid records, produces auditable quality outputs, and persists valid records plus lineage metadata in PostgreSQL. Cohort construction and feature engineering remain planned work.

## Motivation

Clinical datasets may contain inconsistent schemas, duplicated identifiers, invalid dates, missing values, incompatible categories, and broken temporal relationships.

This project demonstrates how software engineering, data-quality controls, relational modeling, and transactional persistence can detect and document these problems without silently discarding rejected records.

## Current workflow

```text
Patient CSV
    │
    ▼
Safe CSV ingestion
    │
    ▼
Structural and clinical validation
    │
    ├── Valid rows ────────► valid_patients.csv
    │                          │
    │                          ▼
    │                     PostgreSQL
    │                     clinical.patients
    │
    └── Invalid rows ──────► invalid_patients.csv
                              validation_errors.csv
                              quality_report.json
                                  │
                                  ▼
                              PostgreSQL audit tables
```

## Implemented capabilities

- Python package configuration through `pyproject.toml`;
- synthetic patient dataset with intentional validation failures;
- documented patient data contract;
- UTF-8 CSV ingestion with malformed-file checks;
- required-value, uniqueness, categorical, date-format, future-date, and temporal-consistency rules;
- valid-record and invalid-record outputs;
- structured validation-error output;
- JSON quality report with a run UUID and source-file SHA-256 checksum;
- PostgreSQL clinical and audit schemas;
- transactional and idempotent loading of validation outputs;
- patient upserts with source-run lineage;
- Docker Compose configuration for local PostgreSQL;
- command-line interface;
- unit, end-to-end, and PostgreSQL integration tests;
- Ruff, mypy, pytest, and GitHub Actions configuration.

## Quick start

### Requirements

- Python 3.11 or later
- Git
- Docker with Docker Compose

### Install

```bash
git clone https://github.com/jennerfeijoo/clinical-data-platform.git
cd clinical-data-platform
python -m venv .venv
```

Activate the environment on PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the project and development tools:

```bash
python -m pip install -e ".[dev]"
```

### Start PostgreSQL

Create the local environment file and start the database:

```powershell
Copy-Item .env.example .env
docker compose up -d postgres
$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"
```

Check the service state:

```bash
docker compose ps
```

### Validate the sample patient data

```powershell
clinical-data validate-patients data/sample/patients.csv `
  --output-dir data/processed/patients `
  --reference-date 2026-07-29
```

The same workflow can be run through the Python module:

```powershell
python -m clinical_data_platform validate-patients data/sample/patients.csv `
  --output-dir data/processed/patients `
  --reference-date 2026-07-29
```

### Load validated outputs into PostgreSQL

```powershell
clinical-data load-patients `
  --output-dir data/processed/patients `
  --schema sql/schema.sql
```

Loading the same validation-output directory again is idempotent: the existing `run_id` is detected and the audit rows are not duplicated.

### Run quality checks

```bash
python -m ruff check .
python -m mypy src
python -m pytest
```

## File outputs

A successful validation run creates:

```text
data/processed/patients/
├── valid_patients.csv
├── invalid_patients.csv
├── validation_errors.csv
└── quality_report.json
```

For the included sample and reference date `2026-07-29`, the expected summary is:

```text
received=8, valid=5, invalid=3, errors=3
```

The sample intentionally exercises three rules:

- a birth date in the future;
- an unsupported `sex_at_birth` value;
- a death date preceding the birth date.

## PostgreSQL model

The database uses two schemas:

```text
clinical.patients

audit.pipeline_runs
audit.validation_errors
```

Each patient row retains the `source_run_id` and source-file checksum. The matching pipeline-run record stores input provenance, validation counts, reference date, status, and timestamps.

See [`docs/database.md`](docs/database.md) for persistence and idempotency details.

## Repository structure

```text
clinical-data-platform/
├── .github/workflows/ci.yml
├── data/sample/patients.csv
├── docs/
│   ├── data-contracts/patients.md
│   └── database.md
├── sql/schema.sql
├── src/clinical_data_platform/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── database.py
│   ├── ingestion.py
│   ├── pipeline.py
│   └── validation.py
├── tests/
├── .env.example
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## Current status

- [x] Repository and Python project configuration
- [x] Synthetic patient dataset
- [x] Patient data contract
- [x] CSV ingestion
- [x] Patient validation
- [x] Invalid-record quarantine outputs
- [x] Structured quality report
- [x] Automated tests and continuous integration
- [x] PostgreSQL schema and loading
- [x] Basic data-lineage persistence
- [x] Docker Compose database environment
- [ ] Reproducible cohort construction
- [ ] Feature generation
- [ ] Expanded clinical entities
- [ ] Workflow orchestration

## Next milestone

The next milestone will add a reproducible hypertension cohort and baseline feature table derived from the persisted patient and observation data.

## Data and privacy

This repository uses synthetic data. It is not intended to process identifiable patient information, support clinical decision-making, or operate as a production healthcare system.
