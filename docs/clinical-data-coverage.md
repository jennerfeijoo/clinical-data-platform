# Clinical data coverage and extension priorities

## Purpose

This document defines what the current six-entity model represents, what it does not represent, and which additions are most valuable for a clinic pilot.

The model is intentionally compact. It supports reproducible clinical-data engineering demonstrations and bounded analytical pilots; it is not a complete electronic health record, FHIR implementation, OMOP warehouse, laboratory system, pharmacy system, or imaging archive.

## Current data model

```text
patients
   └── encounters
          ├── diagnoses
          ├── observations
          ├── medications
          └── procedures
```

Every event belongs to a patient and encounter. Patient demographics use a current snapshot plus SCD Type 2 history. Clinical events are immutable after acceptance.

## Exact current fields

### Patients

- `patient_id`
- `sex_at_birth`
- `birth_date`
- `death_date`
- `source_system`

### Encounters

- `encounter_id`
- `patient_id`
- `encounter_type`
- `start_datetime`
- `end_datetime`
- `source_system`

Supported encounter types are `OUTPATIENT`, `INPATIENT`, and `EMERGENCY`.

### Diagnoses

- `diagnosis_id`
- `patient_id`
- `encounter_id`
- `code_system`
- `diagnosis_code`
- `diagnosis_datetime`
- `source_system`

The contract accepts declared `ICD10` and `SNOMED` source-system labels. Persistence additionally requires resolution to an installed active condition concept.

### Observations

- `observation_id`
- `patient_id`
- `encounter_id`
- `observation_code`
- `value_numeric`
- `unit`
- `observed_at`
- `source_system`

The current contract supports only systolic blood pressure, diastolic blood pressure, and heart rate.

### Medications

- `medication_id`
- `patient_id`
- `encounter_id`
- `code_system`
- `medication_code`
- `status`
- `start_datetime`
- `end_datetime`
- `dose_value`
- `dose_unit`
- `route`
- `source_system`

The contract represents a compact medication event. It does not separately model prescribing, dispensing, administration, reconciliation, adherence, or pharmacy workflow.

### Procedures

- `procedure_id`
- `patient_id`
- `encounter_id`
- `code_system`
- `procedure_code`
- `procedure_datetime`
- `status`
- `source_system`

The contract represents a compact coded procedure event. It does not contain performer, body site, technique, report, device, indication, complication, or outcome details.

## Coverage matrix

| Domain | Current status | Main gap |
|---|---|---|
| Minimal demographics | Implemented | Administrative identity, contact, language, gender, address, insurance |
| Encounters | Implemented, compact | Organization, service, practitioner, location, disposition, referral |
| Diagnoses | Implemented, compact | Clinical status, verification, onset, resolution, severity, primary/secondary role |
| Vital signs | Very partial | Only blood pressure and heart rate |
| Laboratory results | Not implemented | Panels, specimens, reference ranges, flags, methods, qualitative results |
| Medications | Partial | Separate order, dispense, administration, reconciliation, frequency, indication |
| Procedures | Partial | Performer, site, technique, report, complications, outcomes |
| Allergies and intolerances | Not implemented | Agent, reaction, severity, criticality, verification |
| Immunizations | Not implemented | Product, dose, lot, route, site, performer, status |
| Clinical notes | Not implemented | Document metadata, authorship, sections, free-text governance |
| Imaging | Not implemented | Study/series metadata, DICOM/PACS link, report, annotation |
| Pathology | Not implemented | Specimen, report, morphology, stage, molecular findings |
| Care plans and goals | Not implemented | Intent, activities, targets, status |
| Appointments and referrals | Not implemented | Scheduling, referral source, reason, outcome |
| Devices and implants | Not implemented | Device identity, UDI, implantation, explantation |
| Pregnancy and reproductive history | Not implemented | Status, dates, outcomes |
| Social and family history | Not implemented | Tobacco, alcohol, occupation, family conditions |
| Patient-reported outcomes | Not implemented | Questionnaire, instrument, item and score provenance |
| Providers and organizations | Not implemented | Practitioner, role, specialty, institution, department |
| Consent and authorization | Not implemented | Purpose, status, scope, dates, revocation |
| Coverage, billing, and cost | Not implemented | Payer, claim, charge, reimbursement |
| Biospecimens | Not implemented | Specimen identity, collection, processing, storage |
| Genomics and other omics | Not implemented | Assay, reference build, variant, expression, QC |
| Physiological signals | Not implemented | Sampling, channels, calibration, artifacts, annotations |
| Model predictions | Not implemented | Model version, input cohort, calibration, threshold, monitoring |

## Minimum additions for a hypertension pilot

The current model can demonstrate a basic hypertension cohort, but a clinically useful quality pilot will commonly need:

1. practitioner, organization, service, and location context;
2. broader vital-sign representation, including repeated measurements and measurement position or method when available;
3. laboratory results relevant to renal function, diabetes, lipids, and treatment monitoring;
4. allergies and intolerances;
5. medication order, dispense, and administration distinctions;
6. dose frequency, strength, form, indication, and discontinuation reason;
7. problem status, onset, resolution, and primary/secondary diagnosis role;
8. smoking status and selected social history;
9. explicitly defined outcome and follow-up variables;
10. clinic-approved pseudonymous identity linkage.

These fields should be added only when they support a stated pilot question.

## Priority order for extension

### Priority 0: governance and identity

- pseudonymous patient identity;
- source-system identifier mapping;
- organization, location, practitioner, and role;
- consent or authorization references;
- data-retention and deletion metadata;
- access and export auditing.

### Priority 1: clinical safety and common analytics

- allergies and intolerances;
- laboratory tests and specimens;
- expanded observations and UCUM units;
- complete medication lifecycle;
- condition status and onset;
- immunizations;
- outcome definitions.

### Priority 2: interoperability

- FHIR import and export profiles;
- HL7 v2 adapters where required by local systems;
- complete terminology release lifecycle;
- UCUM validation and conversion;
- optional OMOP analytical export;
- DICOM/PACS metadata integration for imaging use cases.

### Priority 3: computational biomedicine

- biospecimens;
- genomic variants and assay provenance;
- expression, proteomic, or metabolomic measurements;
- imaging annotations and radiomic features;
- physiological time series;
- model registry, prediction provenance, validation, calibration, subgroup results, and drift evidence.

## Extension design rules

New domains should preserve the existing engineering guarantees:

- versioned executable contract;
- immutable raw source and receipt;
- deterministic identity rules;
- explicit accepted, rejected, and omitted counts;
- terminology and unit provenance;
- database migration rather than in-place schema editing;
- patient and encounter relationship checks;
- documented history policy;
- durable execution audit;
- structured logging without clinical values;
- cohort and feature lineage;
- tests and documentation;
- explicit non-clinical claim boundary until separately validated.

## Data discovery questions for a clinic

Before implementation, determine:

- Which source systems produce each domain?
- Are identifiers stable across systems and time?
- Which fields are direct or quasi-identifiers?
- Which fields contain free text?
- Which code systems and local catalogs are used?
- Are units explicit and consistent?
- Which timestamps represent order, collection, result, documentation, or administration?
- Are corrections and deletions represented?
- How are merged patient identities communicated?
- How is schema change announced?
- What is the clinically meaningful missingness denominator?
- Which outputs will be viewed by clinicians, analysts, or administrators?
- Could any output influence individual care?

The answers determine whether the pilot is technically and operationally defensible.
