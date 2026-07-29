# Architecture

## System boundary

The repository is progressing toward a portfolio-grade clinical data platform. It operates only on synthetic data and is not a clinical production system.

## Architectural objective

The validation and persistence workflow must not contain a special path for patients. Every supported dataset is executed through the same pipeline and persistence functions.

```text
Dataset name
    │
    ▼
Dataset registry
    │
    ├── columns
    ├── identifier
    ├── validator
    ├── row builder
    └── upsert SQL
    │
    ▼
Generic validation pipeline
    │
    ▼
Generic persistence workflow
```

## Data flow

```text
Synthetic CSV source
        │
        ▼
Dataset registry lookup
        │
        ▼
UTF-8 ingestion
        │
        ▼
Registered dataset validator
        │
        ├── valid rows
        ├── invalid rows
        ├── normalized errors
        └── quality report + SHA-256 + run UUID
        │
        ▼
Generic transactional PostgreSQL loading
        │
        ├── registered row builder
        ├── registered upsert SQL
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

## Core modules

### `models.py`

Defines normalized structures shared by all datasets:

- `ValidationError`;
- `ValidationResult`;
- `DatasetPipelineSummary`.

The pipeline consumes these structures and does not depend on dataset-specific error classes.

### `registry.py`

Defines `DatasetDefinition`, the variation point of the architecture. A definition contains:

- dataset name;
- ordered CSV columns;
- primary identifier column;
- validation callable;
- row-conversion callable;
- PostgreSQL upsert statement.

`DATASET_REGISTRY` currently registers:

```text
patients
encounters
diagnoses
observations
```

Adding a dataset should require a new definition and its domain-specific implementation, not changes to the generic pipeline.

### `pipeline.py`

Implements the invariant validation workflow through:

```python
run_dataset_validation(...)
```

It performs registry lookup, ingestion, validation dispatch, quality-output generation, checksumming, and run-summary construction.

It contains no patient-specific branch.

### `database.py`

Implements the invariant persistence workflow through:

```python
persist_dataset_validation_outputs(...)
```

It validates output consistency, records the pipeline run, invokes the registered row builder and upsert SQL, persists normalized errors, and commits atomically.

It contains no patient-specific persistence function.

### Domain validators

Dataset-specific clinical rules remain separate:

- `validation.py`: patient rules;
- `clinical_entities.py`: encounter, diagnosis, and observation rules.

The registry adapts their outputs to the normalized validation model. This preserves domain rules while replacing duplicated orchestration.

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

The generic CLI commands are:

```text
clinical-data validate-dataset
clinical-data load-dataset
```

## Reproducibility controls

- immutable run UUIDs;
- source SHA-256 checksums;
- consistent output naming across datasets;
- explicit cohort definition version;
- parameterized cohort generation;
- deterministic baseline-measurement tie-breaking;
- persistent source-run mappings;
- automated linting, static typing, unit tests, and PostgreSQL integration tests.

## Design trade-offs

### Executable registry

The registry is Python code rather than a declarative contract. This makes callables and SQL easy to associate with a dataset, but it also couples registration to implementation details.

A later step may separate:

```text
schema contract
validation rules
persistence adapter
```

### Validation adapters

Patient and non-patient validators originally returned different error types. Registry adapters normalize these results without rewriting every clinical rule during the architectural refactor.

This reduces migration risk, but the adapters remain a temporary layer that can be simplified later.

### SQL in definitions

Keeping upsert SQL in `DatasetDefinition` centralizes dataset behavior. The cost is that registry definitions know about persistence. A larger system would likely register separate validation and persistence adapters.

## Extension rule

A new dataset is correctly integrated when it can be added without editing:

```text
pipeline.py
database.py
```

The extension should be limited to:

- domain rules;
- dataset definition;
- database table or migration;
- tests;
- documentation.

## Current limitations

The platform does not yet implement declarative versioned contracts, schema migrations, immutable raw storage, large-scale loading, external terminology services, production observability, authentication, or PHI handling.

The architectural refactor is the first step toward version `1.0.0`, not a claim of final production readiness.
