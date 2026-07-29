# Repository analysis guide

This sequence is intended for reviewing the repository after running the bundled demonstration.

## 1. Run the complete workflow

```powershell
clinical-data run-demo --repository-root .
```

The workflow captures six raw datasets, executes their contracts, migrates PostgreSQL through V007, resolves coded concepts, persists accepted rows, and builds the hypertension cohort.

## 2. Verify migration state

```powershell
clinical-data database-status
clinical-data database-validate
```

Expected:

```text
detected=7
current=7
latest=7
pending=[]
```

Inspect:

```sql
SELECT version, name, checksum, execution_type, application_version, applied_at
FROM public.schema_migrations
ORDER BY version;
```

V007 should be `add_minimal_clinical_terminologies`.

## 3. Inspect active contracts

```powershell
clinical-data list-contracts
clinical-data validate-contracts
clinical-data show-contract diagnoses
clinical-data show-contract observations
clinical-data show-contract medications
clinical-data show-contract procedures
```

Contracts validate source structure and declared categorical systems. They do not contain complete external code lists.

## 4. Inspect raw and processed layers

```text
data/raw/
├── objects/sha256/
└── receipts/

data/processed/<dataset>/
├── valid_<dataset>.csv
├── invalid_<dataset>.csv
├── validation_errors.csv
└── quality_report.json
```

Confirm that source, raw receipt, contract, run, reference date, and row counts remain traceable independently of terminology resolution.

## 5. Inspect registered terminology systems

```sql
SELECT
    code_system_id,
    canonical_uri,
    display_name,
    authority,
    upstream_version,
    subset_version,
    complete_release,
    license_note
FROM terminology.code_systems
ORDER BY code_system_id;
```

Review questions:

- Which system is represented completely?
- Which external releases have explicit versions?
- Which systems have unresolved upstream-version metadata?
- Why are licensing notes stored with the registry?

## 6. Inspect aliases

```sql
SELECT source_system, code_system_id
FROM terminology.system_aliases
ORDER BY source_system;
```

Expected examples:

```text
ICD10  → ICD10CM
SNOMED → SNOMEDCT
```

An alias canonicalizes the system identifier. It does not map the source code to a different code.

## 7. Inspect concepts

```sql
SELECT
    concept_id,
    code_system_id,
    code,
    display,
    domain,
    active,
    verification_status,
    source_reference
FROM terminology.concepts
ORDER BY domain, code_system_id, code;
```

Confirm that concepts are separated into:

```text
condition
observation
medication
procedure
```

## 8. Inspect mappings

```sql
SELECT
    source_system.code_system_id AS source_system,
    source.code AS source_code,
    target_system.code_system_id AS target_system,
    target.code AS target_code,
    mapping.equivalence,
    mapping.mapping_version,
    mapping.review_status,
    mapping.mapping_method
FROM terminology.concept_mappings AS mapping
JOIN terminology.concepts AS source
    ON source.concept_id = mapping.source_concept_id
JOIN terminology.code_systems AS source_system
    ON source_system.code_system_id = source.code_system_id
JOIN terminology.concepts AS target
    ON target.concept_id = mapping.target_concept_id
JOIN terminology.code_systems AS target_system
    ON target_system.code_system_id = target.code_system_id
ORDER BY source_system, source_code;
```

Expected mappings:

```text
SYSTOLIC_BP  → LOINC 8480-6
DIASTOLIC_BP → LOINC 8462-4
HEART_RATE   → LOINC 8867-4
```

## 9. Compare source and normalized codes

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

Expected total after a clean demo:

```text
31 coded clinical rows
```

This comprises:

```text
6 diagnoses
13 observations
6 medications
6 procedures
```

## 10. Trace one observation

Follow `O001`:

```text
observations.csv
→ observation_code = SYSTOLIC_BP
→ executable observation contract
→ valid_observations.csv
→ registry conversion
→ terminology alias LOCAL_OBSERVATION
→ source concept SYSTOLIC_BP
→ reviewed mapping
→ LOINC 8480-6
→ clinical.observations.normalized_concept_id
```

Verify:

```sql
SELECT *
FROM terminology.normalized_clinical_codes
WHERE dataset_name = 'observations'
  AND entity_id = 'O001';
```

