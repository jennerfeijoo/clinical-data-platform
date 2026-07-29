# PostgreSQL migrations and persistence

## Responsibility split

```text
raw.py
    → exact source bytes and receipt integrity

contract.py
    → source-row acceptance rules

migration.py
    → ordered database structure

terminology.py
    → terminology inspection and binding validation

history.py
    → declared snapshot/event semantics

registry.py
    → typed row conversion and dataset SQL

database.py
    → lineage verification and transactional loading

PostgreSQL
    → foreign keys, concepts, hashes, history, immutability, rollback
```

## Migration history

```text
V001 core schemas and patients
V002 encounters, diagnoses, observations, cohorts
V003 contract lineage
V004 raw lineage
V005 patient SCD2 and immutable-event enforcement
V006 medications and procedures
V007 minimal clinical terminologies
```

`public.schema_migrations` stores version, name, checksum, application version, execution type, timestamp, and duration. Applied files are immutable.

## V007 terminology schema

V007 creates:

```text
terminology.code_systems
terminology.system_aliases
terminology.concepts
terminology.concept_mappings
terminology.normalized_clinical_codes
```

It also adds `normalized_concept_id` to:

```text
clinical.diagnoses
clinical.observations
clinical.medications
clinical.procedures
```

Each column is `NOT NULL` and references `terminology.concepts`.

## Resolution function

```sql
terminology.resolve_concept(
    p_source_system,
    p_source_code,
    p_expected_domain
)
```

The function:

1. requires non-empty system and code;
2. resolves the system alias;
3. locates the source concept;
4. follows an optional concept mapping;
5. requires an active target;
6. checks the clinical domain;
7. returns the normalized concept identifier.

Failures use PostgreSQL integrity errors so the dataset transaction rolls back.

## Trigger order

Terminology triggers are installed as `trg_00_*_terminology` and run before the existing immutable-event guards.

```text
incoming coded row
→ assign normalized_concept_id
→ calculate/check business-record hash
→ insert, no-op, or reject conflict
```

The normalized foreign key is not part of `record_sha256`. The source system and source code remain the stable business representation used by immutable-event comparison.

## Upgrade from V006

A V006 database may already contain codes that were accepted before terminology enforcement.

V007:

1. installs the curated subset;
2. imports previously accepted diagnosis, medication, and procedure codes that are absent from that subset;
3. labels imported entries `unverified`;
4. backfills all normalized foreign keys;
5. makes the columns mandatory;
6. installs strict triggers for future writes.

This avoids blocking a managed upgrade while preventing unverified legacy codes from being described as externally validated.

## New-write behavior

After V007, a new coded row is rejected when:

```text
source system alias missing
source code absent
concept inactive
normalized domain incorrect
```

Example:

```text
ICD10:ZZZ.999
→ contract may accept structure
→ terminology subset has no concept
→ PostgreSQL integrity error
→ complete diagnosis load rolls back
```

## Pre-transaction verification

Before database writes, `database.py` verifies:

1. output counts and completed status;
2. dataset identity;
3. retained contract path, version, and SHA-256;
4. raw storage version;
5. receipt UUID, timestamp, path, and manifest hash;
6. raw object path, byte size, and SHA-256;
7. parseable run metadata.

Terminology resolution occurs inside the write transaction because it depends on current database state.

## Transaction behavior

One load writes:

```text
audit.pipeline_runs
+ valid clinical rows
+ validation errors
+ terminology bindings
+ SCD2 transitions or immutable-event checks
```

All operations commit or roll back together.

The raw object, receipt, processed outputs, and quality report exist before this transaction. A database rollback does not delete those investigative artifacts.

## Exact immutable-event duplicate

```text
same event identifier
+ same source clinical content
→ terminology resolves consistently
→ immutable guard returns stored row
→ original source_run_id remains
```

## Conflicting immutable-event identity

```text
same event identifier
+ different source clinical content
→ terminology resolves or rejects
→ immutable conflict when content differs
→ complete load rollback
→ original event remains unchanged
```

## Migration detection

Version 7 is recognized only when all of these are present:

- four terminology base tables;
- four `normalized_concept_id` columns;
- the normalized-code inspection view;
- complete V006 structure.

A partial terminology schema is rejected rather than baselined.

## Upgrade commands

```powershell
clinical-data database-migrate --target-version 6
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

After the final command:

```text
detected=7
current=7
latest=7
pending=[]
```

## Review queries

Migration history:

```sql
SELECT version, name, checksum, execution_type, application_version, applied_at
FROM public.schema_migrations
ORDER BY version;
```

Registered systems:

```sql
SELECT
    code_system_id,
    canonical_uri,
    upstream_version,
    subset_version,
    complete_release,
    license_note
FROM terminology.code_systems
ORDER BY code_system_id;
```

Concept counts:

```sql
SELECT code_system_id, domain, verification_status, COUNT(*)
FROM terminology.concepts
GROUP BY code_system_id, domain, verification_status
ORDER BY code_system_id, domain, verification_status;
```

Normalized clinical rows:

```sql
SELECT *
FROM terminology.normalized_clinical_codes
ORDER BY dataset_name, entity_id;
```

Unbound or invalid rows should return zero:

```sql
SELECT COUNT(*)
FROM (
    SELECT normalized_concept_id, 'condition' AS expected_domain
    FROM clinical.diagnoses
    UNION ALL
    SELECT normalized_concept_id, 'observation'
    FROM clinical.observations
    UNION ALL
    SELECT normalized_concept_id, 'medication'
    FROM clinical.medications
    UNION ALL
    SELECT normalized_concept_id, 'procedure'
    FROM clinical.procedures
) AS binding
LEFT JOIN terminology.concepts AS concept
    ON concept.concept_id = binding.normalized_concept_id
WHERE concept.concept_id IS NULL
   OR NOT concept.active
   OR concept.domain <> binding.expected_domain;
```

## Limits

The database layer does not yet provide terminology release importers, hierarchy traversal, UCUM, FHIR terminology operations, complete execution-state auditing, structured logging, event supersession, tombstones, bitemporal modelling, bulk staging/`COPY`, production access controls, or PHI-ready governance.
