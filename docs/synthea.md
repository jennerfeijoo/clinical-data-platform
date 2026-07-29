# Reproducible Synthea dataset

## Scope

This workflow generates a synthetic population with a pinned Synthea release, records the exact generation inputs, adapts six upstream CSV files into the platform contracts, and verifies every source and output artifact by SHA-256.

Synthea produces synthetic records. This workflow must not be interpreted as a source of real patient data, epidemiological ground truth, or clinically representative prevalence for a target population.

## Reproducibility profile

The packaged profile is:

```text
src/clinical_data_platform/synthea_profiles/reproducible_small.toml
```

It pins:

| Control | Value |
|---|---|
| profile | `synthea-us-small-v1` |
| Synthea release | `v4.0.0` |
| population | 100 |
| random seed | 20260729 |
| clinician seed | 20260730 |
| reference date | 2026-07-29 |
| geography | Massachusetts |
| generator threads | 1 |
| years of history | 0 |
| export format | CSV |

Single-thread generation is deliberate. Parallel generation can make output ordering and some run-scoped identifiers harder to reproduce exactly.

## Why a tag is not enough

The profile pins `v4.0.0`, but the generation manifest also records the resolved upstream Git commit. This allows a previous result to retain the exact source identity even if an upstream ref were later moved or recreated.

The checkout must:

- resolve exactly to the configured tag;
- contain no uncommitted changes;
- use Java 17 or newer;
- be invoked without a shell-built command string.

## Exact upstream inputs

The command pins:

```text
-s random seed
-cs clinician seed
-p population size
-r reference date
--generate.thread_pool_size=1
--exporter.years_of_history=0
--exporter.csv.export=true
--exporter.csv.append_mode=false
--exporter.csv.folder_per_run=false
--exporter.csv.included_files=...
```

FHIR, hospital FHIR, practitioner FHIR, and metadata exporters are disabled for this workflow. Only the six required CSV files are requested.

## Source files

```text
patients.csv
encounters.csv
conditions.csv
observations.csv
medications.csv
procedures.csv
```

The adapter validates exact Synthea 4.0.0 headers before reading rows. A changed or reordered upstream header is treated as schema drift and fails before adaptation.

## Generation manifest

`synthea-generation-manifest.json` records:

```text
profile path and SHA-256
upstream repository, tag, version, and commit
Java version
normalized command
source file names
exact headers
row counts
byte sizes
SHA-256 hashes
dataset fingerprint
```

The normalized command replaces machine-specific checkout and output paths with placeholders. The actual source bytes remain identified by their individual hashes.

## Adapter boundary

The adapter creates:

```text
normalized/
├── patients.csv
├── encounters.csv
├── diagnoses.csv
├── observations.csv
├── medications.csv
├── procedures.csv
├── terminology.csv
└── synthea-adaptation-manifest.json
```

The output files match the existing executable contracts. No Synthea-specific validation or persistence pipeline was added.

### Patients

Synthea `Id`, `BIRTHDATE`, `DEATHDATE`, and `GENDER` become the internal patient fields. Gender values outside `F` and `M` become `UNKNOWN` because the source export does not provide a distinct sex-at-birth field for this adapter.

### Encounters

Encounter classes map as follows:

```text
inpatient → INPATIENT
emergency → EMERGENCY
all other classes → OUTPATIENT
```

The original encounter UUID is retained.

### Diagnoses

Synthea `conditions.csv` becomes `diagnoses.csv`. Because the source file has no stable condition-event identifier, the adapter generates a deterministic UUIDv5 from:

```text
dataset
source file
source row number
canonical source row content
```

Supported source systems are normalized to the contract names `SNOMED` or `ICD10`.

### Observations

The current platform contract intentionally accepts only:

| Synthea/LOINC code | Internal code | Internal unit |
|---|---|---|
| 8480-6 | `SYSTOLIC_BP` | `mmHg` |
| 8462-4 | `DIASTOLIC_BP` | `mmHg` |
| 8867-4 | `HEART_RATE` | `bpm` |