## 11. Trace one diagnosis

```sql
SELECT *
FROM terminology.normalized_clinical_codes
WHERE dataset_name = 'diagnoses'
  AND entity_id = 'D002';
```

Expected:

```text
source system = ICD10
source code = I10
normalized system = ICD10CM
normalized code = I10
domain = condition
```

This uses a system alias, not a cross-code mapping.

## 12. Trace one medication

```sql
SELECT *
FROM terminology.normalized_clinical_codes
WHERE dataset_name = 'medications'
  AND entity_id = 'M001';
```

Expected normalized representation:

```text
RXNORM:197361
```

Inspect its `verification_status` and `source_reference` in `terminology.concepts`.

## 13. Demonstrate unknown-code rejection

Create a valid copy of `diagnoses.csv` with:

```text
D001.diagnosis_code = ZZZ.999
```

The file contract can accept the row because it is non-empty and the system is allowed. Persistence must fail because the installed terminology subset has no matching concept.

After failure verify:

```text
clinical.diagnoses contains no partial rows
the failed audit.pipeline_runs row was rolled back
raw object and receipt remain
processed outputs remain
```

This demonstrates the boundary between structural validity and recognized clinical semantics.

## 14. Demonstrate wrong-domain rejection

Run directly in PostgreSQL on a disposable database:

```sql
SELECT terminology.resolve_concept(
    'LOINC',
    '8480-6',
    'medication'
);
```

The concept exists but belongs to `observation`, so resolution must fail.

## 15. Inspect V006 to V007 upgrade compatibility

On a disposable database:

```powershell
clinical-data database-migrate --target-version 6
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

To test compatibility thoroughly:

1. load a V006-coded row not present in the curated V007 seed;
2. apply V007;
3. find the imported concept;
4. confirm `verification_status = unverified`;
5. confirm its clinical row has a non-null normalized foreign key.

This behavior supports upgrades without presenting legacy codes as verified.

## 16. Validate all terminology bindings

Using Python:

```python
from clinical_data_platform.terminology import validate_terminology_bindings

summary = validate_terminology_bindings(connection)
assert summary.invalid_bindings == 0
```

The check requires every coded row to have an existing, active concept in the correct domain.

## 17. Inspect patient history and immutable events

Terminology integration does not replace the existing history policy.

```sql
SELECT *
FROM clinical.patient_history
ORDER BY patient_id, patient_version_id;
```

For an immutable coded event, an exact duplicate preserves the original row. A changed source code with the same event identifier remains a conflict and rolls back.

## 18. Confirm cohort stability

```sql
SELECT *
FROM analytics.hypertension_features
ORDER BY patient_id;
```

Expected patients remain:

```text
P001
P002
```

Adding terminology bindings must not silently change the existing cohort definition.

## 19. Review code in this order

1. `V007__add_minimal_clinical_terminologies.sql`;
2. `terminology.py`;
3. `migration.py` V007 detection;
4. `tests/test_terminology.py`;
5. `tests/test_migration.py`;
6. `tests/test_analysis_workflow.py`;
7. `docs/terminology.md`;
8. `docs/learning/minimal-clinical-terminologies-es.md`.

For each component identify:

```text
responsibility
enforcement boundary
lineage retained
failure behavior
licensing assumption
unimplemented production capability
```

## 20. Key design questions

- Why preserve source codes after normalization?
- What is the difference between a system alias and a concept mapping?
- Why can a contract-valid row fail terminology resolution?
- Why is domain validation necessary when the code already exists?
- Why are legacy V006 codes imported as `unverified`?
- Why is `normalized_concept_id` not included in immutable business hashes?
- Why are complete CPT and SNOMED CT releases absent?
- What would a reproducible terminology release importer need to record?
- Why is this not a FHIR terminology server?

## 21. Known limitations

- small local terminology subset;
- no release import pipeline;
- no automatic upstream synchronization;
- no hierarchy or subsumption queries;
- no UCUM unit normalization;
- no multilingual terms;
- no contextual many-to-many mappings;
- no FHIR terminology operations;
- no complete execution-state audit or structured logs;
- no PHI controls or production deployment claims.
