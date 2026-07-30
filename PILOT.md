# Clinical pilot boundary

Clinical Data Platform may be used as an engineering foundation for a controlled clinic pilot, but the public repository is not a production clinical system and is not approved for identifiable patient data.

A defensible pilot:

- is limited to one agreed quality, research, or data-engineering question;
- begins with synthetic data or a clinic-approved de-identified extract processed in a clinic-controlled environment;
- preserves source, contract, execution, terminology, record, and cohort lineage;
- reports accepted, rejected, and explicitly omitted records;
- requires clinical review of cohort logic, terminology, units, missingness, and limitations;
- does not trigger diagnosis, treatment, triage, or any other patient-specific action.

Recommended first use case: a hypertension data-quality and cohort-reproducibility assessment.

Primary references:

- [Clinical pilot readiness](docs/clinical-pilot-readiness.md)
- [Clinical data coverage](docs/clinical-data-coverage.md)
- [Pilot data inventory template](templates/clinical-pilot-data-inventory.csv)
- [Pilot risk register template](templates/clinical-pilot-risk-register.csv)
- [Current limitations](docs/limitations.md)

The offer should be presented as a bounded professional service supported by the repository, not as an autonomous EHR, clinical decision-support product, medical device, or PHI-ready platform.
