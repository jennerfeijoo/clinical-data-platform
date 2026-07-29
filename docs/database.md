# PostgreSQL migrations and persistence

## Responsibility split

```text
raw.py
    → exact source bytes and receipt integrity

contract.py
    → source-row acceptance rules

migration.py
    → ordered database structure

history.py
    → declared snapshot/event semantics

registry.py
    → typed row conversion and dataset SQL

database.py
    → lineage verification and transactional loading

PostgreSQL
    → foreign keys, constraints, hashes, history, immutability
```

## Migration history

```text
V001 core schemas and patients
V002 encounters, diagnoses, observations, cohorts
V003 contract lineage
V004 raw lineage
V005 patient SCD2 and immutable-event enforcement
V006 medications and procedures
```

`public.schema_migrations` stores version, name, checksum, application version, execution type, timestamp, and duration. Applied files are immutable.

## V006

V006 adds:

- `clinical.medications`;
- `clinical.procedures`;
- normalized record-hash functions;
- immutable-event triggers;
- patient and encounter foreign keys;
- temporal, categorical, dose, and non-empty-value constraints;
- patient, encounter, code, and time indexes;
- complete V006 schema detection for baseline and drift checks.

## Six current clinical tables

```text
clinical.patients
clinical.encounters
clinical.diagnoses
clinical.observations
clinical.medications
clinical.procedures
```

`clinical.patient_history` separately stores patient SCD Type 2 versions.

## Medication constraints

PostgreSQL enforces:

- patient and encounter existence;
- `RXNORM` or `ATC` as the declared system name;
- `ACTIVE`, `COMPLETED`, or `STOPPED` status;
- end time not earlier than start time;
- positive dose when present;
- dose value and unit supplied together;
- supported route when present;
- non-empty source and code;
- immutable identity/content behavior.

## Procedure constraints

PostgreSQL enforces:

- patient and encounter existence;
- `SNOMED`, `CPT`, or `ICD10PCS` as the declared system name;
- `COMPLETED`, `IN_PROGRESS`, or `NOT_DONE` status;
- non-empty code and source;
- immutable identity/content behavior.

These checks do not prove that an individual code exists in an official terminology release.

## Pre-transaction verification

Before database writes, the loader verifies:

1. output counts and completed status;
2. dataset identity;
3. retained contract path, version, and SHA-256;
4. raw storage version;
5. receipt UUID, timestamp, path, and manifest hash;
6. raw object path, byte size, and SHA-256;
7. parseable run metadata.

Only then does it open the transaction.

## Transaction behavior

One load writes:

```text
audit.pipeline_runs
+ valid clinical rows
+ validation errors
+ SCD2 transitions or immutable-event checks
```

All operations commit or roll back together.

### Exact immutable-event duplicate

```text
same identifier
+ same normalized business hash
→ trigger returns stored row
→ original source_run_id remains
```

### Conflicting immutable-event identity

```text
same identifier
+ different normalized business hash
→ integrity error
→ complete load rollback
→ original event remains unchanged
```

## Record hashes

`record_sha256` identifies normalized business content. It excludes:

```text
source_run_id
source_sha256
loaded_at
```

These fields describe ingestion lineage rather than clinical meaning.

## Upgrade example

```powershell
clinical-data database-migrate --target-version 5
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

At V005, medication and procedure tables do not exist. The final command applies V006 and validates `detected=6`, `current=6`, and `latest=6`.

## Review queries

Migration history:

```sql
SELECT version, name, checksum, execution_type, application_version, applied_at
FROM public.schema_migrations
ORDER BY version;
```

Entity counts:

```sql
SELECT 'patients' AS dataset, COUNT(*) FROM clinical.patients
UNION ALL SELECT 'encounters', COUNT(*) FROM clinical.encounters
UNION ALL SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
UNION ALL SELECT 'observations', COUNT(*) FROM clinical.observations
UNION ALL SELECT 'medications', COUNT(*) FROM clinical.medications
UNION ALL SELECT 'procedures', COUNT(*) FROM clinical.procedures
ORDER BY dataset;
```

Medication lineage:

```sql
SELECT
    medication_id,
    patient_id,
    encounter_id,
    record_sha256,
    source_run_id,
    loaded_at
FROM clinical.medications
ORDER BY medication_id;
```

Procedure lineage:

```sql
SELECT
    procedure_id,
    patient_id,
    encounter_id,
    record_sha256,
    source_run_id,
    loaded_at
FROM clinical.procedures
ORDER BY procedure_id;
```

## Limits

The database layer does not yet provide terminology reference tables, event supersession, tombstones, bitemporal modelling, bulk staging/`COPY`, production access controls, or PHI-ready governance.
