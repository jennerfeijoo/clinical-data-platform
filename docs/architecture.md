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
Formal migrations V001–V007
        │
        ▼
Terminology resolution
        ├── source-system aliases
        ├── active concepts by domain
        └── local-to-normalized mappings
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
          ├── diagnoses    → condition concept
          ├── observations → observation concept
          ├── medications  → medication concept
          └── procedures   → procedure concept
```

The six datasets use the same raw, contract, pipeline, persistence, and audit algorithms. Dataset-specific behavior remains confined to executable contracts, row builders, SQL, migrations, and explicit history policies.

## Terminology relationship model

```text
source system label
        │
        ▼
terminology.system_aliases
        │
        ▼
source concept
        │
        ├── direct normalized concept
        └── terminology.concept_mappings
                │
                ▼
            target concept
```

The source representation remains in the clinical table. `normalized_concept_id` records the resolved concept used by the local platform.

## Core modules

### `raw.py`

Preserves exact source bytes, derives SHA-256 content paths, creates receipt manifests, publishes atomically, prevents application-level replacement, and verifies integrity.

### `contract.py`

Loads TOML contracts, validates contract definitions, calculates contract hashes, and executes structural, categorical, temporal, type, unit, and plausible-range rules.

### `pipeline.py`

Orchestrates raw capture, parsing of the captured object, contract validation, and generation of quality outputs. It contains no dataset-specific validation path.

### `registry.py`

Maps each dataset to typed row conversion and PostgreSQL persistence SQL. It does not resolve terminology itself.

### `migration.py`

Discovers V001–V007, checks immutable migration hashes, detects complete schema signatures, serializes execution with an advisory lock, and applies pending versions transactionally.

### `terminology.py`

Provides typed inspection, source-code resolution, and whole-database terminology-binding validation.

### `history.py`

Declares persistence semantics:

- patients: `scd2_snapshot`;
- encounters, diagnoses, observations, medications, procedures: `immutable_event`.

### `database.py`

Verifies processed outputs, contract lineage, raw receipt/object lineage, and persists one complete run transactionally. PostgreSQL triggers resolve terminology and enforce event semantics during that transaction.

### `cohort.py`

Builds versioned analytical cohorts and records source-run lineage.

## Enforcement boundaries

### Raw boundary

Controls exact bytes and receipt-event integrity.

### Contract boundary

Controls intrinsic row validity: expected columns, required values, types, declared vocabularies, temporal order, units, and ranges.

### Terminology boundary

Controls whether a coded value has:

- a registered source-system alias;
- an installed concept;
- an active normalized target;
- the expected clinical domain.

### PostgreSQL boundary

Controls foreign keys, constraints, normalized-concept references, record hashes, SCD2 transitions, event immutability, and transaction rollback.

A contract-valid row may still fail PostgreSQL because its parent is missing, its code is unknown, its domain is wrong, or its immutable identity conflicts with existing content.

## Identity and lineage model

```text
raw object SHA-256
    → exact source bytes

raw receipt UUID + SHA-256
    → one reception event

contract path + version + SHA-256
    → exact validation rules

run UUID
    → one pipeline execution

source system + source code
    → original coded representation

normalized_concept_id
    → installed normalized concept

record_sha256
    → normalized clinical business content

cohort run UUID
    → one analytical derivation
```

These identifiers remain deliberately separate.

## Migration sequence

```text
V001 core schemas and patients
V002 encounters, diagnoses, observations, cohorts
V003 contract lineage
V004 raw lineage
V005 patient SCD2 and immutable-event policy
V006 medications and procedures
V007 minimal clinical terminology integration
```

Applied migrations are not edited. Corrections require a new forward migration.

## Terminology design trade-offs

### Preserve source codes

Normalization adds a foreign key rather than replacing source fields. This preserves source fidelity and permits later remapping.

### Strict post-V007 membership

New coded rows must exist in the installed subset. This prevents silent acceptance of unknown semantics.

### Compatible V006 upgrade

Previously accepted codes absent from the seed are imported as `unverified`. Upgrade compatibility is preserved without claiming external validation.

### Database triggers

Resolution is enforced for every writer. The trade-off is PostgreSQL-specific behavior that requires migration and integration tests.

### Small subset rather than copied releases

The repository includes only the concepts required by synthetic samples. Complete terminology lifecycle management remains outside this milestone.

## Extension rules

Adding a coded clinical field requires:

1. source contract declaration;
2. registered source-system alias;
3. concept subset entry or explicit mapping;
4. clinical-domain assignment;
5. persistence binding and foreign key;
6. unknown-code and wrong-domain tests;
7. licensing and version metadata;
8. documentation.

A new mapping must not be introduced as an undocumented string replacement in application code.

## Current limitations

The platform does not yet implement complete execution-state auditing, structured logging, terminology release importers, upstream synchronization, hierarchy traversal, UCUM normalization, FHIR terminology operations, Synthea generation, bulk `COPY`, performance benchmarks, a second cohort, production security controls, or PHI handling.
