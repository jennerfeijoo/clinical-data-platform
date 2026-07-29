# Architecture

## System boundary

The repository is a portfolio-grade clinical data engineering MVP. It operates only on synthetic data and is not a clinical production system.

## Data flow

```text
Synthetic CSV sources
        │
        ▼
UTF-8 ingestion
        │
        ▼
Dataset-specific validation
        │
        ├── valid rows
        ├── invalid rows
        ├── structured errors
        └── quality report + SHA-256 + run UUID
        │
        ▼
Transactional PostgreSQL loading
        │
        ├── clinical schema
        └── audit schema
        │
        ▼
Versioned cohort SQL
        │
        ▼
analytics.hypertension_features
        │
        ├── CSV feature export
        └── cohort metadata JSON
```

## Layers

### Source layer

Small version-controlled CSV files provide deterministic test fixtures. Intentional invalid records exercise validation and quarantine behavior.

### Validation layer

Validation is split into intrinsic and relational controls:

- Python validates schema presence, required values, uniqueness within a file, categories, formats, units, plausible ranges, and temporal relationships.
- PostgreSQL validates foreign keys and normalized relational constraints.

Rejected rows are preserved rather than silently dropped.

### Persistence layer

The `clinical` schema stores normalized entities. The `audit` schema stores pipeline execution metadata, validation failures, cohort runs, and cohort-to-source-run mappings.

Loads are transactional. A run UUID is inserted once, so retrying the same output directory is idempotent.

### Analytics layer

Cohort logic is implemented in version-controlled SQL. The current hypertension definition writes a materialized feature snapshot keyed by `cohort_run_id` and `patient_id`.

### Interface layer

The package exposes:

- a Python API;
- the `clinical-data` command-line interface;
- Docker Compose services;
- PowerShell and POSIX demo scripts.

## Reproducibility controls

- immutable run UUIDs;
- source SHA-256 checksums;
- explicit cohort definition version;
- parameterized cohort generation;
- deterministic baseline-measurement tie-breaking;
- persistent source-run mappings;
- automated linting, static typing, unit tests, and PostgreSQL integration tests.

## Deliberate design limitations

The MVP does not implement authentication, encryption key management, FHIR ingestion, terminology services, orchestration platforms, schema migrations, or production observability. These are intentionally excluded to keep the repository reviewable while demonstrating the core engineering path from raw data to an auditable analysis-ready cohort.
