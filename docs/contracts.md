# Executable data contracts

The active data-contract set is selected by `src/clinical_data_platform/contracts/manifest.toml`.

Each dataset contract is an immutable, versioned TOML resource that declares:

- dataset identity and semantic version;
- primary and patient identifier fields;
- required columns and accepted column order;
- data types and required-value rules;
- uniqueness constraints;
- allowed categorical values;
- temporal ordering and not-in-future rules;
- measurement codes, units, and plausible ranges when applicable.

The contract engine loads and validates the definitions, applies them to source rows, and records the exact contract path, version, and SHA-256 in the quality evidence. Persistence reloads the referenced contract and rejects inconsistent or modified lineage.

Published contract files are retained. A behavior change requires a new contract version and an explicit manifest update rather than overwriting an existing contract.

Current contracts:

- `patients/v1.0.0.toml`;
- `encounters/v1.0.0.toml`;
- `diagnoses/v1.0.0.toml`;
- `observations/v1.0.0.toml`;
- `medications/v1.0.0.toml`;
- `procedures/v1.0.0.toml`.

Contracts validate configured technical and domain constraints. They do not establish that a source event is clinically true, complete, timely, or correctly interpreted.

Related references:

- [Clinical entities](clinical-entities.md)
- [Clinical data coverage](clinical-data-coverage.md)
- [Terminology](terminology.md)
- [Architecture](architecture.md)
