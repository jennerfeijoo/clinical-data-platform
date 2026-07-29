# Architecture

## System boundary

The repository is progressing toward a portfolio-grade clinical data platform. It operates only on synthetic data and is not a clinical production system.

## Architectural objective

Source preservation, data acceptance, schema evolution, persistence, and analytical derivation must be explicit and independently reviewable.

```text
External source
    │
    ▼
Immutable raw landing zone
    │
    ▼
Active contract manifest
    │
    ▼
Versioned executable contract
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

The generic pipeline contains no patient-specific path. Database creation contains no monolithic `schema.sql` path.

## End-to-end flow

```text
External CSV source
        │
        ▼
Raw capture before parsing
        ├── SHA-256 + byte size
        ├── content-addressed object
        ├── append-only receipt
        └── atomic publication
        │
        ▼
Read captured raw object
        │
        ▼
Registry + active contract lookup
        │
        ▼
Contract rule execution
        ├── valid rows
        ├── invalid rows
        ├── normalized errors
        └── quality report with raw + contract lineage
        │
        ▼
Migration validation and pending migrations
        │
        ▼
Raw receipt/object verification
        │
        ▼
Contract-lineage verification
        │
        ▼
Transactional PostgreSQL persistence
        │
        ▼
Versioned cohort SQL and feature export
```

## Raw storage model

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<uuid>.json
```

Objects model byte content. Receipts model ingestion events.

```text
same bytes received twice
        │
        ├── one content object
        └── two receipt manifests
```

The application writes to staging, fsyncs, and atomically publishes with a hard link. Existing final paths are never replaced. Published files are marked read-only and verified by SHA-256 before reuse.

This is application-level local immutability, not certified WORM storage.

## Contract resource model

Contracts are packaged under `src/clinical_data_platform/contracts/`. The manifest explicitly selects an active version. Historical resources remain available for verification by path, semantic version, and SHA-256.

## Migration resource model

```text
src/clinical_data_platform/migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
├── V003__add_contract_lineage.sql
└── V004__add_raw_landing_lineage.sql
```

History is stored in `public.schema_migrations`. V004 adds receipt and raw-object lineage to `audit.pipeline_runs`.

## Core modules

### `raw.py`

- calculates source SHA-256 and byte size;
- derives deterministic content paths;
- stages and atomically publishes immutable artifacts;
- deduplicates identical content;
- creates append-only receipt manifests;
- rejects path traversal;
- verifies receipt location, object path, size, and hash.

It does not parse clinical fields or connect to PostgreSQL.

### `contract.py`

- parses and validates TOML contracts;
- computes contract SHA-256;
- executes structural, categorical, temporal, and measurement rules;
- returns normalized validation results.

### `pipeline.py`

`run_dataset_validation(...)` now enforces this order:

```text
capture raw
→ read raw object
→ execute contract
→ write quality outputs
```

The external source path is metadata. The raw object is the validation input.

### `migration.py`

- discovers contiguous SQL migrations;
- validates immutable checksums and recorded history;
- recognizes complete V001–V004 schema signatures;
- acquires an advisory transaction lock;
- applies pending migrations atomically;
- supports explicit baseline and target-version testing.

### `registry.py`

Keeps dataset-specific row conversion and upsert SQL outside the generic pipeline.

### `database.py`

Before persistence it verifies:

1. generated output counts;
2. historical contract path, version, and hash;
3. raw storage version;
4. receipt UUID, timestamp, and manifest hash;
5. content-addressed object path;
6. raw object size and SHA-256.

Only then does it open the write transaction.

### `demo.py`

Coordinates raw capture, validation, migration, persistence, cohort construction, and export for all registered datasets.

## Validation boundaries

### Raw boundary

Controls exact source bytes and ingestion-event integrity.

### Contract boundary

Controls intrinsic file-level validity: required values, types, vocabularies, dates, ranges, and units.

### Migration boundary

Controls database schema history: ordering, checksums, current version, no unmanaged drift, and concurrency.

### PostgreSQL boundary

Controls relational integrity: primary keys, foreign keys, constraints, and transactions.

These boundaries overlap defensively but have distinct responsibilities.

## Reproducibility model

A validation run records:

```text
run UUID
external source path
raw receipt UUID
raw received timestamp
raw receipt path + SHA-256
raw object path + SHA-256 + byte size
contract path + semantic version + SHA-256
reference date
generation timestamp
```

The database also records migration version, migration name, migration SHA-256, application version, execution type, timestamp, and duration.

## Interface layer

Raw commands:

```text
clinical-data raw-capture
clinical-data raw-verify
```

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

## Design trade-offs

### Filesystem rather than object storage

The project uses a local filesystem so the architecture can be reviewed and executed without cloud infrastructure. A production implementation would likely use versioned object storage, retention policies, IAM, encryption, and external backups.

### Content addressing rather than filename addressing

A filename is operational metadata and may repeat. SHA-256 identifies the actual bytes, enables deterministic deduplication, and exposes corruption.

### Receipt separate from object

Content identity and receipt events have different cardinalities. Separating them avoids duplicating bytes while retaining every ingestion event.

### Forward-only migrations

Reverse DDL is not automated because it may destroy data. Corrections are introduced through new migrations.

### Contracts and migrations remain separate

Contracts define accepted source data. Migrations define database structure. Neither is generated implicitly from the other.

## Extension rules

A new source format requires:

- a documented media type and storage-version compatibility decision;
- deterministic object naming;
- a safe parser after raw capture;
- tests for capture, deduplication, verification, and corruption;
- no weakening of existing receipt verification.

A new dataset still requires a contract, manifest entry, registry adapter, migration when necessary, tests, and documentation. It must not require changes to the invariant validation or persistence algorithm.

## Current limitations

The platform does not yet implement:

- historical clinical-record versioning;
- large-scale loading and benchmarks;
- external terminology services;
- production observability;
- enterprise authentication;
- PHI handling;
- certified WORM storage;
- automated backup and restore.

Immutable raw capture, executable contracts, and formal migrations improve reproducibility but do not imply production clinical readiness.
