# Minimal clinical terminology integration

## Scope

The platform contains a small, versioned terminology subset that resolves coded clinical rows to normalized concepts at persistence time.

It is not a complete terminology server, not a replacement for official releases, and not evidence of full semantic interoperability.

## Data model

```text
source system + source code
        │
        ▼
terminology.system_aliases
        │
        ▼
terminology.concepts
        │
        ├── direct normalized concept
        └── terminology.concept_mappings
                │
                ▼
            target normalized concept
```

The database stores four terminology tables:

| Table | Responsibility |
|---|---|
| `terminology.code_systems` | registered systems, canonical URIs, authorities, subset versions, and licensing notes |
| `terminology.system_aliases` | source labels such as `ICD10` or `SNOMED` mapped to canonical local identifiers |
| `terminology.concepts` | codes, displays, domains, active state, and verification status |
| `terminology.concept_mappings` | reviewed or provisional mappings from one local concept to another |

## Registered systems

The bundled subset registers:

```text
ICD10CM
LOINC
RXNORM
ATC
SNOMEDCT
CPT
ICD10PCS
LOCAL_OBSERVATION
```

`complete_release` is false for every external terminology. Only the project-local observation system is represented completely.

## Canonical aliases

Examples:

```text
ICD10      → ICD10CM
SNOMED     → SNOMEDCT
RXNORM     → RXNORM
CPT        → CPT
ICD10PCS   → ICD10PCS
```

Aliases normalize source naming. They do not change the code itself unless a concept mapping is also present.

## Observation mappings

The project previously used three local observation codes. V007 preserves those source codes while mapping them to normalized LOINC concepts:

| Source code | Normalized system | Normalized code | Display |
|---|---|---|---|
| `SYSTOLIC_BP` | LOINC | `8480-6` | Systolic blood pressure |
| `DIASTOLIC_BP` | LOINC | `8462-4` | Diastolic blood pressure |
| `HEART_RATE` | LOINC | `8867-4` | Heart rate |

The original source code remains available in `clinical.observations`. `normalized_concept_id` points to the mapped LOINC concept.

## Clinical bindings

V007 adds `normalized_concept_id` to:

```text
clinical.diagnoses
clinical.observations
clinical.medications
clinical.procedures
```

Every accepted coded row must reference an active concept with the correct domain:

| Clinical table | Expected terminology domain |
|---|---|
| diagnoses | `condition` |
| observations | `observation` |
| medications | `medication` |
| procedures | `procedure` |

A database trigger resolves the concept before the existing immutable-event trigger executes.

## Strict persistence boundary

A source row may pass its executable file contract but fail persistence when:

- the source system has no registered alias;
- the code is absent from the installed subset;
- the concept is inactive;
- the resolved concept belongs to another domain.

The dataset transaction then rolls back, including its pending `audit.pipeline_runs` row. Raw capture and processed quarantine outputs remain available for investigation.

## Upgrade behavior

When V007 upgrades a populated V006 database, previously accepted diagnosis, medication, and procedure codes are imported into the local concept table when they are absent from the curated seed.

Such imported concepts receive:

```text
verification_status = unverified
source_reference = Imported from pre-V007 ...
```

This preserves database upgrade compatibility without falsely declaring those codes externally verified. New post-V007 rows remain subject to strict subset membership.

## Verification status

| Status | Meaning |
|---|---|
| `verified` | code and local display were checked against an identified upstream source |
| `curated` | project-local concept intentionally defined by this repository |
| `unverified` | retained for compatibility or represented without a verified external descriptor |

Verification status describes the local subset entry. It does not certify clinical correctness for a patient.

## Licensing boundary

The repository deliberately avoids redistributing complete licensed terminologies.

- LOINC entries are a very small subset and carry version metadata.
- SNOMED CT entries are illustrative subset records; use of complete releases remains subject to applicable licensing.
- CPT entries retain only codes and neutral local labels; licensed CPT descriptors are not distributed.
- ATC entries are represented as a small illustrative subset.
- CMS ICD-10-CM and ICD-10-PCS entries are limited to codes needed by the synthetic sample.
- RxNorm entries are limited to selected concepts used by the synthetic medication sample.

## Inspection view

`terminology.normalized_clinical_codes` exposes source and normalized representations together:

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

## Python API

```python
from clinical_data_platform.terminology import (
    list_terminology_systems,
    resolve_terminology_concept,
    validate_terminology_bindings,
)
```

The API provides deterministic inspection, individual concept resolution, and whole-database binding validation.

## Example resolution

```python
concept = resolve_terminology_concept(
    connection,
    "LOCAL_OBSERVATION",
    "SYSTOLIC_BP",
    "observation",
)

assert concept.code_system_id == "LOINC"
assert concept.code == "8480-6"
```

## Current limitations

The implementation does not provide:

- complete official terminology releases;
- automatic upstream synchronization;
- terminology release import tooling;
- hierarchy traversal or subsumption queries;
- synonyms, multilingual designations, or preferred-term selection;
- compositional SNOMED CT expressions;
- unit normalization through UCUM;
- many-to-many or context-sensitive mappings;
- historical mapping validity intervals;
- a FHIR terminology API;
- clinical validation of code selection.

Those capabilities require a dedicated terminology lifecycle rather than additional hard-coded rows in a migration.
