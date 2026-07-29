WITH hypertension_index AS (
    SELECT
        patient_id,
        MIN(diagnosis_datetime)::date AS index_date
    FROM clinical.diagnoses
    WHERE code_system = 'ICD10'
      AND diagnosis_code LIKE 'I10%'
    GROUP BY patient_id
),
eligible_patients AS (
    SELECT
        h.patient_id,
        h.index_date,
        EXTRACT(YEAR FROM age(h.index_date, p.birth_date))::integer AS age_at_index,
        p.sex_at_birth
    FROM hypertension_index AS h
    JOIN clinical.patients AS p USING (patient_id)
    WHERE EXTRACT(YEAR FROM age(h.index_date, p.birth_date)) >= %(minimum_age)s
      AND (p.death_date IS NULL OR p.death_date >= h.index_date)
),
event_dates AS (
    SELECT patient_id, start_datetime::date AS event_date FROM clinical.encounters
    UNION ALL
    SELECT patient_id, diagnosis_datetime::date FROM clinical.diagnoses
    UNION ALL
    SELECT patient_id, observed_at::date FROM clinical.observations
),
follow_up AS (
    SELECT
        e.patient_id,
        MAX(e.event_date) AS last_event_date
    FROM event_dates AS e
    GROUP BY e.patient_id
),
bp_ranked AS (
    SELECT
        p.patient_id,
        o.observation_code,
        o.value_numeric,
        ROW_NUMBER() OVER (
            PARTITION BY p.patient_id, o.observation_code
            ORDER BY
                ABS(o.observed_at::date - p.index_date),
                o.observed_at,
                o.observation_id
        ) AS measurement_rank
    FROM eligible_patients AS p
    JOIN clinical.observations AS o USING (patient_id)
    WHERE o.observation_code IN ('SYSTOLIC_BP', 'DIASTOLIC_BP')
      AND o.observed_at::date BETWEEN
          p.index_date - %(baseline_window_days)s
          AND p.index_date + %(baseline_window_days)s
),
baseline_bp AS (
    SELECT
        patient_id,
        MAX(value_numeric) FILTER (
            WHERE observation_code = 'SYSTOLIC_BP' AND measurement_rank = 1
        ) AS baseline_systolic_bp,
        MAX(value_numeric) FILTER (
            WHERE observation_code = 'DIASTOLIC_BP' AND measurement_rank = 1
        ) AS baseline_diastolic_bp
    FROM bp_ranked
    GROUP BY patient_id
)
INSERT INTO analytics.hypertension_features (
    cohort_run_id,
    patient_id,
    index_date,
    age_at_index,
    sex_at_birth,
    baseline_systolic_bp,
    baseline_diastolic_bp,
    prior_encounter_count_365d,
    prior_diagnosis_count_365d,
    follow_up_days
)
SELECT
    %(cohort_run_id)s,
    p.patient_id,
    p.index_date,
    p.age_at_index,
    p.sex_at_birth,
    b.baseline_systolic_bp,
    b.baseline_diastolic_bp,
    (
        SELECT COUNT(*)::integer
        FROM clinical.encounters AS e
        WHERE e.patient_id = p.patient_id
          AND e.start_datetime::date >= p.index_date - 365
          AND e.start_datetime::date < p.index_date
    ),
    (
        SELECT COUNT(*)::integer
        FROM clinical.diagnoses AS d
        WHERE d.patient_id = p.patient_id
          AND d.diagnosis_datetime::date >= p.index_date - 365
          AND d.diagnosis_datetime::date < p.index_date
    ),
    f.last_event_date - p.index_date
FROM eligible_patients AS p
JOIN follow_up AS f USING (patient_id)
JOIN baseline_bp AS b USING (patient_id)
WHERE b.baseline_systolic_bp IS NOT NULL
  AND b.baseline_diastolic_bp IS NOT NULL
  AND f.last_event_date - p.index_date >= %(minimum_follow_up_days)s
ORDER BY p.patient_id
RETURNING
    patient_id,
    index_date,
    age_at_index,
    sex_at_birth,
    baseline_systolic_bp,
    baseline_diastolic_bp,
    prior_encounter_count_365d,
    prior_diagnosis_count_365d,
    follow_up_days;
