# Current limitations and claim boundaries

This document consolidates the boundaries that must remain visible when reviewing or reusing the project.

## Data and clinical scope

The repository uses synthetic data and may support appropriately licensed public data after explicit review. It is not approved for identifiable patient information or PHI.

The platform does not provide:

- diagnosis, prognosis, treatment selection, triage, or clinical decision support;
- clinical validation, epidemiological representativeness, or causal inference;
- regulatory compliance, medical-device certification, or hospital deployment approval;
- privacy governance, consent management, de-identification certification, or data-use authorization.

The bundled cohorts and quality reports are engineering fixtures. Their prevalence, missingness, attrition, and outcomes must not be interpreted as estimates for a real population.

## Storage and immutability

The raw landing zone is content-addressed and append-only at application level. A conventional local filesystem is not WORM storage. An administrator or compromised host can still modify files outside the application controls.

The local validation journal is hash-chained and tamper-evident. It is not a cryptographically signed transparency log and does not prevent deletion, replacement, or rollback by a privileged actor.

## Database and transaction scope

The six-entity clinical load is transactional per dataset execution. The two-cohort workflow is not one global transaction across all twelve dataset loads.

Completed dataset executions are idempotent under their governed run identity. The system does not provide distributed exactly-once semantics, a scheduler, worker leases, automatic retry policy, or cross-service transaction coordination.

The patient table uses current snapshot plus SCD Type 2 history. The remaining entities are immutable events. This policy is an engineering design, not a complete clinical source-of-truth model.

## Terminology

The repository contains small local subsets for selected code systems. They are not complete official releases and do not establish licensing rights, semantic completeness, hierarchy traversal, equivalence reasoning, or clinical validation.

The project does not implement a terminology server, FHIR terminology operations, full UCUM validation, or automated ontology updates.

## Validation and quality evidence

Executable contracts detect configured schema, type, domain, date, order, uniqueness, and measurement constraints. They do not establish that a source event is clinically true, complete, timely, or correctly interpreted.

Contract validation currently materializes complete source datasets in memory. This limits source size and is separate from the bulk PostgreSQL loading path.

Attrition means technical row exclusion during adaptation. It is not participant withdrawal or loss to follow-up. Missingness categories do not determine MCAR, MAR, or MNAR.

## Performance

The documented benchmark measures deterministic initial, single-writer persistence into PostgreSQL with active constraints and governance. It does not measure:

- complete pipeline latency;
- concurrent writers or readers;
- remote network and storage behavior;
- multi-million-row scaling;
- memory ceilings;
- production throughput, availability, or service-level objectives.

Benchmark results are tied to the recorded environment and workload.

## Security

Automated controls include dependency auditing, Bandit, CodeQL, Trivy, Dependabot, pinned GitHub Actions, and a non-root container profile. These controls do not replace threat modeling, manual secure-code review, penetration testing, secret management, network policy, host hardening, incident response, or supply-chain verification.

The container profile reduces privileges but does not prove resistance to container escapes, kernel vulnerabilities, malicious dependencies, unsafe mounts, or deployment misconfiguration.

## Release and support

Release artifacts are checked for metadata consistency, content, reproducibility under the configured build environment, and installation from the wheel. This does not establish reproducibility across every operating system, build backend, CPU architecture, or future toolchain.

The project is maintained through the current `main` branch without a guaranteed response time or long-term support commitment. See [`SUPPORT.md`](../SUPPORT.md).

## Appropriate interpretation

The defensible claim is that this repository demonstrates an auditable synthetic clinical-data engineering architecture with executable governance and reproducible evidence under its documented tests.

It does not demonstrate a production clinical platform.
