# Architecture

## System boundary

The repository is a portfolio-grade synthetic clinical data engineering platform under active development. It is not a clinical production system and must not receive identifiable patient data.

## End-to-end flow

```text
Pinned Synthea profile
    ├── upstream tag and resolved commit
    ├── random and clinician seeds
    ├── reference date and geography
    ├── single-thread generation
    └── exact exporter configuration
            │
            ▼
Synthea CSV generation
    ├── exact v4.0.0 headers
    ├── per-file SHA-256
    └── generation manifest and dataset fingerprint
            │
            ▼
Deterministic adapter
    ├── six contract-ready datasets
    ├── UUIDv5 event identities
    ├── explicit omitted-row counts
    ├── unverified terminology candidates
    └── adaptation manifest and fingerprint
            │
            └──────────────┐
                           ▼
CLI command or external CSV source
    ├── stdout: requested command result
    └── stderr: structured operational logs
            │
            └── correlation_id propagated through nested operations
                           │
                           ▼
Immutable raw landing zone
    ├── content-addressed object
    └── append-only receipt
                           │
                           ▼
Versioned executable contract
                           │
                           ▼
Hash-chained local execution journal
                           │
                           ▼
Generic validation pipeline
    ├── valid rows
    ├── quarantine
    ├── normalized errors
    └── quality report: validated
                           │
                           ▼
Formal migrations V001–V008
                           │
                           ▼
Durable execution audit
    ├── current-state projection
    ├── ordered event timeline
    └── failure retained after clinical rollback
                           │
                           ▼
Terminology resolution
                           │
                           ▼
Hybrid PostgreSQL persistence
    ├── patient snapshot + SCD2 history
    └── immutable clinical events
                           │
                           ▼
Versioned cohort SQL and feature export
```

Synthea is a source workflow, not a parallel data platform. Adapted files enter the same raw, contract, execution, terminology, persistence, audit, and logging layers as any other source.

## Synthea reproducibility model

### Profile identity

The packaged TOML profile has its own SHA-256 and pins:

```text
upstream repository
release tag
upstream version
minimum Java version
population size
random seed
clinician seed
reference date
state and optional city
thread pool size
history window
included CSV files
```

The resolved upstream commit is recorded after checkout verification. The checkout must match the configured tag exactly and contain no uncommitted changes.

### Generation identity

```text
profile SHA-256
+ upstream commit
+ source file hashes, sizes, counts, and headers
→ dataset fingerprint
```

The generation manifest records the normalized command with machine-specific directories replaced by placeholders. Individual source hashes identify the actual bytes.

### Adaptation identity

```text
adapter version
+ profile SHA-256
+ source fingerprints
+ output fingerprints
+ omitted-row reasons
→ adaptation fingerprint
```

The output manifest makes post-adaptation modification detectable.

### Deterministic event identities

Synthea CSV rows without a source event ID receive UUIDv5 identifiers derived from a fixed namespace, dataset, source file, source row number, and canonical row content.

These UUIDs are deterministic technical identities for one adapter version. They are not universal clinical identifiers.

### Source schema boundary

The adapter requires exact Synthea 4.0.0 headers for:

```text
patients.csv
encounters.csv
conditions.csv
observations.csv
medications.csv
procedures.csv
```

Schema drift fails before row transformation. A new upstream schema requires explicit adapter review and versioning.

### Observation subset

The current internal observation contract accepts only systolic blood pressure, diastolic blood pressure, and heart rate. Other Synthea observations are omitted with reason counts. This prevents silent conversion of a broad upstream observation model into a narrow internal model.

### Terminology boundary

The adapter emits terminology candidates used by diagnoses, medications, and procedures. During loading:

- existing concepts are reused;
- missing concepts are added to registered canonical systems;
- imported concepts are marked `unverified`;
- domain conflicts are rejected.

This supports source ingestion without claiming complete or independently verified terminology coverage.

## Clinical relationship model

```text
patients
   └── encounters
          ├── diagnoses    → condition concept
          ├── observations → observation concept
          ├── medications  → medication concept
          └── procedures   → procedure concept
```

The six datasets use the same core algorithms. Dataset-specific behavior remains confined to contracts, adapters, row builders, SQL, migrations, terminology bindings, and explicit history policies.

## Execution state model

```text
created
→ raw_captured
→ validating
→ validated
→ loading
→ completed
```

Active stages may transition to `failed`. A failed load may retry through `failed → loading`; `completed` is terminal.

The architecture uses two audit representations:

```text
local JSONL journal
    → covers initialization, raw capture, and validation

PostgreSQL event timeline
    → imports the local journal
    → adds loading, failure, retry, and completion
```

Both are linked by SHA-256 event chains.

## Transaction topology

```text
Transaction A
    validated run registration
    + local journal import
    + loading acquisition
    → COMMIT

Transaction B
    clinical rows
    + validation errors
    + completed event
    → COMMIT or ROLLBACK together

Transaction C, only after B fails
    failed event
    + failure metadata
    → COMMIT
```

This prevents partial clinical data while preserving durable failure evidence.

## Observability model

```text
clinical and analytical data
    → domain records and derived features

execution audit
    → authoritative state, attempts, timestamps, and durable failures

structured logs
    → operational telemetry, timing, context, and diagnostics
```

