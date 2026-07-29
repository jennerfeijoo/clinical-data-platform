# Six clinical entities

## Scope

The platform models six synthetic clinical datasets:

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

Required relationship: patient.

### Diagnoses

Represents one coded diagnosis event associated with a patient and encounter.

Primary key: `diagnosis_id`.

Contract-level systems: `ICD10`, `SNOMED`.

Persistence requires an active normalized concept in the `condition` domain.

### Observations

Represents one numeric clinical measurement.

Primary key: `observation_id`.

The current sample supports systolic blood pressure, diastolic blood pressure, and heart rate with code-specific units and plausible ranges.

Local observation codes are preserved and mapped to LOINC concepts during persistence.

### Medications

Represents one medication event with coded medication identity, status, timing, optional dose, and optional route.

Primary key: `medication_id`.

Contract-level systems: `RXNORM`, `ATC`.

Statuses: `ACTIVE`, `COMPLETED`, `STOPPED`.

The contract checks start/end order. PostgreSQL additionally requires dose consistency, parent relationships, an active `medication` concept, record hashing, and event immutability.

### Procedures

Represents one coded procedure event associated with a patient and encounter.

Primary key: `procedure_id`.

Contract-level systems: `SNOMED`, `CPT`, `ICD10PCS`.

Statuses: `COMPLETED`, `IN_PROGRESS`, `NOT_DONE`.

Persistence requires an active normalized concept in the `procedure` domain.

## Persistence semantics

| Entity | Persistence policy | Terminology binding |
|---|---|---|
| patients | current snapshot plus SCD Type 2 history | none |
| encounters | immutable event | none |
| diagnoses | immutable event | condition concept |
| observations | immutable event | observation concept |
| medications | immutable event | medication concept |
| procedures | immutable event | procedure concept |

For immutable events, an exact duplicate is a no-op. Reusing the same identifier with different business content raises an integrity error and rolls back the complete dataset load.

## Contract, terminology, and database boundaries

Contracts validate intrinsic row properties such as required values, data types, categorical vocabularies, temporal order, and measurement ranges.

The terminology layer validates whether a declared system and code resolve to an active concept in the expected domain.

PostgreSQL additionally validates foreign keys, dose pairing, record hashes, event immutability, and transaction rollback.

A row may therefore pass its executable contract but fail persistence because:

- its parent does not exist;
- its code is unknown to the installed subset;
- its normalized concept has the wrong domain;
- its event identifier conflicts with accepted content.

## Source and normalized code examples

| Entity | Source representation | Normalized representation |
|---|---|---|
| diagnosis D002 | `ICD10:I10` | `ICD10CM:I10` |
| observation O001 | `LOCAL_OBSERVATION:SYSTOLIC_BP` | `LOINC:8480-6` |
| medication M001 | `RXNORM:197361` | `RXNORM:197361` |
| procedure PR001 | `SNOMED:386053000` | `SNOMEDCT:386053000` |

Aliases canonicalize system names. Concept mappings may additionally change the code and system, as in the local-observation-to-LOINC mappings.

## Bundled sample

| Dataset | Received | Valid | Invalid | Persisted |
|---|---:|---:|---:|---:|
| patients | 8 | 5 | 3 | 5 |
| encounters | 8 | 7 | 1 | 7 |
| diagnoses | 7 | 6 | 1 | 6 |
| observations | 14 | 13 | 1 | 13 |
| medications | 7 | 6 | 1 | 6 |
| procedures | 7 | 6 | 1 | 6 |

The four coded event tables produce 31 normalized terminology bindings.

All values are synthetic. External terminology entries are small local subsets rather than complete releases.

## Review queries

Entity counts:

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

Normalized coded events:

```sql
SELECT
    dataset_name,
    entity_id,
    source_system,
    source_code,
    normalized_system,
    normalized_code,
    normalized_display,
    domain,
    verification_status
FROM terminology.normalized_clinical_codes
ORDER BY dataset_name, entity_id;
```

## Current boundary

The six-entity model and its minimal terminology bindings are implemented. The next roadmap milestone introduces complete execution states and structured logging.

The terminology subset still lacks release importers, automatic synchronization, hierarchy queries, UCUM normalization, multilingual designations, contextual many-to-many mappings, and FHIR terminology operations.
