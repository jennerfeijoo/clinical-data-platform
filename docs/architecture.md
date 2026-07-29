# Architecture

## System boundary

The repository is a portfolio-grade synthetic clinical data engineering platform under active development. It is not a clinical production system and must not receive identifiable patient data.

## End-to-end flow

```text
External CSV source
        │
        ▼
Immutable raw landing zone
        ├── content-addressed object
        └── append-only receipt
        │
        ▼
Active contract manifest
        │
        ▼
Versioned executable contract
        │
        ▼
Generic validation pipeline
        ├── valid rows
        ├── quarantine
        ├── normalized errors
        └── quality report
        │
        ▼
Formal migrations V001–V006
        │
        ▼
Lineage verification
        │
        ▼
Hybrid PostgreSQL persistence
        ├── patient snapshot + SCD2 history
        └── immutable clinical events
        │
        ▼
Versioned cohort SQL and feature export
```

## Clinical relationship model

```text
patients
   └── encounters
          ├── diagnoses
          ├── observations
          ├── medications
          └── procedures
```

The six datasets use the same raw, contract, pipeline, persistence, and audit algorithms. Dataset-specific behavior is confined to executable contracts, row builders, persistence SQL, migrations, and explicit history policies.

## Core modules

### `raw.py`

Preserves exact source bytes, derives SHA-256 content paths, creates receipt manifests, publishes atomically, prevents application-level replacement, and verifies integrity.

### `contract.py`

Loads TOML contracts, validates contract definitions, calculates contract hashes, and executes structural, categorical, temporal, type, unit, and plausible-range rules.

### `pipeline.py`

Orchestrates raw capture, parsing of the captured object, contract validation, and generation of quality outputs. It contains no dataset-specific validation path.

### `registry.py`

Maps each dataset to typed row conversion and PostgreSQL persistence SQL. Adding medications and procedures required new registry entries but no change to the generic pipeline or database orchestration.

### `migration.py`

Discovers V001–V006, checks immutable migration hashes, detects complete schema signatures, serializes migration execution with an advisory lock, and applies pending versions transactionally.

### `history.py`

Declares persistence semantics:

- patients: `scd2_snapshot`;
- encounters, diagnoses, observations, medications, procedures: `immutable_event`.

### `database.py`

Verifies processed outputs, contract lineage, raw receipt/object lineage, and then persists one complete run transactionally.

### `cohort.py`

Builds versioned analytical cohorts and records source-run lineage.

## Validation boundaries

### Raw boundary

Controls exact bytes and receipt-event integrity.

### Contract boundary

Controls intrinsic row validity: expected columns, required values, types, vocabularies, temporal order, units, and ranges.

### Registry boundary

Converts validated strings into Python/PostgreSQL types and supplies dataset-specific SQL.

### PostgreSQL boundary

Controls foreign keys, constraints, normalized record hashes, SCD2 transitions, event immutability, and transaction rollback.

A contract-valid row may still fail PostgreSQL when it references a missing parent or conflicts with an existing immutable event.

## Data and lineage identities

```text
raw object SHA-256
    → exact source bytes

raw receipt UUID + SHA-256
    → one reception event

contract path + version + SHA-256
    → exact validation rules

run UUID
    → one pipeline execution

record_sha256
    → normalized clinical business content

cohort run UUID
    → one analytical derivation
```

These identities are deliberately separate.

## Migrations

```text
V001 core schemas and patients
V002 encounters, diagnoses, observations, cohorts
V003 contract lineage
V004 raw lineage
V005 patient SCD2 and first immutable event policies
V006 medications and procedures
```

Applied migrations are not edited. Corrections require a new forward migration.

## Extension rule

A seventh clinical dataset requires:

1. sample or source adapter;
2. versioned contract and manifest entry;
3. registry row builder and persistence SQL;
4. migration and constraints;
5. explicit history policy;
6. contract, integration, migration, and conflict tests;
7. documentation.

It must not require a new validation pipeline or a parallel persistence orchestration path.

## Current limitations

The platform does not yet implement terminology reference tables, external terminology validation, complete execution-state auditing, structured logging, Synthea generation, bulk `COPY`, performance benchmarks, a second cohort, attrition/missingness reports, production security controls, or PHI handling.
