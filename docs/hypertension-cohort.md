# Hypertension cohort specification

## Purpose

Create a reproducible adult hypertension cohort and a compact baseline feature table from the normalized clinical model.

## Definition version

`hypertension-v1`

## Index event

The index date is the earliest persisted diagnosis date where:

- `code_system = 'ICD10'`; and
- `diagnosis_code LIKE 'I10%'`.

## Inclusion criteria

1. Age at index is at least 18 years.
2. The patient is alive on the index date or has no recorded death date.
3. Both systolic and diastolic blood pressure are available within the configured baseline window.
4. At least the configured number of follow-up days is available after index.

Default parameters:

| Parameter | Default |
|---|---:|
| Minimum age | 18 years |
| Baseline window | ±30 days around index |
| Minimum follow-up | 30 days |

## Baseline blood pressure selection

For each patient and blood-pressure component, the workflow selects the measurement nearest to the index date. Ties are resolved by observation timestamp and observation identifier, making the selection deterministic.

## Feature table

| Variable | Definition |
|---|---|
| `patient_id` | persisted pseudonymous patient identifier |
| `index_date` | earliest qualifying hypertension diagnosis date |
| `age_at_index` | completed years on index date |
| `sex_at_birth` | value from the patient table |
| `baseline_systolic_bp` | nearest valid systolic measurement in the baseline window |
| `baseline_diastolic_bp` | nearest valid diastolic measurement in the baseline window |
| `prior_encounter_count_365d` | encounters in the 365 days before index |
| `prior_diagnosis_count_365d` | diagnoses in the 365 days before index |
| `follow_up_days` | days from index to the latest persisted clinical event |

## Expected bundled-sample result

The default sample produces two included patients:

| Patient | Baseline BP | Follow-up |
|---|---:|---:|
| `P001` | 146/92 mmHg | 95 days |
| `P002` | 151/96 mmHg | 37 days |

`P005` has a qualifying hypertension diagnosis and baseline blood pressure but is excluded because the sample contains no follow-up beyond the index date.

## Lineage

Each cohort build receives a UUID and records:

- definition version;
- parameter values;
- generated row count;
- the latest successful source run for each required dataset;
- generation timestamp;
- exported feature-file location.

The SQL implementation is stored in `sql/cohorts/hypertension.sql` and the orchestration code in `src/clinical_data_platform/cohort.py`.
