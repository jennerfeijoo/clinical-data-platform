"""Independent reproducible Synthea cohort orchestration and evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, Final

import psycopg

from clinical_data_platform.synthea import (
    PROFILE_PACKAGE,
    SyntheaAdaptationSummary,
    SyntheaLoadSummary,
    SyntheaProfile,
    load_adapted_synthea_dataset,
    load_synthea_profile,
    verify_synthea_adaptation,
)

COHORT_COMPARISON_SCHEMA_VERSION: Final = "1.0.0"
COHORT_LOAD_MANIFEST_VERSION: Final = "1.0.0"
DEFAULT_COHORT_A_PROFILE: Final = "synthea-us-small-v1"
DEFAULT_COHORT_B_PROFILE: Final = "synthea-us-small-cohort-b-v1"
COHORT_LABEL_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

PACKAGED_PROFILE_RESOURCES: Final[dict[str, str]] = {
    DEFAULT_COHORT_A_PROFILE: "reproducible_small.toml",
    DEFAULT_COHORT_B_PROFILE: "reproducible_small_cohort_b.toml",
}

DATASET_ID_COLUMNS: Final[dict[str, str]] = {
    "patients": "patient_id",
    "encounters": "encounter_id",
    "diagnoses": "diagnosis_id",
    "observations": "observation_id",
    "medications": "medication_id",
    "procedures": "procedure_id",
}


class SyntheaCohortError(RuntimeError):
    """Raised when two synthetic cohorts cannot be treated as independent replicas."""


@dataclass(frozen=True, slots=True)
class SyntheaCohortSnapshot:
    """Stable evidence for one verified adapted Synthea cohort."""

    label: str
    profile_name: str
    profile_sha256: str
    random_seed: int
    clinician_seed: int
    adaptation_fingerprint: str
    dataset_rows: dict[str, int]
    omitted_rows: dict[str, int]
    terminology_concepts: int
    identifier_counts: dict[str, int]
    identifier_fingerprints: dict[str, str]
    normalized_directory: Path


@dataclass(frozen=True, slots=True)
class SyntheaCohortComparisonSummary:
    """Artifacts and deterministic identity for one two-cohort comparison."""

    cohort_a: SyntheaCohortSnapshot
    cohort_b: SyntheaCohortSnapshot
    comparison_fingerprint: str
    overlap_counts: dict[str, int]
    manifest_path: Path
    markdown_path: Path


@dataclass(frozen=True, slots=True)
class SyntheaCohortPairLoadSummary:
    """Result of loading two verified disjoint cohorts into one PostgreSQL database."""

    comparison: SyntheaCohortComparisonSummary
    cohort_a_load: SyntheaLoadSummary
    cohort_b_load: SyntheaLoadSummary
    load_manifest_path: Path
    load_execution_fingerprint: str


@dataclass(frozen=True, slots=True)
class _CohortMaterial:
    profile: SyntheaProfile
    adaptation: SyntheaAdaptationSummary
    snapshot: SyntheaCohortSnapshot
    identifiers: dict[str, frozenset[str]]


def packaged_synthea_profile_names() -> tuple[str, ...]:
    """Return the stable names of all packaged reproducibility profiles."""
    return tuple(PACKAGED_PROFILE_RESOURCES)


def load_packaged_synthea_profile(name: str) -> SyntheaProfile:
    """Load one packaged profile by its stable profile name."""
    resource_name = PACKAGED_PROFILE_RESOURCES.get(name)
    if resource_name is None:
        available = ", ".join(packaged_synthea_profile_names())
        raise SyntheaCohortError(
            f"Unknown packaged Synthea profile {name!r}; available profiles: {available}."
        )
    resource = files(PROFILE_PACKAGE).joinpath(resource_name)
    with as_file(resource) as profile_path:
        profile = load_synthea_profile(profile_path)
    if profile.name != name:
        raise SyntheaCohortError(
            f"Packaged resource {resource_name!r} declares profile {profile.name!r}, "
            f"not {name!r}."
        )
    return profile


def _normalize_cohort_label(label: str) -> str:
    normalized = label.strip()
    if not COHORT_LABEL_PATTERN.fullmatch(normalized):
        raise SyntheaCohortError(
            "Cohort labels must be safe single path components matching "
            "^[a-z][a-z0-9_-]{0,63}$."
        )
    return normalized


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json_sha256(document: Mapping[str, object]) -> str:
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(document, file, indent=2, sort_keys=True, ensure_ascii=False)
        file.write("\n")


def _profile_design_document(profile: SyntheaProfile) -> dict[str, object]:
    return {
        "source_system": profile.source_system,
        "upstream_repository": profile.upstream_repository,
        "upstream_ref": profile.upstream_ref,
        "upstream_version": profile.upstream_version,
        "population_size": profile.population_size,
        "reference_date": profile.reference_date.isoformat(),
        "state": profile.state,
        "city": profile.city,
        "thread_pool_size": profile.thread_pool_size,
        "years_of_history": profile.years_of_history,
        "included_files": list(profile.included_files),
    }


def _read_identifiers(
    normalized_directory: Path,
    dataset: str,
    identifier_column: str,
) -> frozenset[str]:
    path = normalized_directory / f"{dataset}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Adapted cohort dataset not found: {path}")
    identifiers: list[str] = []
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if identifier_column not in tuple(reader.fieldnames or ()):
            raise SyntheaCohortError(
                f"Dataset {dataset!r} has no identifier column {identifier_column!r}."
            )
        for row_number, row in enumerate(reader, start=2):
            raw = row.get(identifier_column)
            identifier = raw.strip() if isinstance(raw, str) else ""
            if not identifier:
                raise SyntheaCohortError(
                    f"Dataset {dataset!r} has a blank identifier at row {row_number}."
                )
            identifiers.append(identifier)
    unique = frozenset(identifiers)
    if len(unique) != len(identifiers):
        raise SyntheaCohortError(
            f"Dataset {dataset!r} contains duplicate values in {identifier_column!r}."
        )
    return unique


def _identifier_fingerprint(identifiers: frozenset[str]) -> str:
    canonical = "\n".join(sorted(identifiers))
    if canonical:
        canonical += "\n"
    return _sha256_bytes(canonical.encode("utf-8"))


def _cohort_material(
    label: str,
    profile_name: str,
    normalized_directory: Path,
) -> _CohortMaterial:
    normalized_label = _normalize_cohort_label(label)
    profile = load_packaged_synthea_profile(profile_name)
    adaptation = verify_synthea_adaptation(
        normalized_directory,
        profile=profile,
    )
    identifiers = {
        dataset: _read_identifiers(normalized_directory, dataset, identifier_column)
        for dataset, identifier_column in DATASET_ID_COLUMNS.items()
    }
    for dataset, values in identifiers.items():
        expected = adaptation.dataset_rows[dataset]
        if len(values) != expected:
            raise SyntheaCohortError(
                f"Identifier count for {dataset!r} is {len(values)}; expected {expected}."
            )
    snapshot = SyntheaCohortSnapshot(
        label=normalized_label,
        profile_name=profile.name,
        profile_sha256=profile.sha256,
        random_seed=profile.random_seed,
        clinician_seed=profile.clinician_seed,
        adaptation_fingerprint=adaptation.adaptation_fingerprint,
        dataset_rows=dict(adaptation.dataset_rows),
        omitted_rows=dict(adaptation.omitted_rows),
        terminology_concepts=adaptation.terminology_concepts,
        identifier_counts={dataset: len(values) for dataset, values in identifiers.items()},
        identifier_fingerprints={
            dataset: _identifier_fingerprint(values)
            for dataset, values in identifiers.items()
        },
        normalized_directory=normalized_directory,
    )
    return _CohortMaterial(
        profile=profile,
        adaptation=adaptation,
        snapshot=snapshot,
        identifiers=identifiers,
    )


def _snapshot_document(snapshot: SyntheaCohortSnapshot) -> dict[str, object]:
    return {
        "label": snapshot.label,
        "profile_name": snapshot.profile_name,
        "profile_sha256": snapshot.profile_sha256,
        "random_seed": snapshot.random_seed,
        "clinician_seed": snapshot.clinician_seed,
        "adaptation_fingerprint": snapshot.adaptation_fingerprint,
        "dataset_rows": dict(sorted(snapshot.dataset_rows.items())),
        "omitted_rows": dict(sorted(snapshot.omitted_rows.items())),
        "terminology_concepts": snapshot.terminology_concepts,
        "identifier_counts": dict(sorted(snapshot.identifier_counts.items())),
        "identifier_fingerprints": dict(
            sorted(snapshot.identifier_fingerprints.items())
        ),
    }


def _prepare_output_directory(output_directory: Path, *, replace: bool) -> None:
    if output_directory.exists() and any(output_directory.iterdir()):
        if not replace:
            raise SyntheaCohortError(
                f"Cohort comparison output is not empty: {output_directory}; "
                "use replace=True."
            )
        shutil.rmtree(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)


def _write_comparison_markdown(
    path: Path,
    cohort_a: SyntheaCohortSnapshot,
    cohort_b: SyntheaCohortSnapshot,
    comparison_fingerprint: str,
) -> None:
    lines = [
        "# Reproducible Synthea cohort comparison",
        "",
        "Both cohorts use the same pinned study design and independent random seeds.",
        "All six clinical identifier domains are required to be disjoint.",
        "",
        "| Control | Cohort A | Cohort B |",
        "|---|---|---|",
        f"| Label | `{cohort_a.label}` | `{cohort_b.label}` |",
        f"| Profile | `{cohort_a.profile_name}` | `{cohort_b.profile_name}` |",
        f"| Random seed | {cohort_a.random_seed} | {cohort_b.random_seed} |",
        f"| Clinician seed | {cohort_a.clinician_seed} | {cohort_b.clinician_seed} |",
        (
            "| Adaptation fingerprint | "
            f"`{cohort_a.adaptation_fingerprint}` | "
            f"`{cohort_b.adaptation_fingerprint}` |"
        ),
        "",
        "## Adapted row counts",
        "",
        "| Dataset | Cohort A | Cohort B | Identifier overlap |",
        "|---|---:|---:|---:|",
    ]
    for dataset in DATASET_ID_COLUMNS:
        lines.append(
            f"| {dataset} | {cohort_a.dataset_rows[dataset]} | "
            f"{cohort_b.dataset_rows[dataset]} | 0 |"
        )
    lines.extend(
        [
            "",
            "## Combined identity",
            "",
            f"`sha256:{comparison_fingerprint}`",
            "",
            "This artifact demonstrates engineering reproducibility and cohort separation. ",
            "It does not establish clinical representativeness or epidemiological validity.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def compare_synthea_cohorts(
    cohort_a_directory: Path,
    cohort_b_directory: Path,
    output_directory: Path,
    *,
    cohort_a_profile_name: str = DEFAULT_COHORT_A_PROFILE,
    cohort_b_profile_name: str = DEFAULT_COHORT_B_PROFILE,
    cohort_a_label: str = "cohort_a",
    cohort_b_label: str = "cohort_b",
    replace: bool = False,
) -> SyntheaCohortComparisonSummary:
    """Verify two matched-design adaptations and prove identifier-level independence."""
    normalized_a_label = _normalize_cohort_label(cohort_a_label)
    normalized_b_label = _normalize_cohort_label(cohort_b_label)
    if normalized_a_label == normalized_b_label:
        raise SyntheaCohortError("Cohort labels must be distinct after normalization.")
    if cohort_a_profile_name == cohort_b_profile_name:
        raise SyntheaCohortError("Independent cohorts must use distinct profiles.")

    cohort_a = _cohort_material(
        normalized_a_label,
        cohort_a_profile_name,
        cohort_a_directory,
    )
    cohort_b = _cohort_material(
        normalized_b_label,
        cohort_b_profile_name,
        cohort_b_directory,
    )

    design_a = _profile_design_document(cohort_a.profile)
    design_b = _profile_design_document(cohort_b.profile)
    if design_a != design_b:
        raise SyntheaCohortError(
            "Cohort profiles do not share the same controlled study design."
        )
    if cohort_a.profile.sha256 == cohort_b.profile.sha256:
        raise SyntheaCohortError("Cohort profile hashes must differ.")
    if cohort_a.profile.random_seed == cohort_b.profile.random_seed:
        raise SyntheaCohortError("Cohort random seeds must differ.")
    if cohort_a.profile.clinician_seed == cohort_b.profile.clinician_seed:
        raise SyntheaCohortError("Cohort clinician seeds must differ.")
    if (
        cohort_a.adaptation.adaptation_fingerprint
        == cohort_b.adaptation.adaptation_fingerprint
    ):
        raise SyntheaCohortError("Cohort adaptation fingerprints must differ.")

    overlaps = {
        dataset: cohort_a.identifiers[dataset] & cohort_b.identifiers[dataset]
        for dataset in DATASET_ID_COLUMNS
    }
    populated_overlaps = {
        dataset: values for dataset, values in overlaps.items() if values
    }
    if populated_overlaps:
        details = "; ".join(
            f"{dataset}={sorted(values)[:5]}"
            for dataset, values in populated_overlaps.items()
        )
        raise SyntheaCohortError(
            "Independent cohort identifiers overlap; refusing comparison: " + details
        )

    stable_document: dict[str, object] = {
        "schema_version": COHORT_COMPARISON_SCHEMA_VERSION,
        "study_design": design_a,
        "cohorts": [
            _snapshot_document(cohort_a.snapshot),
            _snapshot_document(cohort_b.snapshot),
        ],
        "identifier_overlap_counts": {
            dataset: len(values) for dataset, values in overlaps.items()
        },
    }
    comparison_fingerprint = _canonical_json_sha256(stable_document)
    _prepare_output_directory(output_directory, replace=replace)

    manifest_path = output_directory / "synthea-cohort-comparison.json"
    markdown_path = output_directory / "synthea-cohort-comparison.md"
    manifest: dict[str, object] = {
        **stable_document,
        "created_at": datetime.now(UTC).isoformat(),
        "comparison_fingerprint": comparison_fingerprint,
        "locations": {
            cohort_a.snapshot.label: str(cohort_a_directory),
            cohort_b.snapshot.label: str(cohort_b_directory),
        },
    }
    _write_json(manifest_path, manifest)
    _write_comparison_markdown(
        markdown_path,
        cohort_a.snapshot,
        cohort_b.snapshot,
        comparison_fingerprint,
    )
    return SyntheaCohortComparisonSummary(
        cohort_a=cohort_a.snapshot,
        cohort_b=cohort_b.snapshot,
        comparison_fingerprint=comparison_fingerprint,
        overlap_counts={dataset: len(values) for dataset, values in overlaps.items()},
        manifest_path=manifest_path,
        markdown_path=markdown_path,
    )


def _assert_database_identifiers_are_disjoint(
    connection: psycopg.Connection[Any],
    materials: tuple[_CohortMaterial, _CohortMaterial],
) -> None:
    for dataset, identifier_column in DATASET_ID_COLUMNS.items():
        identifiers = sorted(
            materials[0].identifiers[dataset] | materials[1].identifiers[dataset]
        )
        if not identifiers:
            continue
        rows = connection.execute(
            f"SELECT {identifier_column} FROM clinical.{dataset} "
            f"WHERE {identifier_column} = ANY(%s) ORDER BY {identifier_column}",
            (identifiers,),
        ).fetchall()
        if rows:
            examples = [str(row[0]) for row in rows[:5]]
            raise SyntheaCohortError(
                f"Target database already contains {dataset} identifiers from the "
                f"cohort pair: {examples}. Use a clean database or another cohort pair."
            )


def _load_summary_document(summary: SyntheaLoadSummary) -> dict[str, object]:
    return {
        "terminology": {
            "concepts_received": summary.terminology.concepts_received,
            "concepts_inserted": summary.terminology.concepts_inserted,
            "concepts_existing": summary.terminology.concepts_existing,
        },
        "run_ids": {
            dataset: str(run_id) for dataset, run_id in sorted(summary.run_ids.items())
        },
        "records_persisted": dict(sorted(summary.records_persisted.items())),
    }


def load_synthea_cohort_pair(
    connection: psycopg.Connection[Any],
    cohort_a_directory: Path,
    cohort_b_directory: Path,
    processed_root: Path,
    comparison_output_directory: Path,
    *,
    raw_root: Path,
    cohort_a_profile_name: str = DEFAULT_COHORT_A_PROFILE,
    cohort_b_profile_name: str = DEFAULT_COHORT_B_PROFILE,
    cohort_a_label: str = "cohort_a",
    cohort_b_label: str = "cohort_b",
    replace_comparison: bool = False,
) -> SyntheaCohortPairLoadSummary:
    """Compare and load two disjoint cohorts with separate processing lineage."""
    comparison = compare_synthea_cohorts(
        cohort_a_directory,
        cohort_b_directory,
        comparison_output_directory,
        cohort_a_profile_name=cohort_a_profile_name,
        cohort_b_profile_name=cohort_b_profile_name,
        cohort_a_label=cohort_a_label,
        cohort_b_label=cohort_b_label,
        replace=replace_comparison,
    )
    normalized_a_label = comparison.cohort_a.label
    normalized_b_label = comparison.cohort_b.label
    material_a = _cohort_material(
        normalized_a_label,
        cohort_a_profile_name,
        cohort_a_directory,
    )
    material_b = _cohort_material(
        normalized_b_label,
        cohort_b_profile_name,
        cohort_b_directory,
    )
    _assert_database_identifiers_are_disjoint(
        connection,
        (material_a, material_b),
    )

    cohort_a_load = load_adapted_synthea_dataset(
        connection,
        cohort_a_directory,
        processed_root / normalized_a_label,
        raw_root=raw_root,
        profile=material_a.profile,
    )
    cohort_b_load = load_adapted_synthea_dataset(
        connection,
        cohort_b_directory,
        processed_root / normalized_b_label,
        raw_root=raw_root,
        profile=material_b.profile,
    )

    load_identity: dict[str, object] = {
        "manifest_version": COHORT_LOAD_MANIFEST_VERSION,
        "comparison_fingerprint": comparison.comparison_fingerprint,
        "cohorts": {
            normalized_a_label: _load_summary_document(cohort_a_load),
            normalized_b_label: _load_summary_document(cohort_b_load),
        },
    }
    load_execution_fingerprint = _canonical_json_sha256(load_identity)
    load_manifest_path = comparison_output_directory / "synthea-cohort-load.json"
    _write_json(
        load_manifest_path,
        {
            **load_identity,
            "created_at": datetime.now(UTC).isoformat(),
            "load_execution_fingerprint": load_execution_fingerprint,
        },
    )
    return SyntheaCohortPairLoadSummary(
        comparison=comparison,
        cohort_a_load=cohort_a_load,
        cohort_b_load=cohort_b_load,
        load_manifest_path=load_manifest_path,
        load_execution_fingerprint=load_execution_fingerprint,
    )
