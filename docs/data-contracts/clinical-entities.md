# Clinical entity data contracts

The bundled encounter, diagnosis, and observation datasets are synthetic and intentionally include one rejected row per dataset.

## Encounters

| Field | Type | Required | Rules |
|---|---|---:|---|
| `encounter_id` | string | yes | non-empty and unique |
| `patient_id` | string | yes | must reference a persisted patient |
| `encounter_type` | category | yes | `OUTPATIENT`, `INPATIENT`, or `EMERGENCY` |
| `start_datetime` | ISO 8601 datetime | yes | timezone required |
| `end_datetime` | ISO 8601 datetime | yes | timezone required; not before start |
| `source_system` | string | yes | non-empty |

The sample row `E008` is rejected because its end time precedes its start time.

## Diagnoses

| Field | Type | Required | Rules |
|---|---|---:|---|
| `diagnosis_id` | string | yes | non-empty and unique |
| `patient_id` | string | yes | must reference a persisted patient |
| `encounter_id` | string | yes | must reference a persisted encounter |
| `code_system` | category | yes | `ICD10` or `SNOMED` |
| `diagnosis_code` | string | yes | non-empty |
| `diagnosis_datetime` | ISO 8601 datetime | yes | timezone required |
| `source_system` | string | yes | non-empty |

The sample row `D007` is rejected because it uses an unsupported vocabulary and has an empty diagnosis code.

## Observations

| Code | Unit | Plausible range |
|---|---|---:|
| `SYSTOLIC_BP` | `mmHg` | 50–300 |
| `DIASTOLIC_BP` | `mmHg` | 30–200 |
| `HEART_RATE` | `bpm` | 20–250 |

All observation fields are required: `observation_id`, `patient_id`, `encounter_id`, `observation_code`, `value_numeric`, `unit`, `observed_at`, and `source_system`.

The sample row `O014` is rejected because a systolic pressure of 500 mmHg is outside the configured plausibility range.

## Referential integrity

File validation checks intrinsic row quality. PostgreSQL enforces relationships between patients, encounters, diagnoses, and observations during transactional loading. This separation makes the distinction between row-level validation and cross-table integrity explicit.
