# Repository analysis guide

This sequence reviews the repository after running the bundled demonstration.

## 1. Run the complete workflow with captured logs

PowerShell:

```powershell
$env:CLINICAL_DATA_LOG_LEVEL = "INFO"
$env:CLINICAL_DATA_LOG_FORMAT = "json"
clinical-data run-demo --repository-root . 2> data/clinical-data.jsonl
```

The workflow captures six raw datasets, writes local execution journals, executes contracts, migrates PostgreSQL through V008, imports execution events, resolves coded concepts, persists accepted rows, builds the hypertension cohort, and emits correlated operational telemetry.

## 2. Inspect the structured log envelope

```powershell
Get-Content data/clinical-data.jsonl | Select-Object -First 5
```

Each line must parse as JSON and contain:

```text
schema_version = 1.0.0
timestamp
event
component
level
message
correlation_id
```

The complete demo should use one `correlation_id` across validation, persistence, and cohort operations. Individual datasets should have distinct `run_id` values.

Useful events:

```text
cli.command.started
pipeline.validation.completed
persistence.transaction.completed
cohort.database_build.completed
demo.run.completed
cli.command.completed
```

Confirm that operation completion records contain `duration_ms` and that logs do not contain patient identifiers or row values.

## 3. Verify migration state

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

V008 should be `add_execution_lifecycle_audit`. Structured logging does not add V009 because it does not modify persistent schema.

## 4. Inspect raw, processed, and execution artifacts

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

## 5. Inspect durable run state

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

## 6. Inspect one execution timeline

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

## 7. Compare logs with the durable audit

For the same `run_id`, locate log events:

```bash
jq 'select(.run_id == "<run-uuid>")' data/clinical-data.jsonl
```

The logs should describe operational stages and durations. PostgreSQL should describe authoritative state transitions and attempts.

Expected distinction:

```text
log missing
    → diagnostics may be incomplete
    → durable audit still establishes final state

audit row missing
    → the run was not durably registered
    → a log alone does not prove completed persistence
```

## 8. Validate a run programmatically

```python
from clinical_data_platform.run_audit import validate_pipeline_run_audit

result = validate_pipeline_run_audit(connection, run_id)
assert result.current_status == "completed"
assert result.event_count == 6
assert result.attempt_count == 1
```

This checks counts, heads, identities, transitions, hashes, chain continuity, local-journal boundary, and agreement between current state and final event.

## 9. Demonstrate a durable and observable failure

Validate encounters, then try to load them before patients.

Expected database outcome:

```text
clinical.encounters = 0
status = failed
attempt_count = 1
failure_code = 23503
```

Expected log events:

```text
persistence.transaction.failed
persistence.failure_audited
```

The failure log should retain:

```text
error_type
error_code = 23503
attempt_number = 1
```

It must not retain the rejected patient identifier from PostgreSQL `DETAIL` output.

Inspect durable state:

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

## 10. Demonstrate retry semantics

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

The logs should include a second persistence attempt with `attempt_number = 2`. The final projection is completed, while event 6 remains historical evidence.

## 11. Inspect active contracts

```powershell
clinical-data list-contracts
clinical-data validate-contracts
clinical-data show-contract diagnoses
clinical-data show-contract observations
clinical-data show-contract medications
clinical-data show-contract procedures
```

Contracts validate source structure and declared categorical systems. They do not contain complete external terminology releases.

## 12. Inspect terminology systems and bindings

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

## 13. Inspect six entity counts

```sql
SELECT 'patients' AS dataset, COUNT(*) FROM clinical.patients
UNION ALL SELECT 'encounters', COUNT(*) FROM clinical.encounters
UNION ALL SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
UNION ALL SELECT 'observations', COUNT(*) FROM clinical.observations
UNION ALL SELECT 'medications', COUNT(*) FROM clinical.medications
UNION ALL SELECT 'procedures', COUNT(*) FROM clinical.procedures
ORDER BY dataset;
```

Expected:

```text
patients      5
encounters    7
diagnoses     6
observations 13
medications   6
procedures    6
```

## 14. Inspect patient history

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

## 15. Inspect cohort stability and logs

```sql
SELECT *
FROM analytics.hypertension_features
ORDER BY patient_id;
```

Expected patients remain `P001` and `P002`.

The logs should include:

```text
cohort.source_runs.completed
cohort.database_build.completed
cohort.export.completed
cohort.run.completed
```

Only aggregate `row_count` is logged. The patient values remain in the analytical output, not in telemetry.

## 16. Demonstrate tamper detection

### Local journal

Change a field in one JSONL journal line without recalculating hashes. Persistence must reject the journal before registering the run.

### PostgreSQL event

Change one stored `event_sha256` and run `validate_pipeline_run_audit`. Validation must reject the durable chain.

### Structured logs

Logs are not hash chained. Modifying a collected log file is not detected by the application. This is an intentional distinction from the audit design.

## 17. Review code in this order

1. `structured_logging.py`;
2. `entrypoint.py`;
3. `execution.py`;
4. `pipeline.py`;
5. `V008__add_execution_lifecycle_audit.sql`;
6. `run_audit.py`;
7. `database.py`;
8. `cohort.py`;
9. `demo.py`;
10. `tests/test_structured_logging.py`;
11. `tests/test_run_audit.py`;
12. `tests/test_analysis_workflow.py`.

## 18. Key design questions

- Why are logs and the durable audit separate?
- Why does the CLI use stderr for telemetry and stdout for results?
- What does a correlation ID identify?
- Why does a correlation ID not replace `run_id`?
- Why are durations measured with a monotonic clock?
- Why is SQLSTATE more useful than matching an error message?
- Why must clinical values be omitted before redaction?
- Why is validation `validated` rather than `completed`?
- Why must the loading state commit before clinical inserts?
- What is the difference between a run, an attempt, and a correlation?
- What does a hash chain detect that a normal log file does not?

## 19. Known limitations

- local journal rather than WORM storage;
- structured stderr logs without centralized shipping or managed retention;
- no distributed tracing, metrics, dashboards, or alerting;
- no scheduler heartbeat or stale-loading recovery;
- small terminology subsets;
- small synthetic fixtures;
- no bulk `COPY` or performance benchmark;
- one demonstrative cohort;
- no PHI controls or production deployment claims.