A `correlation_id` represents one observable invocation. A dataset `run_id` remains the durable execution identity. `contextvars` propagates contextual fields without changing domain function signatures.

Measured operations produce:

```text
<event>.started
<event>.completed
```

or:

```text
<event>.started
<event>.failed
```

Logs contain aggregate counts, hashes, versions, stages, and sanitized technical errors. They must not contain clinical rows.

## Core modules

### `synthea.py`

Loads and validates the pinned profile, builds the shell-free generator command, verifies the clean tagged checkout and Java version, fingerprints upstream files, adapts the six CSVs, generates UUIDv5 identities, records omitted rows, creates terminology candidates, verifies manifests, and loads adapted datasets through the existing platform.

### `synthea_profiles/`

Contains packaged, versioned generation profiles included in the Python distribution.

### `entrypoint.py`

Configures logging before CLI dispatch and creates command correlation context.

### `structured_logging.py`

Defines schema versioning, formatters, environment configuration, context propagation, timing, exception normalization, and defensive redaction.

### `raw.py`

Preserves exact source bytes, creates content-addressed objects and receipt manifests, and verifies integrity.

### `contract.py`

Loads TOML contracts and executes structural, categorical, temporal, type, unit, and range rules.

### `execution.py`

Defines lifecycle states, permitted transitions, canonical event hashing, local JSONL journals, and chain validation.

### `pipeline.py`

Orchestrates raw capture, contract validation, quality outputs, local execution events, and structured logs. Success means `validated`, not yet `completed`.

### `run_audit.py`

Registers validated runs, imports local events, acquires attempts, records completion or failure, supports retries, and validates durable chains.

### `registry.py`

Maps datasets to typed conversion and persistence SQL. It is independent of the source adapter.

### `migration.py`

Discovers V001–V008, verifies migration history, detects schema signatures, locks execution, and applies pending versions transactionally.

### `terminology.py`

Provides terminology inspection, resolution, and binding validation.

### `database.py`

Verifies outputs and lineage, then coordinates audit and clinical transactions.

### `cohort.py`

Builds versioned analytical cohorts and records source-run lineage.

## Enforcement boundaries

### Generation boundary

Controls profile completeness, tag and commit identity, clean checkout, Java requirement, command inputs, exact source headers, and source fingerprints.

### Adapter boundary

Controls deterministic transformation, parent relationships, supported subsets, stable event identities, explicit omissions, terminology candidates, output contracts, and output fingerprints.

### Raw boundary

Controls exact bytes and receipt integrity.

### Contract boundary

Controls intrinsic row validity: columns, required values, types, vocabularies, temporal order, units, and ranges.

### Execution boundary

Controls lifecycle transitions, attempts, timestamps, failure metadata, hashes, and agreement between history and current state.

### Observability boundary

Controls log schema, contextual fields, severity, timing, sanitization, and stderr/stdout separation. It does not establish durability.

### Terminology boundary

Controls source aliases, installed concepts, active targets, and clinical domain.

### PostgreSQL boundary

Controls foreign keys, constraints, terminology references, record hashes, SCD2 transitions, immutable conflicts, and transaction rollback.

## Identity and lineage model

```text
profile SHA-256
    → exact Synthea generation controls

upstream commit
    → exact generator source identity

generation dataset fingerprint
    → exact upstream CSV set

adaptation fingerprint
    → exact adapter inputs, outputs, and omission policy

correlation UUID
    → one observable invocation

raw object SHA-256
    → exact ingested source bytes

raw receipt UUID + SHA-256
    → one reception event

contract path + version + SHA-256
    → exact validation rules

run UUID
    → one logical execution across retries

record_sha256
    → normalized clinical business content

normalized_concept_id
    → installed normalized concept

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
V008 complete execution lifecycle and failure audit
```

Synthea and logging do not require V009 because they do not alter persistent database structure.

## Design trade-offs

### Full generation outside normal CI

The standard CI validates profile packaging, schema pinning, deterministic adaptation, manifests, terminology import, and PostgreSQL loading with a small fixture. It does not clone and run the Java generator on every pull request, avoiding network and Gradle dependence in the fast test path.

### Single thread over generation speed

A single generator thread prioritizes stable ordering and identifiers over throughput. Benchmark generation may later use a separate performance profile with weaker byte-level reproducibility claims.

### Explicit omission over broad coercion

The adapter reports unsupported observations and other excluded rows. It does not invent mappings to make every upstream record fit a narrow contract.

### Unverified terminology over false confidence

Unknown Synthea concepts are retained as `unverified` rather than rejected solely because the local catalog is small or described as verified without evidence.

### Logging is not auditing

Logs support diagnosis and aggregation. Audit records enforce durable state consistency. Combining them would make the audit dependent on optional log transport.

### Hashes expose, not prevent, modification

Manifests and event chains are tamper-evident. They do not replace access control or WORM storage.

## Current limitations

The platform does not yet implement bulk PostgreSQL `COPY`, performance benchmarks on large Synthea populations, centralized log transport, OpenTelemetry, metrics, dashboards, scheduler recovery, complete terminology importers, UCUM normalization, a second cohort, production security controls, PHI handling, or epidemiological validity claims.
