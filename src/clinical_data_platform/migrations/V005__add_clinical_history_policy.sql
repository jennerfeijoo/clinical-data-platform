CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE FUNCTION clinical.patient_record_sha256(
    p_patient_id TEXT,
    p_sex_at_birth TEXT,
    p_birth_date DATE,
    p_death_date DATE,
    p_source_system TEXT
) RETURNS CHAR(64)
LANGUAGE SQL
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT encode(
        digest(
            jsonb_build_object(
                'patient_id', p_patient_id,
                'sex_at_birth', p_sex_at_birth,
                'birth_date', p_birth_date,
                'death_date', p_death_date,
                'source_system', p_source_system
            )::TEXT,
            'sha256'
        ),
        'hex'
    )::CHAR(64)
$$;

CREATE FUNCTION clinical.encounter_record_sha256(
    p_encounter_id TEXT,
    p_patient_id TEXT,
    p_encounter_type TEXT,
    p_start_datetime TIMESTAMPTZ,
    p_end_datetime TIMESTAMPTZ,
    p_source_system TEXT
) RETURNS CHAR(64)
LANGUAGE SQL
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT encode(
        digest(
            jsonb_build_object(
                'encounter_id', p_encounter_id,
                'patient_id', p_patient_id,
                'encounter_type', p_encounter_type,
                'start_datetime', p_start_datetime,
                'end_datetime', p_end_datetime,
                'source_system', p_source_system
            )::TEXT,
            'sha256'
        ),
        'hex'
    )::CHAR(64)
$$;

CREATE FUNCTION clinical.diagnosis_record_sha256(
    p_diagnosis_id TEXT,
    p_patient_id TEXT,
    p_encounter_id TEXT,
    p_code_system TEXT,
    p_diagnosis_code TEXT,
    p_diagnosis_datetime TIMESTAMPTZ,
    p_source_system TEXT
) RETURNS CHAR(64)
LANGUAGE SQL
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT encode(
        digest(
            jsonb_build_object(
                'diagnosis_id', p_diagnosis_id,
                'patient_id', p_patient_id,
                'encounter_id', p_encounter_id,
                'code_system', p_code_system,
                'diagnosis_code', p_diagnosis_code,
                'diagnosis_datetime', p_diagnosis_datetime,
                'source_system', p_source_system
            )::TEXT,
            'sha256'
        ),
        'hex'
    )::CHAR(64)
$$;

CREATE FUNCTION clinical.observation_record_sha256(
    p_observation_id TEXT,
    p_patient_id TEXT,
    p_encounter_id TEXT,
    p_observation_code TEXT,
    p_value_numeric DOUBLE PRECISION,
    p_unit TEXT,
    p_observed_at TIMESTAMPTZ,
    p_source_system TEXT
) RETURNS CHAR(64)
LANGUAGE SQL
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT encode(
        digest(
            jsonb_build_object(
                'observation_id', p_observation_id,
                'patient_id', p_patient_id,
                'encounter_id', p_encounter_id,
                'observation_code', p_observation_code,
                'value_numeric', p_value_numeric,
                'unit', p_unit,
                'observed_at', p_observed_at,
                'source_system', p_source_system
            )::TEXT,
            'sha256'
        ),
        'hex'
    )::CHAR(64)
$$;

ALTER TABLE clinical.patients
    ADD COLUMN record_sha256 CHAR(64);
ALTER TABLE clinical.encounters
    ADD COLUMN record_sha256 CHAR(64);
ALTER TABLE clinical.diagnoses
    ADD COLUMN record_sha256 CHAR(64);
ALTER TABLE clinical.observations
    ADD COLUMN record_sha256 CHAR(64);

UPDATE clinical.patients
SET record_sha256 = clinical.patient_record_sha256(
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    source_system
);

UPDATE clinical.encounters
SET record_sha256 = clinical.encounter_record_sha256(
    encounter_id,
    patient_id,
    encounter_type,
    start_datetime,
    end_datetime,
    source_system
);

UPDATE clinical.diagnoses
SET record_sha256 = clinical.diagnosis_record_sha256(
    diagnosis_id,
    patient_id,
    encounter_id,
    code_system,
    diagnosis_code,
    diagnosis_datetime,
    source_system
);

