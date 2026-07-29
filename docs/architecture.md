# Architecture

## System boundary

The repository is progressing toward a portfolio-grade clinical data platform. It operates only on synthetic data and is not a clinical production system.

## Architectural objective

Dataset interfaces must be explicit, executable, versioned, and auditable. The generic pipeline must not contain patient-specific or observation-specific validation branches.

```text
Dataset name
    │
    ▼
Active contract manifest
    │
    ▼
Versioned TOML contract
    │
    ├── schema and field order
    ├── primary key and uniqueness
    ├── required values
    ├── types and categories
    ├── temporal rules
    └── measurement profiles
    │
    ▼
Generic contract engine
    │
    ▼
Generic validation pipeline
    │
    ▼
Registry-controlled persistence
```

## Data flow

```text
Synthetic CSV source
        │
        ▼
Dataset registry lookup
        │
        ▼
Contract manifest lookup
        │
        ▼
Load and validate active TOML contract
        │
        ├── contract version
        ├── contract path
        └── contract SHA-256
        │
        ▼
UTF-8 ingestion
        │
        ▼
Execute contract rules
        │
        ├── valid rows
        ├── invalid rows
        ├── normalized errors
        └── quality report
        │
        ▼
Verify contract lineage again
        │
        ▼
Transactional PostgreSQL loading
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
```

## Contract resource model

Contracts are packaged application resources:

```text
src/clinical_data_platform/contracts/
├── manifest.toml
├── patients/v1.0.0.toml
├── encounters/v1.0.0.toml
├── diagnoses/v1.0.0.toml
└── observations/v1.0.0.toml
```

`manifest.toml` maps a dataset name to its active contract resource. A historical contract file is retained after a newer version becomes active.

A contract defines:

```text
name
semantic version
primary key
patient identifier column
extra-column policy
ordered columns
column types
required and unique flags
allowed values
temporal ordering rules
not-in-future rules
conditional measurement profiles
```

## Core modules

### `contract.py`

Defines the contract engine:

- parses TOML with Python `tomllib`;
- validates the contract definition itself;
- enforces semantic version syntax;
- checks that primary keys and rule references are internally consistent;
- computes SHA-256 over the exact contract bytes;
- executes contract rules against source records;
- returns normalized `ValidationResult` objects.

The contract engine does not connect to PostgreSQL and does not contain dataset-specific SQL.

### `models.py`

Defines normalized structures shared by all datasets:

- `ValidationError`;
- `ValidationResult`;
- `DatasetPipelineSummary`.

The pipeline consumes these structures and does not depend on dataset-specific error classes.

### `registry.py`

Defines runtime behavior that remains inappropriate for free-form configuration:

- row conversion to PostgreSQL values;
- upsert SQL.

`DatasetDefinition` obtains columns and primary keys from the active contract instead of duplicating them in Python.

The registry and contract manifest must contain the same datasets in the same deterministic order. A mismatch fails early.

### `pipeline.py`

Implements the invariant validation workflow through:

```python
run_dataset_validation(...)
```

It performs:

1. registry lookup;
2. active contract loading;
3. source checksum calculation;
4. CSV ingestion;
5. contract execution;
6. output generation;
7. quality-report generation;
8. run-summary construction.

The quality report records both source and contract lineage.

### `database.py`

Implements the invariant persistence workflow through:

```python
persist_dataset_validation_outputs(...)
```

Before persistence it:

1. validates generated output counts;
2. loads the historical contract referenced by `contract_path`;
3. verifies dataset identity;
4. verifies `contract_version`;
5. recalculates and compares `contract_sha256`;
6. inserts pipeline metadata;
7. converts validated rows using the registered row builder;
8. performs the registered upsert;
9. stores normalized errors;
10. commits atomically.

This allows a run generated under an older retained contract to preserve its exact lineage even after the manifest activates a newer version.

## Validation layers

### Contract validation

Executed before database access:

```text
required_column
unexpected_column
required_value
unique
allowed_values
iso_date
iso_datetime
numeric
not_in_future
temporal_consistency
unit_consistency
plausible_range
```

### Relational validation

Executed by PostgreSQL:

- foreign keys;
- database check constraints;
- primary keys;
- transactional consistency.

Rejected rows are preserved rather than silently dropped.

## Versioning model

Contract versions follow semantic versioning:

```text
MAJOR.MINOR.PATCH
```

Policy:

- PATCH: non-behavioral correction;
- MINOR: backward-compatible interface addition;
- MAJOR: incompatible interface change.

Published contract resources are not overwritten. A new version is introduced as a new file and activated by updating the manifest.

## Reproducibility model

A validation run is identified by:

```text
run UUID
source path
source SHA-256
contract resource path
contract semantic version
contract SHA-256
reference date
generation timestamp
```

The version communicates intended compatibility. The hash identifies the exact bytes executed.

## Interface layer

The package exposes:

- Python APIs;
- the `clinical-data` CLI;
- Docker Compose services;
- PowerShell and POSIX demo scripts.

Contract-oriented CLI commands:

```text
clinical-data list-contracts
clinical-data show-contract
clinical-data validate-contracts
```

Pipeline commands:

```text
clinical-data validate-dataset
clinical-data load-dataset
```

## Design trade-offs

### TOML instead of YAML

Python 3.11 includes `tomllib`, so contracts can be parsed without another runtime dependency. TOML remains readable and supports nested tables and arrays of tables.

### Contracts inside the package

This guarantees that contracts are available in editable installs, wheels, and Docker images. The cost is that publishing a new active contract requires a new package build.

### SQL remains in Python

Contracts describe accepted data and validation rules. SQL remains controlled code because arbitrary SQL in configuration would expand the execution and security surface.

### Purpose-built rule language

The engine supports the rules required by the current clinical datasets. It is not intended to replace general systems such as JSON Schema, Pydantic, Pandera, or enterprise data-contract platforms.

## Extension rule

A new dataset is correctly integrated when it can be added without editing:

```text
pipeline.py
database.py
```

The extension is limited to:

- a versioned contract;
- a manifest entry;
- a registry persistence adapter;
- a database table or migration;
- tests;
- documentation.

## Current limitations

The platform does not yet implement:

- database schema migrations;
- immutable raw storage;
- historical clinical-record versioning;
- large-scale loading and benchmarks;
- external terminology services;
- production observability;
- authentication;
- PHI handling.

Executable contracts improve reproducibility and maintainability but do not imply production clinical readiness.
