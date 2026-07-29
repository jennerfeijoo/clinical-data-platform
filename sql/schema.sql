CREATE SCHEMA IF NOT EXISTS clinical;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS audit.pipeline_runs (
    run_id UUID PRIMARY KEY,
    dataset_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    reference_date DATE NOT NULL,
    rows_received INTEGER NOT NULL CHECK (rows_received >= 0),
    rows_valid INTEGER NOT NULL CHECK (rows_valid >= 0),
    rows_invalid INTEGER NOT NULL CHECK (rows_invalid >= 0),
    validation_errors INTEGER NOT NULL CHECK (validation_errors >= 0),
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    generated_at TIMESTAMPTZ NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clinical.patients (
    patient_id TEXT PRIMARY KEY,
    sex_at_birth TEXT NOT NULL
        CHECK (sex_at_birth IN ('F', 'M', 'OTHER', 'UNKNOWN')),
    birth_date DATE NOT NULL,
    death_date DATE,
    source_system TEXT NOT NULL CHECK (btrim(source_system) <> ''),
    source_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    source_sha256 CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (death_date IS NULL OR death_date >= birth_date)
);

CREATE TABLE IF NOT EXISTS clinical.encounters (
    encounter_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES clinical.patients(patient_id),
    encounter_type TEXT NOT NULL
        CHECK (encounter_type IN ('OUTPATIENT', 'INPATIENT', 'EMERGENCY')),
    start_datetime TIMESTAMPTZ NOT NULL,
    end_datetime TIMESTAMPTZ NOT NULL,
    source_system TEXT NOT NULL CHECK (btrim(source_system) <> ''),
    source_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    source_sha256 CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (end_datetime >= start_datetime)
);

CREATE TABLE IF NOT EXISTS clinical.diagnoses (
    diagnosis_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES clinical.patients(patient_id),
    encounter_id TEXT NOT NULL REFERENCES clinical.encounters(encounter_id),
    code_system TEXT NOT NULL CHECK (code_system IN ('ICD10', 'SNOMED')),
    diagnosis_code TEXT NOT NULL CHECK (btrim(diagnosis_code) <> ''),
    diagnosis_datetime TIMESTAMPTZ NOT NULL,
    source_system TEXT NOT NULL CHECK (btrim(source_system) <> ''),
    source_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    source_sha256 CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clinical.observations (
    observation_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES clinical.patients(patient_id),
    encounter_id TEXT NOT NULL REFERENCES clinical.encounters(encounter_id),
    observation_code TEXT NOT NULL
        CHECK (observation_code IN ('SYSTOLIC_BP', 'DIASTOLIC_BP', 'HEART_RATE')),
    value_numeric DOUBLE PRECISION NOT NULL,
    unit TEXT NOT NULL CHECK (btrim(unit) <> ''),
    observed_at TIMESTAMPTZ NOT NULL,
    source_system TEXT NOT NULL CHECK (btrim(source_system) <> ''),
    source_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    source_sha256 CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (observation_code IN ('SYSTOLIC_BP', 'DIASTOLIC_BP') AND unit = 'mmHg')
        OR (observation_code = 'HEART_RATE' AND unit = 'bpm')
    )
);

CREATE TABLE IF NOT EXISTS audit.validation_errors (
    error_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL CHECK (row_number >= 2),
    entity_id TEXT,
    patient_id TEXT,
    field_name TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    message TEXT NOT NULL,
    rejected_value TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE audit.validation_errors
    ADD COLUMN IF NOT EXISTS entity_id TEXT;

CREATE TABLE IF NOT EXISTS audit.cohort_runs (
    cohort_run_id UUID PRIMARY KEY,
    cohort_name TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    parameters JSONB NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit.cohort_source_runs (
    cohort_run_id UUID NOT NULL
        REFERENCES audit.cohort_runs(cohort_run_id) ON DELETE CASCADE,
    source_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    PRIMARY KEY (cohort_run_id, source_run_id)
);

CREATE TABLE IF NOT EXISTS analytics.hypertension_features (
    cohort_run_id UUID NOT NULL
        REFERENCES audit.cohort_runs(cohort_run_id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL REFERENCES clinical.patients(patient_id),
    index_date DATE NOT NULL,
    age_at_index INTEGER NOT NULL CHECK (age_at_index >= 18),
    sex_at_birth TEXT NOT NULL,
    baseline_systolic_bp DOUBLE PRECISION NOT NULL,
    baseline_diastolic_bp DOUBLE PRECISION NOT NULL,
    prior_encounter_count_365d INTEGER NOT NULL CHECK (prior_encounter_count_365d >= 0),
    prior_diagnosis_count_365d INTEGER NOT NULL CHECK (prior_diagnosis_count_365d >= 0),
    follow_up_days INTEGER NOT NULL CHECK (follow_up_days >= 0),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cohort_run_id, patient_id)
);

CREATE INDEX IF NOT EXISTS idx_validation_errors_run_id
    ON audit.validation_errors (run_id);
CREATE INDEX IF NOT EXISTS idx_patients_source_run_id
    ON clinical.patients (source_run_id);
CREATE INDEX IF NOT EXISTS idx_encounters_patient_start
    ON clinical.encounters (patient_id, start_datetime);
CREATE INDEX IF NOT EXISTS idx_diagnoses_patient_code
    ON clinical.diagnoses (patient_id, code_system, diagnosis_code);
CREATE INDEX IF NOT EXISTS idx_observations_patient_code_time
    ON clinical.observations (patient_id, observation_code, observed_at);
CREATE INDEX IF NOT EXISTS idx_hypertension_features_patient
    ON analytics.hypertension_features (patient_id);
