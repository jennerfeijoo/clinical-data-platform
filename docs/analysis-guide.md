# Repository analysis guide

This sequence reviews the bundled demo and the reproducible Synthea source workflow.

## 1. Inspect the pinned Synthea profile

```powershell
clinical-data synthea-profile
```

Confirm:

```text
name = synthea-us-small-v1
upstream ref = v4.0.0
population = 100
random seed = 20260729
clinician seed = 20260730
reference date = 2026-07-29
state = Massachusetts
thread pool = 1
years of history = 0
six included CSV files
profile SHA-256 = 64 hexadecimal characters
```

Explain why the profile hash, upstream ref, resolved commit, and generated file hashes represent different identities.

## 2. Exercise the adapter without running Java

```powershell
clinical-data synthea-adapt `
  tests/fixtures/synthea/csv `
  --output-dir data/synthea/review-normalized `
  --replace

clinical-data synthea-verify data/synthea/review-normalized
```

Expected fixture output:

```text
patients      2
encounters    2
diagnoses     2
observations  3
medications   2
procedures    1
```

Expected omission:

```text
observation_outside_supported_subset = 1
```

The omitted row is body weight. It is structurally valid Synthea data but outside the current internal observation contract.

## 3. Inspect the adaptation manifest

```powershell
Get-Content data/synthea/review-normalized/synthea-adaptation-manifest.json
```

Locate:

```text
adapter_version
profile.sha256
source_files
output_files
dataset_rows
omitted_rows
terminology_concepts
adaptation_fingerprint
```

For every source and output file, verify that the manifest contains:

```text
header
row_count
size_bytes
sha256
```

## 4. Demonstrate deterministic adaptation

Run the adapter into two empty directories with the same fixture and profile.

Compare:

```powershell
Get-FileHash data/synthea/review-a/*.csv -Algorithm SHA256
Get-FileHash data/synthea/review-b/*.csv -Algorithm SHA256
```

Expected:

```text
all seven CSV hashes equal
adaptation fingerprints equal
UUIDv5 event identifiers equal
```

Equal row counts alone are insufficient evidence of identical outputs.

## 5. Demonstrate source schema drift

Copy the fixture and rename the patient header:

```text
BIRTHDATE → DATE_OF_BIRTH
```

The adapter must fail before transforming patients. This verifies that an upstream schema change cannot be interpreted silently by the v1 adapter.

## 6. Demonstrate adaptation tamper detection

After a successful adaptation, change one byte in an output CSV and execute:

```powershell
clinical-data synthea-verify data/synthea/review-normalized
```

Verification must reject the file hash or adaptation fingerprint.

## 7. Inspect transformation semantics

### Patient

Verify:

```text
Synthea Id        → patient_id
Synthea GENDER    → sex_at_birth
Synthea BIRTHDATE → birth_date
```

### Encounter

Verify:

```text
ambulatory → OUTPATIENT
emergency  → EMERGENCY
```

### Diagnosis

Confirm that `conditions.csv` becomes `diagnoses.csv` and receives deterministic UUIDv5 identifiers.

### Observation

Confirm mappings:

```text
8480-6 → SYSTOLIC_BP  → mmHg
8462-4 → DIASTOLIC_BP → mmHg
8867-4 → HEART_RATE   → bpm
```

### Medication

Confirm:

```text
CODE interpreted as RXNORM
blank STOP → ACTIVE
STOP present → COMPLETED
```

### Procedure

Confirm that the source system is normalized to one of:

```text
SNOMED
CPT
ICD10PCS
```

## 8. Inspect terminology candidates

```powershell
Import-Csv data/synthea/review-normalized/terminology.csv |
    Format-Table
```

New Synthea source concepts must use:

```text
verification_status = unverified
```

This status describes local verification evidence. It does not state that the source concept is clinically invalid.

## 9. Load the adapted fixture

```powershell
docker compose up -d postgres
$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"

clinical-data database-migrate
clinical-data synthea-load `
  data/synthea/review-normalized `
  --processed-root data/processed/synthea-review `
  --raw-root data/raw
```

The command must reuse:

```text
raw capture
contracts
quality reports
execution journals
structured logging
durable run audit
terminology resolution
transactional persistence
```

No source-specific persistence algorithm should appear.

## 10. Inspect Synthea-loaded runs

```sql
SELECT
    run_id,
    dataset_name,
    status,
    attempt_count,
    source_path,
    source_sha256,
    contract_version,
    audit_event_count
FROM audit.pipeline_runs
WHERE source_path LIKE '%synthea%'
ORDER BY loaded_at;
```

Expected:

```text
six completed runs
attempt_count = 1
audit_event_count = 6
```

## 11. Inspect Synthea terminology imports

```sql
SELECT
    code_system_id,
    code,
    display,
    domain,
    verification_status,
    source_reference
FROM terminology.concepts
WHERE source_reference LIKE 'Synthea 4.0.0 CSV export%'
ORDER BY code_system_id, code;
```

The fixture introduces two condition concepts not present in the curated subset. They should be `unverified` and use the `condition` domain.

## 12. Run the full upstream generation

Requirements:

```text
Git
Java 17+
network access for the initial clone
```

PowerShell:

```powershell
.\scripts\generate_synthea.ps1
```

The workflow creates:

```text
data/synthea/synthea-us-small-v1/
├── upstream/synthea-4.0.0/
├── generated/csv/
├── normalized/
├── synthea-generation-manifest.json
└── normalized/synthea-adaptation-manifest.json
```

The generated workspace is ignored by Git.

## 13. Inspect the generation manifest

Confirm that it records:

```text
upstream_commit
Java version
normalized command
profile SHA-256
six exact source headers
source row counts
source byte sizes
source SHA-256 hashes
dataset_fingerprint
```

The command should use placeholders for machine-specific checkout and output paths.

## 14. Compare two full generations

Generate the same profile twice in separate workspaces.

Compare:

```text
profile SHA-256
upstream commit
source file SHA-256 values
dataset fingerprint
adaptation fingerprint
```

Interpretation:

```text
all equal
→ byte-identical generated and adapted artifacts

same profile, different source hashes
→ environment or upstream execution difference exposed by the manifest
```

Do not rewrite the manifest to force agreement.

## 15. Run the bundled platform demo with logs

```powershell
$env:CLINICAL_DATA_LOG_LEVEL = "INFO"
$env:CLINICAL_DATA_LOG_FORMAT = "json"
clinical-data run-demo --repository-root . 2> data/clinical-data.jsonl
```

The bundled demo remains a fast, deliberately invalid/valid sample for quality-control behavior. It is separate from the Synthea population.

## 16. Verify migration state

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

Synthea does not add V009 because the feature introduces profiles, manifests, adapters, and CLI workflows rather than database structure.

## 17. Inspect structured logs

```powershell
Get-Content data/clinical-data.jsonl | Select-Object -First 10
```

Every line must be valid JSON with:

```text
schema_version
timestamp
level
event
component
message
correlation_id
```

Synthea operations use events such as:

```text
synthea.checkout.started
synthea.generation.started
synthea.adaptation.started
synthea.adaptation.completed
```

Logs contain counts and fingerprints, not source clinical rows.

## 18. Inspect execution state

```sql
SELECT
    run_id,
    dataset_name,
    status,
    current_stage,
    attempt_count,
    failure_code,
    audit_event_count
FROM audit.pipeline_runs
ORDER BY updated_at DESC;
```

A clean run has:

```text
created
raw_captured
validating
validated
loading
completed
```

## 19. Inspect terminology bindings

```sql
SELECT
    dataset_name,
    entity_id,
    source_system,
    source_code,
    normalized_system,
    normalized_code,
    domain,
    verification_status
FROM terminology.normalized_clinical_codes
ORDER BY dataset_name, entity_id;
```

Distinguish curated project mappings from dynamically imported unverified Synthea concepts.

## 20. Review code in this order

1. `synthea_profiles/reproducible_small.toml`;
2. profile loader in `synthea.py`;
3. `build_synthea_command`;
4. generation manifest functions;
5. source header definitions;
6. six adapter functions;
7. adaptation manifest functions;
8. terminology import;
9. `load_adapted_synthea_dataset`;
10. `tests/test_synthea.py`;
11. existing `pipeline.py` and `database.py` to confirm reuse.

## 21. Key design questions

- Why are both random and clinician seeds fixed?
- Why is the reference date part of the dataset identity?
- Why is the resolved commit stored in addition to the tag?
- Why is generation single-threaded?
- What does the generation fingerprint cover?
- What does the adaptation fingerprint add?
- Why do missing source IDs become UUIDv5 rather than random UUIDv4?
- Why are unsupported observations omitted with counts?
- Why are new source concepts imported as unverified?
- Why does normal CI not execute the complete Java generator?
- Why is Synthea a source adapter rather than a new pipeline?

## 22. Known limitations

- full upstream generation is external to normal CI;
- the packaged profile contains 100 patients, not a benchmark-scale population;
- only six Synthea CSV files are adapted;
- only three observation concepts are retained;
- dynamic terminology imports are unverified;
- loading is still row-wise rather than PostgreSQL `COPY`;
- no epidemiological representativeness claim;
- no PHI controls or production deployment claim.
