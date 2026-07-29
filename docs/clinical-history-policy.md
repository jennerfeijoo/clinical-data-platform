# Clinical history policy

## Scope

The platform uses a hybrid persistence model rather than treating every clinical entity as a mutable snapshot.

| Dataset | Policy | Current storage | Historical behavior |
|---|---|---|---|
| patients | SCD Type 2 snapshot | `clinical.patients` | business changes append versions to `clinical.patient_history` |
| encounters | immutable event | `clinical.encounters` | exact duplicates are no-ops; conflicting identity reuse is rejected |
| diagnoses | immutable event | `clinical.diagnoses` | exact duplicates are no-ops; conflicting identity reuse is rejected |
| observations | immutable event | `clinical.observations` | exact duplicates are no-ops; conflicting identity reuse is rejected |
| medications | immutable event | `clinical.medications` | exact duplicates are no-ops; conflicting identity reuse is rejected |
| procedures | immutable event | `clinical.procedures` | exact duplicates are no-ops; conflicting identity reuse is rejected |

The policy is declared in `clinical_data_platform.history`. Migration V005 introduced patient SCD2 and the first immutable-event guards; V006 extends the immutable-event policy to medications and procedures.

## Patient snapshot semantics

`clinical.patients` contains the latest accepted demographic snapshot. Each row has a `record_sha256` calculated from patient identifier, sex at birth, birth date, death date, and source system. Lineage fields are excluded.

When the business hash changes:

1. the current history version is closed;
2. `valid_to` and `valid_to_run_id` identify the transition;
3. a new current version is inserted;
4. `clinical.patients` retains only the latest snapshot.

An identical patient snapshot may refresh current-run lineage without creating another historical version.

## Immutable-event semantics

Encounter, diagnosis, observation, medication, and procedure identifiers represent source event identity. PostgreSQL calculates a business-record SHA-256 before insert or update.

On identity conflict:

- if the incoming business hash matches the stored hash, the original event and original lineage are preserved;
- if the incoming hash differs, PostgreSQL raises an integrity error and the complete dataset-load transaction rolls back.

Corrections therefore require a new event identifier or a future explicit correction/supersession model. Silent mutation is not allowed.

## Medication event content

The medication business hash includes:

- medication, patient, and encounter identifiers;
- code system and medication code;
- status;
- start and optional end timestamps;
- optional dose value and unit;
- optional route;
- source system.

Database constraints require start time not to exceed end time, a positive dose when supplied, and a dose unit whenever a dose value exists.

## Procedure event content

The procedure business hash includes:

- procedure, patient, and encounter identifiers;
- code system and procedure code;
- procedure timestamp;
- status;
- source system.

## Record hashes

`record_sha256` identifies normalized business content after contract validation and typed conversion. It is different from:

- `source_sha256`: complete raw source file;
- `raw_manifest_sha256`: receipt manifest;
- `contract_sha256`: executed data contract.

## Migration sequence

```text
V004 raw lineage
    → V005 patient history + immutable encounters/diagnoses/observations
    → V006 immutable medications/procedures
```

V006 creates both new tables, their hash functions, guard triggers, indexes, foreign keys, and constraints.

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

Medication events:

```sql
SELECT
    medication_id,
    patient_id,
    encounter_id,
    code_system,
    medication_code,
    status,
    start_datetime,
    end_datetime,
    dose_value,
    dose_unit,
    route,
    record_sha256,
    source_run_id
FROM clinical.medications
ORDER BY patient_id, start_datetime;
```

Procedure events:

```sql
SELECT
    procedure_id,
    patient_id,
    encounter_id,
    code_system,
    procedure_code,
    procedure_datetime,
    status,
    record_sha256,
    source_run_id
FROM clinical.procedures
ORDER BY patient_id, procedure_datetime;
```

## Boundaries

This implementation does not yet model deletion/tombstones, formal source corrections, bitemporal valid time, patient identity merges, event supersession, or bulk `COPY` merge semantics. Those require explicit domain rules and must not be inferred from a generic upsert.
