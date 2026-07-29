# Repository analysis guide

This sequence reviews the repository after running the bundled demonstration.

## 1. Run the complete workflow

```powershell
clinical-data run-demo --repository-root .
```

The workflow captures six raw datasets, writes local execution journals, executes contracts, migrates PostgreSQL through V008, imports execution events, resolves coded concepts, persists accepted rows, and builds the hypertension cohort.

## 2. Verify migration state

```powershell
clinical-data database-status
clinical-data database-validate
```

Expected:

```text
detected=8
current=8
latest=8
pending=[]
```

Inspect:

```sql
SELECT version, name, checksum, execution_type, application_version, applied_at
FROM public.schema_migrations
ORDER BY version;
```

V008 should be `add_execution_lifecycle_audit`.

## 3. Inspect raw, processed, and execution artifacts

```text
data/raw/
├── objects/sha256/
└── receipts/

data/processed/<dataset>/
├── execution/<run-id>.jsonl
├── valid_<dataset>.csv
├── invalid_<dataset>.csv
├── validation_errors.csv
└── quality_report.json
```

For one dataset, verify that the quality report records:

```text
run_id
source and raw hashes
contract path, version, and hash
execution_journal_version
execution_journal_path
execution_event_count
execution_journal_head_sha256
status = validated
```

The local journal should contain:

```text
created
raw_captured
validating
validated
```

## 4. Inspect durable run state

```sql
SELECT
    run_id,
    dataset_name,
    status,
    current_stage,
    attempt_count,
    started_at,
    validated_at,
    loading_started_at,
    completed_at,
    failed_at,
    audit_event_count,
    audit_gap_reason
FROM audit.pipeline_runs
ORDER BY updated_at DESC;
```

After a clean demo, all six runs should be `completed`, each with `attempt_count = 1` and `audit_event_count = 6`.

## 5. Inspect one execution timeline

```sql
SELECT
    sequence_number,
    attempt_number,
    from_status,
    to_status,
    stage,
    occurred_at,
    error_type,
    error_code,
    error_message,
    event_source,
    previous_event_sha256,
    event_sha256
FROM audit.pipeline_run_timeline
WHERE run_id = '<run-uuid>'
ORDER BY sequence_number;
```

Expected clean sequence:

```text
1 created       attempt 0 local_journal
2 raw_captured  attempt 0 local_journal
3 validating    attempt 0 local_journal
4 validated     attempt 0 local_journal
5 loading       attempt 1 database
6 completed     attempt 1 database
```

Confirm that every `previous_event_sha256` equals the prior row's `event_sha256`.

## 6. Validate a run programmatically

```python
from clinical_data_platform.run_audit import validate_pipeline_run_audit

result = validate_pipeline_run_audit(connection, run_id)
assert result.current_status == "completed"
assert result.event_count == 6
assert result.attempt_count == 1
```

This checks counts, heads, identities, transitions, hashes, chain continuity, local-journal boundary, and agreement between current state and final event.

## 7. Demonstrate a durable failure

Validate encounters, then try to load them before patients.

Expected outcome:

```text
clinical.encounters = 0
status = failed
attempt_count = 1
failure_code = 23503
```

Inspect:

```sql
SELECT
    status,
    current_stage,
    attempt_count,
    failure_stage,
    failure_type,
    failure_code,
    failure_message,
    failed_at
FROM audit.pipeline_runs
WHERE run_id = '<encounter-run-uuid>';
```

The clinical transaction must be empty, while the run and failure timeline remain committed.

## 8. Demonstrate retry semantics

After the previous failure:

1. load patients;
2. load the same validated encounter outputs again.

Expected timeline:

```text
...
5 loading    attempt 1
6 failed     attempt 1
7 loading    attempt 2
8 completed  attempt 2
```

The final projection is completed with `attempt_count = 2`, while event 6 remains historical evidence.

## 9. Inspect active contracts

```powershell
clinical-data list-contracts
clinical-data validate-contracts
clinical-data show-contract diagnoses
clinical-data show-contract observations
clinical-data show-contract medications
clinical-data show-contract procedures
```

Contracts validate source structure and declared categorical systems. They do not contain complete external terminology releases.

## 10. Inspect terminology systems

```sql
SELECT
    code_system_id,
    canonical_uri,
    display_name,
    upstream_version,
    subset_version,
    complete_release,
    license_note
FROM terminology.code_systems
ORDER BY code_system_id;
```

External systems should be marked as incomplete local subsets.

## 11. Inspect normalized clinical codes

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

Expected local observation mappings:

```text
SYSTOLIC_BP  → LOINC 8480-6
DIASTOLIC_BP → LOINC 8462-4
HEART_RATE   → LOINC 8867-4
```

## 12. Inspect six entity counts

```sql
SELECT 'patients' AS dataset, COUNT(*) FROM clinical.patients
UNION ALL SELECT 'encounters', COUNT(*) FROM clinical.encounters
UNION ALL SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
UNION ALL SELECT 'observations', COUNT(*) FROM clinical.observations
UNION ALL SELECT 'medications', COUNT(*) FROM clinical.medications
UNION ALL SELECT 'procedures', COUNT(*) FROM clinical.procedures
ORDER BY dataset;
```

Expected counts:

```text
patients      5
encounters    7
diagnoses     6
observations 13
medications   6
procedures    6
```

## 13. Inspect patient history

```sql
SELECT
    patient_version_id,
    patient_id,
    record_sha256,
    valid_from_run_id,
    valid_to_run_id,
    valid_from,
    valid_to,
    is_current
FROM clinical.patient_history
ORDER BY patient_id, patient_version_id;
```

Confirm one current version per accepted patient.

## 14. Inspect cohort stability

```sql
SELECT *
FROM analytics.hypertension_features
ORDER BY patient_id;
```

Expected patients remain `P001` and `P002`.

## 15. Demonstrate tamper detection

### Local journal

Change a field in one JSONL line without recalculating hashes. Persistence must reject the journal before registering the run.

### PostgreSQL event

Change one stored `event_sha256` and run `validate_pipeline_run_audit`. Validation must reject the durable chain.

The hashes expose inconsistency but do not provide administrator-resistant storage.

## 16. Review code in this order

1. `execution.py`;
2. `pipeline.py`;
3. `V008__add_execution_lifecycle_audit.sql`;
4. `run_audit.py`;
5. `database.py`;
6. `tests/test_pipeline.py`;
7. `tests/test_run_audit.py`;
8. conflict tests in history, terminology, and additional entities;
9. `tests/test_analysis_workflow.py`.

## 17. Key design questions

- Why is validation `validated` rather than `completed`?
- Why must the loading state commit before clinical inserts?
- Why must completed commit with the clinical rows?
- Why is failed recorded only after the clinical transaction rolls back?
- What is the difference between a run and an attempt?
- What is the difference between idempotency and retry?
- Why are there separate local and durable audit heads?
- Why are pre-V008 events not reconstructed?
- What does a hash chain detect, and what can an administrator still do?

## 18. Known limitations

- local journal rather than WORM storage;
- no structured application logging or external log shipping;
- no distributed tracing, metrics, or alerting;
- no scheduler heartbeat or stale-loading recovery;
- small terminology subsets;
- small synthetic fixtures;
- no bulk `COPY` or performance benchmark;
- one demonstrative cohort;
- no PHI controls or production deployment claims.
