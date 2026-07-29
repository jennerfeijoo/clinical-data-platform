ALTER TABLE audit.validation_errors
    ADD COLUMN entity_id TEXT;

CREATE TABLE clinical.encounters (
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

CREATE TABLE clinical.diagnoses (
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

CREATE TABLE clinical.observations (
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

CREATE TABLE audit.cohort_runs (
    cohort_run_id UUID PRIMARY KEY,
    cohort_name TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    parameters JSONB NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit.cohort_source_runs (
    cohort_run_id UUID NOT NULL
        REFERENCES audit.cohort_runs(cohort_run_id) ON DELETE CASCADE,
    source_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    PRIMARY KEY (cohort_run_id, source_run_id)
);

CREATE TABLE analytics.hypertension_features (
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

CREATE INDEX idx_encounters_patient_start
    ON clinical.encounters (patient_id, start_datetime);
CREATE INDEX idx_diagnoses_patient_code
    ON clinical.diagnoses (patient_id, code_system, diagnosis_code);
CREATE INDEX idx_observations_patient_code_time
    ON clinical.observations (patient_id, observation_code, observed_at);
CREATE INDEX idx_hypertension_features_patient
    ON analytics.hypertension_features (patient_id);
