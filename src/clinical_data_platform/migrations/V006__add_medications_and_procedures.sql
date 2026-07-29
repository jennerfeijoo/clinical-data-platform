CREATE FUNCTION clinical.medication_record_sha256(
    p_medication_id TEXT,
    p_patient_id TEXT,
    p_encounter_id TEXT,
    p_code_system TEXT,
    p_medication_code TEXT,
    p_status TEXT,
    p_start_datetime TIMESTAMPTZ,
    p_end_datetime TIMESTAMPTZ,
    p_dose_value DOUBLE PRECISION,
    p_dose_unit TEXT,
    p_route TEXT,
    p_source_system TEXT
) RETURNS CHAR(64)
LANGUAGE SQL
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT encode(
        digest(
            jsonb_build_object(
                'medication_id', p_medication_id,
                'patient_id', p_patient_id,
                'encounter_id', p_encounter_id,
                'code_system', p_code_system,
                'medication_code', p_medication_code,
                'status', p_status,
                'start_datetime', p_start_datetime,
                'end_datetime', p_end_datetime,
                'dose_value', p_dose_value,
                'dose_unit', p_dose_unit,
                'route', p_route,
                'source_system', p_source_system
            )::TEXT,
            'sha256'
        ),
        'hex'
    )::CHAR(64)
$$;

CREATE FUNCTION clinical.procedure_record_sha256(
    p_procedure_id TEXT,
    p_patient_id TEXT,
    p_encounter_id TEXT,
    p_code_system TEXT,
    p_procedure_code TEXT,
    p_procedure_datetime TIMESTAMPTZ,
    p_status TEXT,
    p_source_system TEXT
) RETURNS CHAR(64)
LANGUAGE SQL
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT encode(
        digest(
            jsonb_build_object(
                'procedure_id', p_procedure_id,
                'patient_id', p_patient_id,
                'encounter_id', p_encounter_id,
                'code_system', p_code_system,
                'procedure_code', p_procedure_code,
                'procedure_datetime', p_procedure_datetime,
                'status', p_status,
                'source_system', p_source_system
            )::TEXT,
            'sha256'
        ),
        'hex'
    )::CHAR(64)
$$;

CREATE TABLE clinical.medications (
    medication_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES clinical.patients(patient_id),
    encounter_id TEXT NOT NULL REFERENCES clinical.encounters(encounter_id),
    code_system TEXT NOT NULL CHECK (code_system IN ('RXNORM', 'ATC')),
    medication_code TEXT NOT NULL CHECK (btrim(medication_code) <> ''),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'COMPLETED', 'STOPPED')),
    start_datetime TIMESTAMPTZ NOT NULL,
    end_datetime TIMESTAMPTZ,
    dose_value DOUBLE PRECISION,
    dose_unit TEXT,
    route TEXT CHECK (
        route IS NULL
        OR route IN ('ORAL', 'INTRAVENOUS', 'SUBCUTANEOUS', 'INHALATION', 'TOPICAL')
    ),
    source_system TEXT NOT NULL CHECK (btrim(source_system) <> ''),
    source_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    source_sha256 CHAR(64) NOT NULL,
    record_sha256 CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (end_datetime IS NULL OR end_datetime >= start_datetime),
    CHECK (
        (dose_value IS NULL AND dose_unit IS NULL)
        OR (
            dose_value IS NOT NULL
            AND dose_value > 0
            AND dose_unit IS NOT NULL
            AND btrim(dose_unit) <> ''
        )
    )
);

CREATE TABLE clinical.procedures (
    procedure_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES clinical.patients(patient_id),
    encounter_id TEXT NOT NULL REFERENCES clinical.encounters(encounter_id),
    code_system TEXT NOT NULL CHECK (code_system IN ('SNOMED', 'CPT', 'ICD10PCS')),
    procedure_code TEXT NOT NULL CHECK (btrim(procedure_code) <> ''),
    procedure_datetime TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('COMPLETED', 'IN_PROGRESS', 'NOT_DONE')),
    source_system TEXT NOT NULL CHECK (btrim(source_system) <> ''),
    source_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    source_sha256 CHAR(64) NOT NULL,
    record_sha256 CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE FUNCTION clinical.guard_medication_immutability()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
DECLARE
    expected_sha256 CHAR(64);
BEGIN
    expected_sha256 := clinical.medication_record_sha256(
        NEW.medication_id,
        NEW.patient_id,
        NEW.encounter_id,
        NEW.code_system,
        NEW.medication_code,
        NEW.status,
        NEW.start_datetime,
        NEW.end_datetime,
        NEW.dose_value,
        NEW.dose_unit,
        NEW.route,
        NEW.source_system
    );

    IF TG_OP = 'INSERT' THEN
        NEW.record_sha256 := expected_sha256;
        RETURN NEW;
    END IF;

    IF OLD.record_sha256 IS DISTINCT FROM expected_sha256 THEN
        RAISE EXCEPTION
            'Immutable medication conflict for medication_id=%',
            OLD.medication_id
            USING ERRCODE = '23514';
    END IF;

    RETURN OLD;
END
$$;

CREATE FUNCTION clinical.guard_procedure_immutability()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
DECLARE
    expected_sha256 CHAR(64);
BEGIN
    expected_sha256 := clinical.procedure_record_sha256(
        NEW.procedure_id,
        NEW.patient_id,
        NEW.encounter_id,
        NEW.code_system,
        NEW.procedure_code,
        NEW.procedure_datetime,
        NEW.status,
        NEW.source_system
    );

    IF TG_OP = 'INSERT' THEN
        NEW.record_sha256 := expected_sha256;
        RETURN NEW;
    END IF;

    IF OLD.record_sha256 IS DISTINCT FROM expected_sha256 THEN
        RAISE EXCEPTION
            'Immutable procedure conflict for procedure_id=%',
            OLD.procedure_id
            USING ERRCODE = '23514';
    END IF;

    RETURN OLD;
END
$$;

CREATE TRIGGER trg_medications_immutable
BEFORE INSERT OR UPDATE ON clinical.medications
FOR EACH ROW
EXECUTE FUNCTION clinical.guard_medication_immutability();

CREATE TRIGGER trg_procedures_immutable
BEFORE INSERT OR UPDATE ON clinical.procedures
FOR EACH ROW
EXECUTE FUNCTION clinical.guard_procedure_immutability();

CREATE INDEX idx_medications_patient_start
    ON clinical.medications (patient_id, start_datetime);
CREATE INDEX idx_medications_encounter
    ON clinical.medications (encounter_id);
CREATE INDEX idx_medications_code
    ON clinical.medications (code_system, medication_code);
CREATE INDEX idx_procedures_patient_time
    ON clinical.procedures (patient_id, procedure_datetime);
CREATE INDEX idx_procedures_encounter
    ON clinical.procedures (encounter_id);
CREATE INDEX idx_procedures_code
    ON clinical.procedures (code_system, procedure_code);

COMMENT ON TABLE clinical.medications IS
    'Immutable medication events. Conflicting reuse of a medication_id is rejected.';
COMMENT ON TABLE clinical.procedures IS
    'Immutable procedure events. Conflicting reuse of a procedure_id is rejected.';
