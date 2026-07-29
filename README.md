# Clinical Data Platform

> Status: early development — the first patient-data validation workflow is implemented.

Clinical Data Platform is a portfolio project for building reproducible clinical data engineering workflows with synthetic healthcare data.

The current milestone reads a patient CSV file, applies structural and clinical consistency rules, separates valid and invalid records, and produces auditable quality outputs. PostgreSQL storage, cohort construction, and feature engineering remain planned work.

## Motivation

Clinical datasets may contain inconsistent schemas, duplicated identifiers, invalid dates, missing values, incompatible categories, and broken temporal relationships.

This project demonstrates how software engineering and data-quality controls can detect and document these problems without silently discarding rejected records.

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
    │
    └── Invalid rows ──────► invalid_patients.csv
                              validation_errors.csv
                              quality_report.json
```

## Implemented capabilities

- Python package configuration through `pyproject.toml`;
- synthetic patient dataset with intentional validation failures;
- documented patient data contract;
- UTF-8 CSV ingestion with malformed-file checks;
- required-value, uniqueness, categorical, date-format, future-date, and temporal-consistency rules;
- valid-record and invalid-record outputs;
- structured validation-error output;
- JSON quality report with a source-file SHA-256 checksum;
- command-line interface;
- unit and end-to-end tests;
- Ruff, mypy, pytest, and GitHub Actions configuration.

## Quick start

### Requirements

- Python 3.11 or later
- Git

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

### Run the patient validation workflow

```bash
clinical-data validate-patients data/sample/patients.csv \
  --output-dir data/processed/patients \
  --reference-date 2026-07-29
```

The same command can be run through the Python module:

```bash
python -m clinical_data_platform validate-patients data/sample/patients.csv \
  --output-dir data/processed/patients \
  --reference-date 2026-07-29
```

### Run quality checks

```bash
python -m ruff check .
python -m mypy src
python -m pytest
```

## Outputs

A successful run creates:

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

## Repository structure

```text
clinical-data-platform/
├── .github/workflows/ci.yml
├── data/sample/patients.csv
├── docs/data-contracts/patients.md
├── src/clinical_data_platform/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── ingestion.py
│   ├── pipeline.py
│   └── validation.py
├── tests/
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
- [ ] PostgreSQL schema and loading
- [ ] Reproducible cohort construction
- [ ] Feature generation
- [ ] Data-lineage persistence
- [ ] Docker Compose environment

## Planned architecture

```text
Validated clinical data
        │
        ▼
PostgreSQL
        │
        ▼
Cohort construction
        │
        ▼
Feature generation
        │
        ▼
Analysis-ready datasets
```

## Data and privacy

This repository uses synthetic data. It is not intended to process identifiable patient information, support clinical decision-making, or operate as a production healthcare system.