UPDATE clinical.observations
SET record_sha256 = clinical.observation_record_sha256(
    observation_id,
    patient_id,
    encounter_id,
    observation_code,
    value_numeric,
    unit,
    observed_at,
    source_system
);

ALTER TABLE clinical.patients
    ALTER COLUMN record_sha256 SET NOT NULL;
ALTER TABLE clinical.encounters
    ALTER COLUMN record_sha256 SET NOT NULL;
ALTER TABLE clinical.diagnoses
    ALTER COLUMN record_sha256 SET NOT NULL;
ALTER TABLE clinical.observations
    ALTER COLUMN record_sha256 SET NOT NULL;

CREATE TABLE clinical.patient_history (
    patient_version_id BIGSERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    sex_at_birth TEXT NOT NULL
        CHECK (sex_at_birth IN ('F', 'M', 'OTHER', 'UNKNOWN')),
    birth_date DATE NOT NULL,
    death_date DATE,
    source_system TEXT NOT NULL CHECK (btrim(source_system) <> ''),
    record_sha256 CHAR(64) NOT NULL,
    valid_from_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    valid_to_run_id UUID REFERENCES audit.pipeline_runs(run_id),
    source_sha256 CHAR(64) NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    is_current BOOLEAN NOT NULL,
    CHECK (death_date IS NULL OR death_date >= birth_date),
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CHECK (
        (is_current AND valid_to IS NULL AND valid_to_run_id IS NULL)
        OR
        (NOT is_current AND valid_to IS NOT NULL AND valid_to_run_id IS NOT NULL)
    )
);

INSERT INTO clinical.patient_history (
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    source_system,
    record_sha256,
    valid_from_run_id,
    source_sha256,
    valid_from,
    is_current
)
SELECT
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    source_system,
    record_sha256,
    source_run_id,
    source_sha256,
    loaded_at,
    TRUE
FROM clinical.patients;

CREATE UNIQUE INDEX uq_patient_history_current
    ON clinical.patient_history (patient_id)
    WHERE is_current;
CREATE INDEX idx_patient_history_patient_validity
    ON clinical.patient_history (patient_id, valid_from, valid_to);
CREATE INDEX idx_patient_history_record_sha256
    ON clinical.patient_history (record_sha256);

CREATE FUNCTION clinical.set_patient_record_hash()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
BEGIN
    NEW.record_sha256 := clinical.patient_record_sha256(
        NEW.patient_id,
        NEW.sex_at_birth,
        NEW.birth_date,
        NEW.death_date,
        NEW.source_system
    );
    RETURN NEW;
END
$$;

CREATE FUNCTION clinical.capture_patient_history()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
DECLARE
    transition_time TIMESTAMPTZ := CURRENT_TIMESTAMP;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO clinical.patient_history (
            patient_id,
            sex_at_birth,
            birth_date,
            death_date,
            source_system,
            record_sha256,
            valid_from_run_id,
            source_sha256,
            valid_from,
            is_current
        ) VALUES (
            NEW.patient_id,
            NEW.sex_at_birth,
            NEW.birth_date,
            NEW.death_date,
            NEW.source_system,
            NEW.record_sha256,
            NEW.source_run_id,
            NEW.source_sha256,
            transition_time,
            TRUE
        );
        RETURN NULL;
    END IF;

    IF OLD.record_sha256 IS DISTINCT FROM NEW.record_sha256 THEN
        UPDATE clinical.patient_history
        SET valid_to = transition_time,
            valid_to_run_id = NEW.source_run_id,
            is_current = FALSE
        WHERE patient_id = OLD.patient_id
          AND is_current;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'No current patient history row exists for patient_id=%',
                OLD.patient_id
                USING ERRCODE = '23514';
        END IF;

        INSERT INTO clinical.patient_history (
            patient_id,
            sex_at_birth,
            birth_date,
            death_date,
            source_system,
            record_sha256,
            valid_from_run_id,
            source_sha256,
            valid_from,
            is_current
        ) VALUES (
            NEW.patient_id,
            NEW.sex_at_birth,
            NEW.birth_date,
            NEW.death_date,
            NEW.source_system,
            NEW.record_sha256,
            NEW.source_run_id,
            NEW.source_sha256,
            transition_time,
            TRUE
        );
    END IF;

    RETURN NULL;
END
$$;

