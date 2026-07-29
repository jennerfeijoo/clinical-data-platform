# Changelog

## 0.17.0

- raised statement coverage from 82% to more than 90% without excluding package modules;
- made the 90% minimum mandatory through shared pytest-cov and coverage configuration;
- added behavioral tests for the primary, cohort, benchmark, demo, and logging entrypoints;
- exercised real contracts, raw capture, validation, Synthea adaptation, cohort comparison, and quality reporting with synthetic fixtures;
- added governed failure-path tests for Synthea profiles, source artifacts, external commands, Git checkout state, and Java versions;
- retained PostgreSQL and Java boundaries as controlled doubles where unit tests must remain deterministic;
- documented the coverage policy, interpretation limits, and maintenance workflow;
- retained the synthetic-only, non-clinical, non-PHI project boundary.

## 0.16.0

- added reproducible source-to-adapted attrition reports for both Synthea cohorts;
- reconciled every entity as source rows equals adapted plus explicitly omitted rows;
- added omission-reason, source-missingness, adapted-missingness, and row-completeness CSV artifacts;
- classified adapted missingness as required, optional, or structural;
- added a stable paired quality fingerprint and descriptive cohort comparison;
- added `clinical-data-cohort quality-report`, PowerShell and POSIX runners;
- added CI, tests, technical documentation, and a Spanish learning guide;
- retained the synthetic-only, non-clinical, non-PHI project boundary.

## 0.15.0

- added a second packaged Synthea profile with independent patient and clinician seeds;
- added deterministic comparison evidence for two matched-design cohorts;
- required zero overlap across all six clinical identifier domains;
- added database preflight and separate processing lineage for pair loading;
- added `clinical-data-cohort`, PowerShell and POSIX runners;
- added unit, CLI, PostgreSQL integration, container, and documentation coverage;
- retained the synthetic-only, non-clinical, non-PHI project boundary.

## 0.14.0

- added the documented, balanced, correctness-gated PostgreSQL loading benchmark.
