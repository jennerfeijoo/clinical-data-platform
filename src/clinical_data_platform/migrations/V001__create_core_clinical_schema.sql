CREATE SCHEMA clinical;
CREATE SCHEMA audit;
CREATE SCHEMA analytics;

CREATE TABLE audit.pipeline_runs (
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

CREATE TABLE clinical.patients (
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

CREATE TABLE audit.validation_errors (
    error_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL CHECK (row_number >= 2),
    patient_id TEXT,
    field_name TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    message TEXT NOT NULL,
    rejected_value TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_validation_errors_run_id
    ON audit.validation_errors (run_id);
CREATE INDEX idx_patients_source_run_id
    ON clinical.patients (source_run_id);
