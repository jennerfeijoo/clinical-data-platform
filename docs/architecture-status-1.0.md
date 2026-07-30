# Architecture status at 1.0.0

This note resolves a documentation-drift risk by stating the implemented stable architecture without editing historical explanatory sections.

Implemented at version `1.0.0`:

- PostgreSQL `COPY FROM STDIN` through typed temporary staging;
- governed set-based merge with constraints, terminology triggers, hashes, history, and audit active;
- a documented correctness-gated loading benchmark;
- two independent matched-design Synthea cohorts;
- attrition and missingness evidence for both cohorts;
- CPython 3.11-3.14 CI;
- security scanning, non-root container hardening, and reproducible release artifacts.

Remaining architecture gaps include:

- FHIR, HL7 v2, DICOM, OMOP, and production EHR integration;
- complete terminology importers, lifecycle management, hierarchy queries, and UCUM normalization;
- identity matching, consent, user authentication, authorization, and access auditing;
- centralized log transport, OpenTelemetry, metrics, dashboards, and scheduler recovery;
- multi-writer or distributed exactly-once semantics;
- streaming validation for very large source files;
- production capacity, availability, backup, disaster-recovery, and service-level validation;
- PHI handling, clinical validation, epidemiological validity, and regulatory deployment controls.

The canonical limitation register remains [limitations.md](limitations.md). When any older prose conflicts with executable evidence, use migrations, contracts, source code, policy tests, and commit-specific CI evidence as the source of truth.