Other Synthea observations are omitted and counted in the adaptation manifest. They are not silently converted into the narrow observation contract.

### Medications

The Synthea medication CSV does not include a code-system column. The adapter treats its medication `CODE` as RxNorm, matching Synthea's native medication export convention.

Status is derived as:

```text
blank STOP → ACTIVE
STOP present → COMPLETED
```

Dose and route remain empty because the CSV source does not contain a reliable structured dose/route representation for this adapter.

### Procedures

Supported source systems are normalized to `SNOMED`, `CPT`, or `ICD10PCS`. Adapted procedures are marked `COMPLETED` because the CSV row represents an exported performed procedure event.

## Parent integrity

Every dependent event must reference:

- an included patient;
- an included encounter;
- the same patient as that encounter.

Rows that violate this condition are omitted with an explicit reason count.

## Terminology import

The adapter writes source concepts used by diagnoses, medications, and procedures to `terminology.csv`.

During `synthea-load`:

- existing concepts are reused;
- missing concepts are inserted into the existing canonical system;
- inserted concepts are marked `unverified`;
- a code cannot be imported into a conflicting clinical domain.

This supports loading the generated population without claiming that every source code was independently verified against an official terminology release.

## Adaptation manifest

`synthea-adaptation-manifest.json` records:

```text
adapter version
profile SHA-256
source file hashes and counts
output file hashes and counts
omitted-row reasons
terminology concept count
adaptation fingerprint
```

The adaptation fingerprint covers source fingerprints, output fingerprints, adapter version, profile hash, and omitted-row counts.

## Commands

Inspect the profile:

```powershell
clinical-data synthea-profile
```

Generate and adapt with the packaged workflow:

```powershell
.\scripts\generate_synthea.ps1
```

Manual sequence:

```powershell
clinical-data synthea-generate `
  --workspace data/synthea/synthea-us-small-v1

clinical-data synthea-adapt `
  data/synthea/synthea-us-small-v1/generated/csv `
  --output-dir data/synthea/synthea-us-small-v1/normalized `
  --generation-manifest data/synthea/synthea-us-small-v1/synthea-generation-manifest.json

clinical-data synthea-verify `
  data/synthea/synthea-us-small-v1/normalized
```

Load the six datasets:

```powershell
clinical-data synthea-load `
  data/synthea/synthea-us-small-v1/normalized `
  --processed-root data/processed/synthea `
  --raw-root data/raw
```

The load command uses the existing immutable raw capture, executable contracts, execution journals, structured logging, terminology layer, durable failure audit, and PostgreSQL persistence.

## What CI verifies

Normal CI does not clone and execute the full Java generator. It verifies:

- the packaged profile is installed;
- the profile contains the expected pinned controls;
- exact upstream CSV headers;
- deterministic adaptation;
- manifest verification and tamper detection;
- contract validity of every adapted output;
- terminology import;
- end-to-end loading through PostgreSQL.

A small checked-in fixture is used for these tests. It is a schema and behavior fixture, not the final 100-patient generated dataset.

## Reproducibility claim

The implementation can verify exact repeatability when two executions produce the same source-file hashes and dataset fingerprint. Fixed inputs substantially reduce variability, but the repository does not claim that every future operating system, JVM, or upstream dependency environment will always produce byte-identical outputs. The manifest exposes such differences rather than hiding them.

## Current limits

- the adapter supports only six Synthea CSV files;
- observations are intentionally restricted to three vital-sign concepts;
- terminology entries absent from the local subset are imported as unverified;
- no upstream Java generation occurs in standard CI;
- generated workspaces are ignored by Git;
- row-wise PostgreSQL loading remains in use;
- bulk `COPY` and performance benchmarking are the next milestones;
- no epidemiological or clinical-validity claim is made.
