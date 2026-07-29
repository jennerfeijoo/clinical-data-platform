# Clinical Data Platform

> Status: early development.

Clinical Data Platform is a work-in-progress portfolio project focused on building a reproducible workflow for synthetic clinical data.

The repository will incrementally implement ingestion, validation, storage, cohort construction, feature generation, testing, and data lineage. Only capabilities listed under **Current implementation** should be considered available.

## Motivation

Clinical datasets may contain inconsistent schemas, duplicated identifiers, invalid dates, missing values, incompatible units, and broken relationships between clinical entities.

This project explores how software engineering and data engineering practices can be applied to detect and manage these problems reproducibly.

## Planned workflow

```text
Synthetic clinical data
        │
        ▼
Schema validation
        │
        ▼
Clinical consistency checks
        │
        ├── Invalid records → Quarantine report
        │
        ▼
PostgreSQL
        │
        ▼
Cohort construction
        │
        ▼
Feature generation
```

## Current implementation

- [x] Repository initialized
- [ ] Python project configuration
- [ ] Synthetic patient dataset
- [ ] Patient data contract
- [ ] CSV ingestion
- [ ] Patient validation
- [ ] Invalid-record quarantine output
- [ ] PostgreSQL schema and loading
- [ ] Cohort construction
- [ ] Feature generation
- [ ] Continuous integration

## First milestone

The first end-to-end milestone will:

1. read a synthetic patient CSV file;
2. validate its schema and temporal consistency;
3. separate valid and invalid records;
4. produce a structured quality report;
5. run through automated tests.

## Planned technology stack

- Python
- SQL
- PostgreSQL
- Pandera or Pydantic
- Docker Compose
- pytest
- Ruff
- mypy
- GitHub Actions

## Data and privacy

The project will use only synthetic or appropriately licensed public data. It is not intended for identifiable patient data, clinical decision-making, or production healthcare use.
