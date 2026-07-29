CREATE SCHEMA terminology;

CREATE TABLE terminology.code_systems (
    code_system_id TEXT PRIMARY KEY,
    canonical_uri TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    authority TEXT NOT NULL,
    upstream_version TEXT,
    subset_version TEXT NOT NULL,
    complete_release BOOLEAN NOT NULL DEFAULT FALSE,
    license_note TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (btrim(code_system_id) <> ''),
    CHECK (btrim(canonical_uri) <> ''),
    CHECK (btrim(display_name) <> ''),
    CHECK (btrim(authority) <> ''),
    CHECK (btrim(subset_version) <> ''),
    CHECK (btrim(license_note) <> '')
);

CREATE TABLE terminology.system_aliases (
    source_system TEXT PRIMARY KEY,
    code_system_id TEXT NOT NULL
        REFERENCES terminology.code_systems(code_system_id),
    CHECK (source_system = upper(btrim(source_system)))
);

CREATE TABLE terminology.concepts (
    concept_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code_system_id TEXT NOT NULL
        REFERENCES terminology.code_systems(code_system_id),
    code TEXT NOT NULL,
    display TEXT NOT NULL,
    domain TEXT NOT NULL
        CHECK (domain IN ('condition', 'observation', 'medication', 'procedure')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    verification_status TEXT NOT NULL
        CHECK (verification_status IN ('verified', 'curated', 'unverified')),
    source_reference TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (code_system_id, code),
    CHECK (btrim(code) <> ''),
    CHECK (btrim(display) <> ''),
    CHECK (btrim(source_reference) <> '')
);

CREATE TABLE terminology.concept_mappings (
    source_concept_id BIGINT PRIMARY KEY
        REFERENCES terminology.concepts(concept_id),
    target_concept_id BIGINT NOT NULL
        REFERENCES terminology.concepts(concept_id),
    equivalence TEXT NOT NULL
        CHECK (equivalence IN ('equivalent', 'narrower', 'broader', 'related')),
    mapping_version TEXT NOT NULL,
    review_status TEXT NOT NULL
        CHECK (review_status IN ('reviewed', 'provisional')),
    mapping_method TEXT NOT NULL,
    CHECK (source_concept_id <> target_concept_id),
    CHECK (btrim(mapping_version) <> ''),
    CHECK (btrim(mapping_method) <> '')
);

INSERT INTO terminology.code_systems (
    code_system_id,
    canonical_uri,
    display_name,
    authority,
    upstream_version,
    subset_version,
    complete_release,
    license_note
)
VALUES
    (
        'ICD10CM',
        'http://hl7.org/fhir/sid/icd-10-cm',
        'ICD-10-CM',
        'United States Centers for Medicare & Medicaid Services',
        'FY2026',
        'clinical-data-platform-2026-07-29',
        FALSE,
        'Locally curated subset; consult CMS distribution terms for complete releases.'
    ),
    (
        'LOINC',
        'http://loinc.org',
        'LOINC',
        'Regenstrief Institute',
        '2.82',
        'clinical-data-platform-2026-07-29',
        FALSE,
        'Small subset redistributed under the LOINC license; not a complete release.'
    ),
    (
        'RXNORM',
        'http://www.nlm.nih.gov/research/umls/rxnorm',
        'RxNorm',
        'United States National Library of Medicine',
        NULL,
        'clinical-data-platform-2026-07-29',
        FALSE,
        'Locally curated subset; not a complete or continuously synchronized RxNorm release.'
    ),
    (
        'ATC',
        'http://www.whocc.no/atc',
        'Anatomical Therapeutic Chemical Classification',
        'WHO Collaborating Centre for Drug Statistics Methodology',
        NULL,
        'clinical-data-platform-2026-07-29',
        FALSE,
        'Illustrative subset only; consult the WHO ATC/DDD Index and terms of use.'
    ),
    (
        'SNOMEDCT',
        'http://snomed.info/sct',
        'SNOMED CT',
        'SNOMED International',
        NULL,
        'clinical-data-platform-2026-07-29',
        FALSE,
        'Illustrative subset only; use requires compliance with applicable SNOMED CT licensing.'
    ),
    (
        'CPT',
        'http://www.ama-assn.org/go/cpt',
        'Current Procedural Terminology',
        'American Medical Association',
        NULL,
        'clinical-data-platform-2026-07-29',
        FALSE,
        'Codes only with neutral local labels; no licensed CPT descriptor distribution.'
    ),
    (
        'ICD10PCS',
        'http://www.cms.gov/Medicare/Coding/ICD10',
        'ICD-10-PCS',
        'United States Centers for Medicare & Medicaid Services',
        'FY2026',
        'clinical-data-platform-2026-07-29',
        FALSE,
        'Locally curated subset; consult CMS distribution files for complete releases.'
    ),
    (
        'LOCAL_OBSERVATION',
        'urn:clinical-data-platform:code-system:observation',
        'Clinical Data Platform local observation codes',
        'Clinical Data Platform',
        '1.0.0',
        '1.0.0',
        TRUE,
        'Project-local synthetic terminology.'
    );

INSERT INTO terminology.system_aliases (source_system, code_system_id)
VALUES
    ('ICD10', 'ICD10CM'),
    ('ICD10CM', 'ICD10CM'),
    ('LOINC', 'LOINC'),
    ('RXNORM', 'RXNORM'),
    ('ATC', 'ATC'),
    ('SNOMED', 'SNOMEDCT'),
    ('SNOMEDCT', 'SNOMEDCT'),
    ('CPT', 'CPT'),
    ('ICD10PCS', 'ICD10PCS'),
    ('LOCAL_OBSERVATION', 'LOCAL_OBSERVATION');

INSERT INTO terminology.concepts (
    code_system_id,
    code,
    display,
    domain,
    active,
    verification_status,
    source_reference
)
VALUES
    ('ICD10CM', 'E78.5', 'Hyperlipidemia, unspecified', 'condition', TRUE, 'verified', 'CMS FY2026 ICD-10-CM subset'),
    ('ICD10CM', 'I10', 'Essential (primary) hypertension', 'condition', TRUE, 'verified', 'CMS FY2026 ICD-10-CM subset'),
    ('ICD10CM', 'J45.909', 'Unspecified asthma, uncomplicated', 'condition', TRUE, 'verified', 'CMS FY2026 ICD-10-CM subset'),
    ('ICD10CM', 'E11.9', 'Type 2 diabetes mellitus without complications', 'condition', TRUE, 'verified', 'CMS FY2026 ICD-10-CM subset'),
    ('LOINC', '8480-6', 'Systolic blood pressure', 'observation', TRUE, 'verified', 'LOINC 2.82'),
    ('LOINC', '8462-4', 'Diastolic blood pressure', 'observation', TRUE, 'verified', 'LOINC 2.82'),
    ('LOINC', '8867-4', 'Heart rate', 'observation', TRUE, 'verified', 'LOINC 2.82'),
    ('LOCAL_OBSERVATION', 'SYSTOLIC_BP', 'Local systolic blood pressure', 'observation', TRUE, 'curated', 'Project contract observations v1.0.0'),
    ('LOCAL_OBSERVATION', 'DIASTOLIC_BP', 'Local diastolic blood pressure', 'observation', TRUE, 'curated', 'Project contract observations v1.0.0'),
    ('LOCAL_OBSERVATION', 'HEART_RATE', 'Local heart rate', 'observation', TRUE, 'curated', 'Project contract observations v1.0.0'),
    ('RXNORM', '197361', 'amlodipine 5 MG Oral Tablet', 'medication', TRUE, 'verified', 'NLM RxNorm/RxNav curated lookup'),
    ('RXNORM', '860975', '24 HR metformin hydrochloride 500 MG Extended Release Oral Tablet', 'medication', TRUE, 'verified', 'NLM RxNorm/RxNav curated lookup'),
    ('RXNORM', '312961', 'simvastatin 20 MG Oral Tablet', 'medication', TRUE, 'verified', 'NLM RxNorm/RxNav curated lookup'),
    ('RXNORM', '617314', 'atorvastatin 10 MG Oral Tablet [Lipitor]', 'medication', TRUE, 'verified', 'NLM RxNorm/RxNav curated lookup'),
    ('ATC', 'C09AA05', 'ATC C09AA05', 'medication', TRUE, 'unverified', 'Illustrative ATC subset entry'),
    ('ATC', 'D07AC01', 'ATC D07AC01', 'medication', TRUE, 'unverified', 'Illustrative ATC subset entry'),
    ('SNOMEDCT', '386053000', 'Evaluation procedure', 'procedure', TRUE, 'verified', 'SNOMED CT curated subset'),
    ('SNOMEDCT', '29303009', 'Electrocardiographic procedure', 'procedure', TRUE, 'verified', 'SNOMED CT curated subset'),
    ('SNOMEDCT', '225358003', 'Wound care', 'procedure', TRUE, 'verified', 'SNOMED CT curated subset'),
    ('CPT', '93000', 'CPT code 93000', 'procedure', TRUE, 'unverified', 'Code retained without licensed CPT descriptor'),
    ('CPT', '71045', 'CPT code 71045', 'procedure', TRUE, 'unverified', 'Code retained without licensed CPT descriptor'),
    ('ICD10PCS', '3E0P3VZ', 'Introduction of hormone into female reproductive, percutaneous approach', 'procedure', TRUE, 'verified', 'CMS FY2026 ICD-10-PCS subset');

INSERT INTO terminology.concept_mappings (
    source_concept_id,
    target_concept_id,
    equivalence,
    mapping_version,
    review_status,
    mapping_method
)
SELECT
    source.concept_id,
    target.concept_id,
    'equivalent',
    '1.0.0',
    'reviewed',
    'Manually reviewed project mapping'
FROM (
    VALUES
        ('SYSTOLIC_BP', '8480-6'),
        ('DIASTOLIC_BP', '8462-4'),
        ('HEART_RATE', '8867-4')
) AS mapping(source_code, target_code)
JOIN terminology.concepts AS source
    ON source.code_system_id = 'LOCAL_OBSERVATION'
   AND source.code = mapping.source_code
JOIN terminology.concepts AS target
    ON target.code_system_id = 'LOINC'
   AND target.code = mapping.target_code;

-- Preserve upgrade compatibility for codes already accepted under V006 contracts.
INSERT INTO terminology.concepts (
    code_system_id,
    code,
    display,
    domain,
    active,
    verification_status,
    source_reference
)
SELECT DISTINCT
    alias.code_system_id,
    diagnosis.diagnosis_code,
    alias.code_system_id || ' code ' || diagnosis.diagnosis_code,
    'condition',
    TRUE,
    'unverified',
    'Imported from pre-V007 clinical.diagnoses'
FROM clinical.diagnoses AS diagnosis
JOIN terminology.system_aliases AS alias
    ON alias.source_system = upper(btrim(diagnosis.code_system))
ON CONFLICT (code_system_id, code) DO NOTHING;

INSERT INTO terminology.concepts (
    code_system_id,
    code,
    display,
    domain,
    active,
    verification_status,
    source_reference
)
SELECT DISTINCT
    alias.code_system_id,
    medication.medication_code,
    alias.code_system_id || ' code ' || medication.medication_code,
    'medication',
    TRUE,
    'unverified',
    'Imported from pre-V007 clinical.medications'
FROM clinical.medications AS medication
JOIN terminology.system_aliases AS alias
    ON alias.source_system = upper(btrim(medication.code_system))
ON CONFLICT (code_system_id, code) DO NOTHING;

INSERT INTO terminology.concepts (
    code_system_id,
    code,
    display,
    domain,
    active,
    verification_status,
    source_reference
)
SELECT DISTINCT
    alias.code_system_id,
    procedure.procedure_code,
    alias.code_system_id || ' code ' || procedure.procedure_code,
    'procedure',
    TRUE,
    'unverified',
    'Imported from pre-V007 clinical.procedures'
FROM clinical.procedures AS procedure
JOIN terminology.system_aliases AS alias
    ON alias.source_system = upper(btrim(procedure.code_system))
ON CONFLICT (code_system_id, code) DO NOTHING;

CREATE FUNCTION terminology.resolve_concept(
    p_source_system TEXT,
    p_source_code TEXT,
    p_expected_domain TEXT
) RETURNS BIGINT
LANGUAGE PLPGSQL
STABLE
AS $$
DECLARE
    canonical_system TEXT;
    source_id BIGINT;
    resolved_id BIGINT;
    resolved_domain TEXT;
    resolved_active BOOLEAN;
BEGIN
    IF p_source_system IS NULL OR btrim(p_source_system) = '' THEN
        RAISE EXCEPTION 'Terminology source system is required'
            USING ERRCODE = '23514';
    END IF;
    IF p_source_code IS NULL OR btrim(p_source_code) = '' THEN
        RAISE EXCEPTION 'Terminology source code is required'
            USING ERRCODE = '23514';
    END IF;

    SELECT alias.code_system_id
    INTO canonical_system
    FROM terminology.system_aliases AS alias
    WHERE alias.source_system = upper(btrim(p_source_system));

    IF canonical_system IS NULL THEN
        RAISE EXCEPTION 'Unsupported terminology system: %', p_source_system
            USING ERRCODE = '23514';
    END IF;

    SELECT concept.concept_id
    INTO source_id
    FROM terminology.concepts AS concept
    WHERE concept.code_system_id = canonical_system
      AND concept.code = btrim(p_source_code);

    IF source_id IS NULL THEN
        RAISE EXCEPTION 'Unknown terminology concept system=% code=%',
            canonical_system,
            p_source_code
            USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(mapping.target_concept_id, source_id)
    INTO resolved_id
    FROM (SELECT source_id AS concept_id) AS source
    LEFT JOIN terminology.concept_mappings AS mapping
        ON mapping.source_concept_id = source.concept_id;

    SELECT concept.domain, concept.active
    INTO resolved_domain, resolved_active
    FROM terminology.concepts AS concept
    WHERE concept.concept_id = resolved_id;

    IF NOT resolved_active THEN
        RAISE EXCEPTION 'Inactive terminology concept system=% code=%',
            canonical_system,
            p_source_code
            USING ERRCODE = '23514';
    END IF;

    IF resolved_domain <> p_expected_domain THEN
        RAISE EXCEPTION
            'Terminology domain mismatch system=% code=% expected=% resolved=%',
            canonical_system,
            p_source_code,
            p_expected_domain,
            resolved_domain
            USING ERRCODE = '23514';
    END IF;

    RETURN resolved_id;
END
$$;

ALTER TABLE clinical.diagnoses
    ADD COLUMN normalized_concept_id BIGINT;
ALTER TABLE clinical.observations
    ADD COLUMN normalized_concept_id BIGINT;
ALTER TABLE clinical.medications
    ADD COLUMN normalized_concept_id BIGINT;
ALTER TABLE clinical.procedures
    ADD COLUMN normalized_concept_id BIGINT;

UPDATE clinical.diagnoses
SET normalized_concept_id = terminology.resolve_concept(
    code_system,
    diagnosis_code,
    'condition'
);

UPDATE clinical.observations
SET normalized_concept_id = terminology.resolve_concept(
    'LOCAL_OBSERVATION',
    observation_code,
    'observation'
);

UPDATE clinical.medications
SET normalized_concept_id = terminology.resolve_concept(
    code_system,
    medication_code,
    'medication'
);

UPDATE clinical.procedures
SET normalized_concept_id = terminology.resolve_concept(
    code_system,
    procedure_code,
    'procedure'
);

ALTER TABLE clinical.diagnoses
    ALTER COLUMN normalized_concept_id SET NOT NULL,
    ADD CONSTRAINT fk_diagnoses_normalized_concept
        FOREIGN KEY (normalized_concept_id)
        REFERENCES terminology.concepts(concept_id);
ALTER TABLE clinical.observations
    ALTER COLUMN normalized_concept_id SET NOT NULL,
    ADD CONSTRAINT fk_observations_normalized_concept
        FOREIGN KEY (normalized_concept_id)
        REFERENCES terminology.concepts(concept_id);
ALTER TABLE clinical.medications
    ALTER COLUMN normalized_concept_id SET NOT NULL,
    ADD CONSTRAINT fk_medications_normalized_concept
        FOREIGN KEY (normalized_concept_id)
        REFERENCES terminology.concepts(concept_id);
ALTER TABLE clinical.procedures
    ALTER COLUMN normalized_concept_id SET NOT NULL,
    ADD CONSTRAINT fk_procedures_normalized_concept
        FOREIGN KEY (normalized_concept_id)
        REFERENCES terminology.concepts(concept_id);

CREATE FUNCTION terminology.assign_diagnosis_concept()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
BEGIN
    NEW.normalized_concept_id := terminology.resolve_concept(
        NEW.code_system,
        NEW.diagnosis_code,
        'condition'
    );
    RETURN NEW;
END
$$;

CREATE FUNCTION terminology.assign_observation_concept()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
BEGIN
    NEW.normalized_concept_id := terminology.resolve_concept(
        'LOCAL_OBSERVATION',
        NEW.observation_code,
        'observation'
    );
    RETURN NEW;
END
$$;

CREATE FUNCTION terminology.assign_medication_concept()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
BEGIN
    NEW.normalized_concept_id := terminology.resolve_concept(
        NEW.code_system,
        NEW.medication_code,
        'medication'
    );
    RETURN NEW;
END
$$;

CREATE FUNCTION terminology.assign_procedure_concept()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
BEGIN
    NEW.normalized_concept_id := terminology.resolve_concept(
        NEW.code_system,
        NEW.procedure_code,
        'procedure'
    );
    RETURN NEW;
END
$$;

CREATE TRIGGER trg_00_diagnoses_terminology
BEFORE INSERT OR UPDATE OF code_system, diagnosis_code
ON clinical.diagnoses
FOR EACH ROW
EXECUTE FUNCTION terminology.assign_diagnosis_concept();

CREATE TRIGGER trg_00_observations_terminology
BEFORE INSERT OR UPDATE OF observation_code
ON clinical.observations
FOR EACH ROW
EXECUTE FUNCTION terminology.assign_observation_concept();

CREATE TRIGGER trg_00_medications_terminology
BEFORE INSERT OR UPDATE OF code_system, medication_code
ON clinical.medications
FOR EACH ROW
EXECUTE FUNCTION terminology.assign_medication_concept();

CREATE TRIGGER trg_00_procedures_terminology
BEFORE INSERT OR UPDATE OF code_system, procedure_code
ON clinical.procedures
FOR EACH ROW
EXECUTE FUNCTION terminology.assign_procedure_concept();

CREATE INDEX idx_diagnoses_normalized_concept
    ON clinical.diagnoses (normalized_concept_id);
CREATE INDEX idx_observations_normalized_concept
    ON clinical.observations (normalized_concept_id);
CREATE INDEX idx_medications_normalized_concept
    ON clinical.medications (normalized_concept_id);
CREATE INDEX idx_procedures_normalized_concept
    ON clinical.procedures (normalized_concept_id);
CREATE INDEX idx_terminology_concepts_domain
    ON terminology.concepts (domain, code_system_id, code);

CREATE VIEW terminology.normalized_clinical_codes AS
SELECT
    'diagnoses'::TEXT AS dataset_name,
    diagnosis.diagnosis_id AS entity_id,
    diagnosis.code_system AS source_system,
    diagnosis.diagnosis_code AS source_code,
    system.code_system_id AS normalized_system,
    concept.code AS normalized_code,
    concept.display AS normalized_display,
    concept.domain,
    concept.verification_status
FROM clinical.diagnoses AS diagnosis
JOIN terminology.concepts AS concept
    ON concept.concept_id = diagnosis.normalized_concept_id
JOIN terminology.code_systems AS system
    ON system.code_system_id = concept.code_system_id
UNION ALL
SELECT
    'observations',
    observation.observation_id,
    'LOCAL_OBSERVATION',
    observation.observation_code,
    system.code_system_id,
    concept.code,
    concept.display,
    concept.domain,
    concept.verification_status
FROM clinical.observations AS observation
JOIN terminology.concepts AS concept
    ON concept.concept_id = observation.normalized_concept_id
JOIN terminology.code_systems AS system
    ON system.code_system_id = concept.code_system_id
UNION ALL
SELECT
    'medications',
    medication.medication_id,
    medication.code_system,
    medication.medication_code,
    system.code_system_id,
    concept.code,
    concept.display,
    concept.domain,
    concept.verification_status
FROM clinical.medications AS medication
JOIN terminology.concepts AS concept
    ON concept.concept_id = medication.normalized_concept_id
JOIN terminology.code_systems AS system
    ON system.code_system_id = concept.code_system_id
UNION ALL
SELECT
    'procedures',
    procedure.procedure_id,
    procedure.code_system,
    procedure.procedure_code,
    system.code_system_id,
    concept.code,
    concept.display,
    concept.domain,
    concept.verification_status
FROM clinical.procedures AS procedure
JOIN terminology.concepts AS concept
    ON concept.concept_id = procedure.normalized_concept_id
JOIN terminology.code_systems AS system
    ON system.code_system_id = concept.code_system_id;

COMMENT ON SCHEMA terminology IS
    'Versioned local terminology subset and normalization mappings. Not a complete terminology service.';
COMMENT ON VIEW terminology.normalized_clinical_codes IS
    'Source codes resolved to the normalized concepts accepted by the local terminology subset.';
