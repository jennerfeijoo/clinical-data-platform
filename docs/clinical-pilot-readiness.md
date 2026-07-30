# Clinical pilot readiness

## Purpose

This document defines the defensible boundary for presenting the Clinical Data Platform to a clinic and for deciding whether a limited pilot may proceed.

The current repository is a stable synthetic clinical-data engineering platform. It is not a production electronic health record, a clinical decision-support system, a medical device, or a PHI-ready service.

## Defensible offer

The platform may be presented as an engineering accelerator for a controlled pilot that demonstrates:

- source-file inventory and reproducible ingestion;
- explicit data contracts;
- technical data-quality validation and quarantine;
- terminology linkage;
- PostgreSQL persistence with lineage and execution audit;
- reproducible analytical cohort construction;
- attrition and missingness evidence.

The pilot should sell a bounded professional service supported by the repository, not an autonomous clinical software product.

## Data boundary

The public repository and its default deployment remain synthetic-only.

A clinic pilot must start with one of these options:

1. synthetic data shaped like the clinic's exports;
2. a clinic-generated, formally reviewed de-identified extract processed inside a clinic-controlled environment;
3. appropriately licensed public data after a documented data-use review.

Identifiable patient data, free-text notes containing identifiers, direct identifiers, linkage keys, or production credentials must not be copied into the public repository, GitHub issues, pull requests, logs, sample files, benchmark artifacts, or support messages.

Use of de-identified data does not itself establish legal compliance, acceptable residual re-identification risk, ethical approval, or authorization for secondary use. Those decisions remain with the clinic and its responsible governance roles.

## Recommended first pilot

A defensible first pilot is a hypertension data-quality and cohort-reproducibility assessment.

### Clinical question

Can the clinic reproducibly identify an adult hypertension cohort and quantify whether the required demographic, encounter, diagnosis, blood-pressure, treatment, and follow-up data are sufficiently complete for a defined quality or research use case?

### Current reusable components

- patient, encounter, diagnosis, observation, medication, and procedure contracts;
- ICD-10/SNOMED, LOINC, RxNorm/ATC, CPT, and ICD-10-PCS terminology bindings within the installed subsets;
- hypertension cohort SQL;
- source, contract, execution, record, terminology, and cohort lineage;
- missingness, attrition, quarantine, and benchmark evidence.

### Required pilot extensions

The clinic-specific branch will normally require:

- source-system mapping;
- clinic identifiers converted to approved pseudonymous technical identifiers;
- local code-system and unit review;
- broader blood-pressure and laboratory representation when needed;
- practitioner, organization, and location context when the use case depends on them;
- explicit data-retention and deletion procedures;
- clinic-approved access, secret, backup, and incident controls.

## Go/no-go checklist

A pilot does not begin until all applicable items have an accountable owner and documented evidence.

### Governance

- named clinical sponsor;
- named data owner;
- named technical owner;
- documented purpose and success criteria;
- documented legal, ethical, and data-use approval;
- approved data minimization and retention period;
- approved handling location and transfer method;
- explicit decision on whether any data are identifiable, pseudonymous, or de-identified.

### Data understanding

- source-system inventory completed;
- data dictionary available;
- date range and approximate row counts known;
- patient and encounter linkage strategy documented;
- code systems and units identified;
- free-text fields identified and excluded or separately governed;
- known source-quality limitations recorded;
- schema-drift owner and notification process defined.

### Technical controls

- isolated pilot environment;
- no production credentials in source control;
- encrypted transport and storage supplied by the clinic environment;
- least-privilege database and filesystem access;
- audit-log destination and retention agreed;
- backup and recovery procedure tested when the pilot retains state;
- deletion procedure tested;
- dependency and container scans pass for the exact commit;
- release artifacts and checksums tied to the exact pilot build.

### Clinical interpretation

- cohort definition reviewed by a qualified clinical representative;
- terminology mappings reviewed for the pilot domain;
- plausible ranges treated as technical screening rules, not medical truth;
- missingness and attrition interpretation reviewed;
- outputs clearly labelled non-diagnostic and non-treatment-directing;
- no automated clinical action triggered by pilot outputs.

## Proposed pilot workflow

```text
clinic source inventory
→ synthetic or approved de-identified extract
→ clinic-specific mapping specification
→ immutable capture in the controlled environment
→ contract validation and quarantine
→ terminology and unit review
→ PostgreSQL load with lineage
→ reproducible cohort or quality report
→ joint technical and clinical review
→ acceptance decision
```

## Deliverables

A strong pilot package contains:

1. source-system and field inventory;
2. mapping specification and data dictionary;
3. executable clinic-specific contracts;
4. validation and quarantine report;
5. terminology and unit mapping report;
6. reproducible PostgreSQL loading workflow;
7. cohort or quality-analysis definition;
8. attrition and missingness report;
9. lineage and execution evidence;
10. limitations and residual-risk register;
11. deployment and deletion record;
12. final recommendation for stop, revise, or expand.

## Acceptance criteria

Acceptance criteria must be agreed before data processing. Suggested examples:

- every delivered file has a recorded checksum and receipt;
- every source row is reconciled as accepted, rejected, or explicitly omitted;
- required identifiers are non-empty and unique within their defined scope;
- patient and encounter relationships pass agreed referential checks;
- terminology mappings have a documented verification status;
- all required units are normalized or explicitly rejected;
- cohort membership is reproducible from versioned parameters and source runs;
- the same governed inputs produce the same stable analytical fingerprint;
- no identifiable data appear in logs, repository artifacts, or exported reports;
- all known limitations are presented in the final review.

Numerical targets must be selected from the clinic's use case. The repository must not invent acceptable missingness, error-rate, or clinical-performance thresholds.

## Roles

| Role | Responsibility |
|---|---|
| Clinical sponsor | Owns the clinical purpose and interpretation |
| Data owner | Authorizes data use, minimization, retention, and access |
| Privacy or governance lead | Reviews identifiability, legal basis, transfer, and deletion |
| Clinic IT or security | Provides the controlled environment and operational controls |
| Platform engineer | Implements mappings, contracts, loading, evidence, and reproducibility |
| Clinical reviewer | Reviews cohort logic, terminology, units, and limitations |
| Independent reviewer | Challenges acceptance evidence before expansion |

One person may hold more than one role in a small clinic, but responsibilities must remain explicit.

## Stop conditions

Pause the pilot when:

- the extract contains unapproved identifiers or free text;
- legal or ethical authorization is unclear;
- patient linkage cannot be performed reliably;
- source schema changes without review;
- terminology or unit ambiguity could change the interpretation;
- required clinical review is unavailable;
- security controls differ materially from the approved design;
- outputs are being used for patient-specific decisions;
- acceptance evidence cannot be reproduced.

## Commercial positioning

Recommended statement:

> Clinical Data Platform is an auditable engineering foundation for converting controlled clinical exports into validated, terminology-linked, reproducible analytical datasets. A proposed pilot is limited to one agreed use case, uses synthetic or clinic-approved de-identified data, and produces quality, lineage, and cohort evidence for joint review.

Do not claim:

- complete EHR coverage;
- production healthcare readiness;
- PHI readiness;
- regulatory compliance;
- medical-device status;
- diagnostic or treatment capability;
- validated epidemiological estimates;
- complete FHIR, HL7, DICOM, OMOP, or terminology-server interoperability.

## Expansion decision

After the pilot, expansion should require a new decision based on:

- data-quality evidence;
- user and workflow fit;
- clinical review;
- privacy and security findings;
- source-system integration effort;
- operating-cost estimate;
- support and maintenance capacity;
- regulatory classification;
- measurable value to the clinic.
