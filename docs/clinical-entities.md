# Six clinical entities

## Scope

The platform now models six synthetic clinical datasets:

1. patients;
2. encounters;
3. diagnoses;
4. observations;
5. medications;
6. procedures.

The model is intentionally compact. It demonstrates clinical data engineering boundaries without claiming complete EHR, FHIR, OMOP, or terminology-service coverage.

## Relationship model

```text
patients
   └── encounters
          ├── diagnoses
          ├── observations
          ├── medications
          └── procedures
```

Every event table references both a patient and an encounter. PostgreSQL foreign keys reject orphaned events.

## Entity responsibilities

### Patients

Represents the latest accepted demographic snapshot. Historical changes are retained in `clinical.patient_history` through SCD Type 2 semantics.

Primary key: `patient_id`.

### Encounters

Represents a time-bounded contact with the clinical system.

Primary key: `encounter_id`.

Required relationships: patient.

### Diagnoses

Represents one coded diagnosis event associated with a patient and encounter.

Primary key: `diagnosis_id`.

Code systems currently accepted by the contract: `ICD10`, `SNOMED`.

### Observations

Represents one numeric clinical measurement.

Primary key: `observation_id`.

The current sample supports systolic blood pressure, diastolic blood pressure, and heart rate with code-specific units and plausible ranges.

### Medications

Represents one medication event with coded medication identity, status, timing, optional dose, and optional route.

Primary key: `medication_id`.

Contract-level code-system values: `RXNORM`, `ATC`.

Statuses: `ACTIVE`, `COMPLETED`, `STOPPED`.

The contract checks start/end order. PostgreSQL additionally requires a positive dose and a non-empty unit when dose information is supplied.

### Procedures

Represents one coded procedure event associated with a patient and encounter.

Primary key: `procedure_id`.

Contract-level code-system values: `SNOMED`, `CPT`, `ICD10PCS`.

Statuses: `COMPLETED`, `IN_PROGRESS`, `NOT_DONE`.

## Persistence semantics

| Entity | Persistence policy |
|---|---|
| patients | current snapshot plus SCD Type 2 history |
| encounters | immutable event |
| diagnoses | immutable event |
| observations | immutable event |
| medications | immutable event |
| procedures | immutable event |

For immutable events, an exact duplicate is a no-op. Reusing the same identifier with different business content raises an integrity error and rolls back the complete dataset load.

## Contract and database boundaries

Contracts validate intrinsic row properties such as required values, data types, categorical vocabularies, temporal order, and measurement ranges.

PostgreSQL validates relational and persistence properties such as foreign keys, dose pairing, positive dose, record hashes, event immutability, and transaction rollback.

A row may therefore pass its executable contract but still fail persistence when it references a missing parent or conflicts with an already accepted event identifier.

## Bundled sample

| Dataset | Received | Valid | Invalid |
|---|---:|---:|---:|
| patients | 8 | 5 | 3 |
| encounters | 8 | 7 | 1 |
| diagnoses | 7 | 6 | 1 |
| observations | 14 | 13 | 1 |
| medications | 7 | 6 | 1 |
| procedures | 7 | 6 | 1 |

All values are synthetic. Codes are illustrative identifiers accepted by the local contract; the repository does not claim semantic validation against complete external terminology releases.

## Review queries

```sql
SELECT 'patients' AS dataset, COUNT(*) FROM clinical.patients
UNION ALL
SELECT 'encounters', COUNT(*) FROM clinical.encounters
UNION ALL
SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
UNION ALL
SELECT 'observations', COUNT(*) FROM clinical.observations
UNION ALL
SELECT 'medications', COUNT(*) FROM clinical.medications
UNION ALL
SELECT 'procedures', COUNT(*) FROM clinical.procedures
ORDER BY dataset;
```

Expected counts after a clean demo are 5, 7, 6, 13, 6, and 6 respectively.

## Current boundary

The next milestone introduces terminology normalization. Until then, `code_system` is required and constrained, but codes are not mapped to reference tables, versioned terminology releases, standard concepts, or semantic equivalence groups.
