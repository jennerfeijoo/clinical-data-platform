# Clinical history policy

## Scope

The platform uses a hybrid persistence model rather than treating every clinical entity as a mutable snapshot.

| Dataset | Policy | Current storage | Historical behavior |
|---|---|---|---|
| patients | SCD Type 2 snapshot | `clinical.patients` | business changes append versions to `clinical.patient_history` |
| encounters | immutable event | `clinical.encounters` | exact duplicates are no-ops; conflicting identity reuse is rejected |
| diagnoses | immutable event | `clinical.diagnoses` | exact duplicates are no-ops; conflicting identity reuse is rejected |
| observations | immutable event | `clinical.observations` | exact duplicates are no-ops; conflicting identity reuse is rejected |

The policy is declared in `clinical_data_platform.history` and enforced in PostgreSQL by migration V005.

## Patient snapshot semantics

`clinical.patients` contains the latest accepted demographic snapshot. Each row has a `record_sha256` calculated from:

- patient identifier;
- sex at birth;
- birth date;
- death date;
- source system.

Lineage fields such as `source_run_id`, source-file SHA-256, and load timestamp are excluded from the business-record hash.

When a patient is first inserted, a current row is added to `clinical.patient_history`. When the business hash changes:

1. the current history version is closed;
2. `valid_to` and `valid_to_run_id` identify the transition;
3. a new current version is inserted;
4. `clinical.patients` retains only the latest snapshot.

An identical patient snapshot may refresh current-run lineage without creating another historical version.

## Immutable-event semantics

Encounter, diagnosis, and observation identifiers represent source event identity. PostgreSQL computes a business-record SHA-256 before insert or update.

On identity conflict:

- if the incoming business hash matches the stored hash, the original event and its original lineage are preserved;
- if the incoming business hash differs, PostgreSQL raises an integrity error and the dataset-load transaction rolls back.

Corrections must therefore arrive with a new event identifier or through a future explicitly modelled correction/version mechanism. Silent mutation of a previously accepted event is not permitted.

## Record hashes

`record_sha256` identifies normalized business content after contract validation and typed conversion. It is different from:

- `source_sha256`, which identifies the complete raw source file;
- `raw_manifest_sha256`, which identifies the receipt manifest;
- `contract_sha256`, which identifies the executed data contract.

## Migration

V005 adds:

- PostgreSQL `pgcrypto` for SHA-256 calculation;
- `record_sha256` to all current clinical tables;
- `clinical.patient_history`;
- SCD Type 2 patient triggers;
- immutable-event guard triggers;
- indexes and table comments.

Upgrade behavior:

```text
V004 current tables
    → calculate hashes for existing rows
    → create one current patient-history version per existing patient
    → install history and immutability triggers
    → V005
```

## Queries

Current patient snapshot:

```sql
SELECT *
FROM clinical.patients
ORDER BY patient_id;
```

Complete patient history:

```sql
SELECT
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    record_sha256,
    valid_from_run_id,
    valid_to_run_id,
    valid_from,
    valid_to,
    is_current
FROM clinical.patient_history
ORDER BY patient_id, patient_version_id;
```

Patients with more than one historical version:

```sql
SELECT patient_id, COUNT(*) AS version_count
FROM clinical.patient_history
GROUP BY patient_id
HAVING COUNT(*) > 1
ORDER BY version_count DESC, patient_id;
```

Event hashes and original lineage:

```sql
SELECT
    encounter_id,
    patient_id,
    record_sha256,
    source_run_id,
    loaded_at
FROM clinical.encounters
ORDER BY encounter_id;
```

## Boundaries

This implementation does not yet model:

- deletion/tombstone events;
- source-system correction messages;
- bitemporal valid time versus system time;
- merge/split patient identities;
- late-arriving event supersession;
- bulk `COPY` merge logic.

Those require explicit domain semantics and must not be inferred from a generic upsert.
