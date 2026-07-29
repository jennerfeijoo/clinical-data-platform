# Clinical Data Platform
> Status: early development — project structure and first ingestion workflow.
Clinical Data Platform is a work-in-progress portfolio project focused on
building a reproducible pipeline for synthetic clinical data.

The planned platform will ingest, validate, store, and transform healthcare
records while preserving data quality and transformation lineage.

## Motivation

Clinical datasets may contain inconsistent schemas, duplicated identifiers,
invalid dates, missing values, incompatible units, and broken relationships
between clinical entities.

This project explores how software engineering and data engineering practices
can be applied to detect and manage these problems reproducibly.
## Planned scope

- synthetic clinical data ingestion;
- schema validation;
- clinical consistency rules;
- PostgreSQL storage;
- invalid-record quarantine;
- reproducible cohort construction;
- feature generation;
- testing and continuous integration;
- execution metadata and lineage.

## Current implementation

Currently implemented:

- [x] repository initialized;
- [ ] project configuration;
- [ ] synthetic dataset;
- [ ] PostgreSQL schema;
- [ ] ingestion pipeline;
- [ ] validation rules;
- [ ] automated tests.

## First milestone

The first milestone is a complete vertical slice that:

1. reads a synthetic patient CSV file;
2. validates its schema;
3. separates valid and invalid rows;
4. loads valid records into PostgreSQL;
5. records a validation summary;
6. runs through Docker Compose;
7. is covered by automated tests.

## Running the project

Execution instructions will be added once the first end-to-end workflow is
available.

## Planned workflow

```text
Synthetic source data
        ↓
Schema validation
        ↓
Clinical consistency checks
        ↓
Valid records ────────── Invalid records
        ↓                       ↓
PostgreSQL                 Quarantine report
        ↓
Cohort and feature generation


## 10. Privacidad

```markdown
## Data and privacy

The project will use only synthetic or appropriately licensed public data.

It is not intended for identifiable patient data, clinical decision-making,
or production healthcare use.







