# Architecture

## System boundary

The repository is progressing toward a portfolio-grade clinical data platform. It operates only on synthetic data and is not a clinical production system.

## Architectural objective

Source preservation, data acceptance, schema evolution, historical semantics, persistence, and analytical derivation must be explicit and independently reviewable.

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
Hybrid clinical persistence
    ├── current patient snapshot + SCD2 history
    └── immutable clinical events
    │
    ▼
Versioned cohort SQL
```

The generic pipeline contains no patient-specific validation path. Database creation contains no monolithic `schema.sql` path.

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
        ├── SCD2 patient transitions
        └── immutable-event conflict checks
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

Objects model byte content. Receipts model ingestion events. Identical bytes share an object while retaining distinct receipt manifests.

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
├── V004__add_raw_landing_lineage.sql
└── V005__add_clinical_history_policy.sql
```

History is stored in `public.schema_migrations`. V005 adds record hashes, patient history, and immutable-event guards.

## Clinical persistence model

### Patients

```text
clinical.patients
    → current accepted snapshot

clinical.patient_history
    → SCD Type 2 versions
```

A business-content change closes the current history version and inserts a new one. An identical patient snapshot may refresh current-run lineage without creating another historical version.

### Encounters, diagnoses, and observations

These tables model immutable source events.

```text
same identifier + same normalized content
    → no-op; preserve original event lineage

same identifier + different normalized content
    → integrity error; rollback dataset transaction
```

The policy is declared in `history.py` and enforced by PostgreSQL triggers installed by V005.

## Hash model

```text
source_sha256
    → complete raw source object

raw_manifest_sha256
    → receipt manifest bytes

contract_sha256
    → executable contract bytes

record_sha256
    → normalized business content of one clinical row
```

Run lineage and load timestamps are excluded from `record_sha256`, preventing repeated receipt of identical clinical content from becoming a false business change.

Event timestamps are normalized to UTC before hashing.

## Core modules

### `raw.py`

Preserves and verifies exact source bytes. It does not parse clinical fields or connect to PostgreSQL.

### `contract.py`

Parses versioned TOML contracts, validates contract consistency, executes structural and clinical rules, and returns normalized validation results.

### `pipeline.py`

Enforces:

```text
capture raw
→ read raw object
→ execute active contract
→ write quality outputs
```

### `migration.py`

Discovers V001–V005, validates immutable checksums and complete schema signatures, serializes migrations with an advisory lock, and applies pending migrations transactionally.

### `history.py`

Declares which datasets use:

```text
scd2_snapshot
immutable_event
```

It documents policy intent; PostgreSQL remains the enforcement boundary.

### `registry.py`

Keeps typed row conversion and dataset-specific SQL outside the generic pipeline.

### `database.py`

Verifies output counts, historical contract lineage, raw receipts, raw objects, and then persists one complete validation run transactionally.

### `demo.py`

Coordinates raw capture, validation, migration, persistence, cohort construction, and export for all registered datasets.

## Validation and enforcement boundaries

### Raw boundary

Controls exact source bytes and ingestion-event integrity.

### Contract boundary

Controls intrinsic file-level validity: required values, types, vocabularies, dates, ranges, and units.

### Migration boundary

Controls database schema history: ordering, checksums, current version, no unmanaged drift, and concurrency.

### History boundary

Controls whether normalized records are snapshots or immutable events, and how duplicate identities are treated.

### PostgreSQL boundary

Controls primary keys, foreign keys, constraints, triggers, hashes, and transaction rollback.

## Reproducibility model

A validation run records raw, contract, temporal, and quality lineage. Clinical rows record source lineage and `record_sha256`. Patient history records the run that opened each version and the run that closed it.

The database also records migration version, migration name, migration SHA-256, application version, execution type, timestamp, and duration.

## Design trade-offs

### Hybrid history rather than universal upsert

Patient demographics are mutable dimensions. Encounters, diagnoses, and observations are treated as events. Applying one mutation policy to both would hide domain semantics.

### Triggers rather than application-only history

Database triggers enforce the policy for every writer using the tables. The cost is additional PostgreSQL-specific behavior that must be tested and documented.

### Current table plus patient history

A separate current snapshot simplifies operational and cohort queries, while the history table preserves prior states. This is not full bitemporal modelling.

### Conservative event corrections

Conflicting reuse of an event identifier is rejected rather than guessed. Future correction or supersession semantics require an explicit domain model.

### Forward-only migrations

Reverse DDL is not automated because it may destroy data. Corrections are introduced through new migrations.

## Extension rules

A new clinical entity requires:

- a versioned contract and manifest entry;
- a registry adapter;
- an explicit history policy;
- a migration for tables, hashes, and enforcement;
- tests for duplicates and conflicting identities;
- documentation.

A new history mode must not be introduced as an undocumented variation of `ON CONFLICT DO UPDATE`.

## Current limitations

The platform does not yet implement:

- medications and procedures;
- tombstones or formal correction messages;
- bitemporal valid time;
- patient identity merge/split semantics;
- bulk staging and `COPY`;
- large-scale benchmarks;
- external terminology services;
- production observability;
- PHI handling or certified WORM storage.

The implemented history policy improves auditability but does not imply production clinical readiness.