CREATE TRIGGER trg_patients_set_record_hash
BEFORE INSERT OR UPDATE ON clinical.patients
FOR EACH ROW
EXECUTE FUNCTION clinical.set_patient_record_hash();

CREATE TRIGGER trg_patients_capture_history
AFTER INSERT OR UPDATE ON clinical.patients
FOR EACH ROW
EXECUTE FUNCTION clinical.capture_patient_history();

CREATE FUNCTION clinical.guard_encounter_immutability()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
DECLARE
    expected_sha256 CHAR(64);
BEGIN
    expected_sha256 := clinical.encounter_record_sha256(
        NEW.encounter_id,
        NEW.patient_id,
        NEW.encounter_type,
        NEW.start_datetime,
        NEW.end_datetime,
        NEW.source_system
    );

    IF TG_OP = 'INSERT' THEN
        NEW.record_sha256 := expected_sha256;
        RETURN NEW;
    END IF;

    IF OLD.record_sha256 IS DISTINCT FROM expected_sha256 THEN
        RAISE EXCEPTION
            'Immutable encounter conflict for encounter_id=%',
            OLD.encounter_id
            USING ERRCODE = '23514';
    END IF;

    RETURN OLD;
END
$$;

CREATE FUNCTION clinical.guard_diagnosis_immutability()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
DECLARE
    expected_sha256 CHAR(64);
BEGIN
    expected_sha256 := clinical.diagnosis_record_sha256(
        NEW.diagnosis_id,
        NEW.patient_id,
        NEW.encounter_id,
        NEW.code_system,
        NEW.diagnosis_code,
        NEW.diagnosis_datetime,
        NEW.source_system
    );

    IF TG_OP = 'INSERT' THEN
        NEW.record_sha256 := expected_sha256;
        RETURN NEW;
    END IF;

    IF OLD.record_sha256 IS DISTINCT FROM expected_sha256 THEN
        RAISE EXCEPTION
            'Immutable diagnosis conflict for diagnosis_id=%',
            OLD.diagnosis_id
            USING ERRCODE = '23514';
    END IF;

    RETURN OLD;
END
$$;

CREATE FUNCTION clinical.guard_observation_immutability()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
DECLARE
    expected_sha256 CHAR(64);
BEGIN
    expected_sha256 := clinical.observation_record_sha256(
        NEW.observation_id,
        NEW.patient_id,
        NEW.encounter_id,
        NEW.observation_code,
        NEW.value_numeric,
        NEW.unit,
        NEW.observed_at,
        NEW.source_system
    );

    IF TG_OP = 'INSERT' THEN
        NEW.record_sha256 := expected_sha256;
        RETURN NEW;
    END IF;

    IF OLD.record_sha256 IS DISTINCT FROM expected_sha256 THEN
        RAISE EXCEPTION
            'Immutable observation conflict for observation_id=%',
            OLD.observation_id
            USING ERRCODE = '23514';
    END IF;

    RETURN OLD;
END
$$;

CREATE TRIGGER trg_encounters_immutable
BEFORE INSERT OR UPDATE ON clinical.encounters
FOR EACH ROW
EXECUTE FUNCTION clinical.guard_encounter_immutability();

CREATE TRIGGER trg_diagnoses_immutable
BEFORE INSERT OR UPDATE ON clinical.diagnoses
FOR EACH ROW
EXECUTE FUNCTION clinical.guard_diagnosis_immutability();

CREATE TRIGGER trg_observations_immutable
BEFORE INSERT OR UPDATE ON clinical.observations
FOR EACH ROW
EXECUTE FUNCTION clinical.guard_observation_immutability();

COMMENT ON TABLE clinical.patients IS
    'Current patient snapshot. Business changes create SCD2 rows in clinical.patient_history.';
COMMENT ON TABLE clinical.patient_history IS
    'SCD Type 2 history for patient demographic snapshots.';
COMMENT ON TABLE clinical.encounters IS
    'Append-only clinical events. Conflicting reuse of an encounter_id is rejected.';
COMMENT ON TABLE clinical.diagnoses IS
    'Append-only clinical events. Conflicting reuse of a diagnosis_id is rejected.';
COMMENT ON TABLE clinical.observations IS
    'Append-only clinical events. Conflicting reuse of an observation_id is rejected.';
