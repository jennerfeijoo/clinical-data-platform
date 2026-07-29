# Architecture

## System boundary

The repository is progressing toward a portfolio-grade clinical data platform. It operates only on synthetic data and is not a clinical production system.

## Architectural objective

Dataset interfaces, schema evolution, validation, persistence, and analytical derivation must be explicit and independently reviewable.

```text
Dataset name
    │
    ▼
Active contract manifest
    │
    ▼
Versioned TOML contract
    │
    ▼
Generic contract engine
    │
    ▼
Generic validation pipeline
    │
    ▼
Formal PostgreSQL migrations
    │
    ▼
Registry-controlled persistence
    │
    ▼
Versioned cohort SQL
```

The generic pipeline contains no patient-specific validation path. Database creation contains no monolithic `schema.sql` path.

## End-to-end data flow

```text
Synthetic CSV source
        │
        ▼
Registry + active contract lookup
        │
        ▼
Contract-definition validation
        │
        ▼
UTF-8 ingestion and rule execution
        │
        ├── valid rows
        ├── invalid rows
        ├── normalized errors
        └── source/contract quality report
        │
        ▼
Database migration validation
        │
        ├── version history
        ├── migration checksums
        ├── advisory lock
        └── pending SQL migrations
        │
        ▼
Contract-lineage verification
        │
        ▼
Transactional PostgreSQL persistence
        │
        ▼
Versioned cohort SQL
        │
        ▼
Analysis-ready feature export
```

## Contract resource model

Contracts are packaged resources:

```text
src/clinical_data_platform/contracts/
├── manifest.toml
├── patients/v1.0.0.toml
├── encounters/v1.0.0.toml
├── diagnoses/v1.0.0.toml
└── observations/v1.0.0.toml
```

The manifest selects an active version. Historical contracts remain available so older validation bundles can be verified by path, version, and SHA-256.

## Migration resource model

Database evolution is represented by packaged SQL migrations:

```text
src/clinical_data_platform/migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
└── V003__add_contract_lineage.sql
```

The migration history is stored in:

```text
public.schema_migrations
```

This table is outside `audit` because V001 is responsible for creating the `audit` schema.

## Core modules

### `contract.py`

- parses TOML with `tomllib`;
- validates contract consistency;
- enforces semantic version syntax;
- computes contract SHA-256;
- executes structural, categorical, temporal, and measurement rules;
- returns normalized `ValidationResult` objects.

It does not connect to PostgreSQL.

### `migration.py`

- discovers `VNNN__name.sql` resources;
- verifies contiguous ordering and unique names;
- calculates migration SHA-256;
- detects known legacy schema states;
- validates applied history;
- acquires a PostgreSQL advisory transaction lock;
- applies pending migrations transactionally;
- records execution metadata;
- supports explicit baseline and target-version operations;
- rejects downgrades, partial legacy schemas, and checksum drift.

It does not load clinical datasets.

### `models.py`

Defines normalized cross-dataset structures:

- `ValidationError`;
- `ValidationResult`;
- `DatasetPipelineSummary`.

### `registry.py`

Defines runtime behavior that is intentionally not free-form configuration:

- typed row conversion;
- PostgreSQL upsert SQL.

Columns and primary keys come from active contracts rather than duplicated Python constants.

### `pipeline.py`

Implements the invariant validation workflow:

```python
run_dataset_validation(...)
```

It loads the contract, hashes the source, ingests CSV, executes rules, writes valid and invalid rows, writes normalized errors, and records source/contract lineage.

### `database.py`

Implements dataset persistence:

```python
persist_dataset_validation_outputs(...)
```

It verifies generated counts and historical contract lineage, converts rows through the registry, stores run metadata and errors, performs upserts, and commits atomically.

It does not create or alter database tables.

### `demo.py`

Coordinates:

```text
migrate
→ validate datasets
→ persist datasets
→ build cohort
→ export features
```

## Validation boundaries

### Contract engine

Handles intrinsic file-level rules:

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

### Migration engine

Handles database-history rules:

```text
contiguous migration versions
immutable migration checksums
known current version
no unmanaged schema drift
no downgrade
explicit baseline
single concurrent migrator
```

### PostgreSQL

Handles relational integrity:

- primary keys;
- foreign keys;
- check constraints;
- transactional consistency.

## Migration lifecycle

### Fresh install

```text
empty database
→ create migration history
→ V001
→ V002
→ V003
```

### Managed upgrade

```text
current V001
→ validate V001 checksum
→ apply V002
→ apply V003
```

### Legacy baseline

```text
recognized existing schema
+
no migration history
→ explicit --baseline-existing
→ register equivalent versions as baseline
```

Partial or unknown structures are rejected.

## Transaction and concurrency model

All pending migrations and their history rows are applied within a PostgreSQL transaction. An advisory transaction lock prevents two cooperating processes from migrating the same database concurrently.

If SQL execution fails, its migration-history insertion is rolled back with it.

## Reproducibility model

A validation run records:

```text
run UUID
source path
source SHA-256
contract path
contract semantic version
contract SHA-256
reference date
generation timestamp
```

A database records:

```text
migration version
migration name
migration SHA-256
application version
execution type
application timestamp
execution duration
```

Contract version communicates data-interface compatibility. Contract hash identifies exact validation bytes. Migration version communicates schema order. Migration hash identifies exact DDL bytes.

## Interface layer

Contract commands:

```text
clinical-data list-contracts
clinical-data show-contract
clinical-data validate-contracts
```

Migration commands:

```text
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

Pipeline commands:

```text
clinical-data validate-dataset
clinical-data load-dataset
clinical-data build-hypertension-cohort
clinical-data run-demo
```

Loading, cohort construction, and the demo apply pending migrations before writing.

## Design trade-offs

### Purpose-built SQL migrator

The project uses explicit SQL and psycopg without an ORM. A small migrator keeps DDL visible and avoids introducing ORM-oriented migration tooling solely to execute SQL files.

The cost is ownership of discovery, locking, history validation, baseline detection, and checksum policy. A larger multi-service environment may justify Alembic, Flyway, or Liquibase.

### Forward-only migrations

Downgrades are not automated because reverse DDL can destroy data. Corrections are introduced as new forward migrations. Operational rollback would rely on backup/restore or an explicit compatibility strategy.

### Contracts and migrations remain separate

Contracts define accepted source data. Migrations define database structure. A contract version change does not automatically generate DDL, and a migration does not redefine source validation semantics.

### SQL remains controlled code

Contracts do not contain arbitrary persistence SQL. The registry and migrations keep database-changing operations reviewable as application-controlled code.

## Extension rules

A new dataset requires:

- a versioned contract;
- a manifest entry;
- a registry persistence adapter;
- a new database migration when storage changes;
- tests;
- documentation.

A new schema change requires:

- the next contiguous migration file;
- fresh-install testing;
- upgrade testing from the previous version;
- code compatibility changes;
- no edits to previously applied migrations.

## Current limitations

The platform does not yet implement:

- immutable raw storage;
- historical clinical-record versioning;
- large-scale loading and benchmarks;
- external terminology services;
- production observability;
- authentication;
- PHI handling;
- automated backup or restore workflows.

Formal migrations and executable contracts improve reproducibility and maintainability but do not imply production clinical readiness.
