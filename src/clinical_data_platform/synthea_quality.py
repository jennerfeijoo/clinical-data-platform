"""Reproducible attrition and missingness evidence for paired Synthea cohorts."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

from clinical_data_platform.registry import dataset_names, get_dataset_definition
from clinical_data_platform.synthea import (
    SOURCE_HEADERS,
    inspect_synthea_csv_directory,
    verify_synthea_adaptation,
)
from clinical_data_platform.synthea_cohorts import (
    DEFAULT_COHORT_A_PROFILE,
    DEFAULT_COHORT_B_PROFILE,
    SyntheaCohortComparisonSummary,
    compare_synthea_cohorts,
    load_packaged_synthea_profile,
)

QUALITY_REPORT_SCHEMA_VERSION: Final = "1.0.0"

SOURCE_FILE_BY_DATASET: Final[dict[str, str]] = {
    "patients": "patients.csv",
    "encounters": "encounters.csv",
    "diagnoses": "conditions.csv",
    "observations": "observations.csv",
    "medications": "medications.csv",
    "procedures": "procedures.csv",
}

OMISSION_PREFIX_BY_DATASET: Final[dict[str, str]] = {
    "patients": "patient_",
    "encounters": "encounter_",
    "diagnoses": "condition_",
    "observations": "observation_",
    "medications": "medication_",
    "procedures": "procedure_",
}

STRUCTURAL_MISSING_FIELDS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("medications", "dose_value"),
        ("medications", "dose_unit"),
        ("medications", "route"),
    }
)


class SyntheaQualityReportError(RuntimeError):
    """Raised when quality evidence cannot be reconciled or published safely."""


@dataclass(frozen=True, slots=True)
class FieldMissingness:
    """Missing-value counts for one field at one processing stage."""

    field: str
    required: bool | None
    classification: str
    rows_total: int
    missing_count: int

    @property
    def present_count(self) -> int:
        return self.rows_total - self.missing_count

    @property
    def missing_rate(self) -> float | None:
        return _rate(self.missing_count, self.rows_total)


@dataclass(frozen=True, slots=True)
class DatasetQuality:
    """Attrition and missingness evidence for one clinical entity."""

    dataset: str
    source_file: str
    contract_path: str
    contract_version: str
    contract_sha256: str
    source_rows: int
    adapted_rows: int
    omission_reasons: dict[str, int]
    source_fields: tuple[FieldMissingness, ...]
    adapted_fields: tuple[FieldMissingness, ...]
    rows_complete_all_fields: int
    rows_with_any_missing: int
    rows_missing_required: int

    @property
    def omitted_rows(self) -> int:
        return sum(self.omission_reasons.values())

    @property
    def retention_rate(self) -> float | None:
        return _rate(self.adapted_rows, self.source_rows)

    @property
    def attrition_rate(self) -> float | None:
        return _rate(self.omitted_rows, self.source_rows)

    @property
    def adapted_missing_cells(self) -> int:
        return sum(field.missing_count for field in self.adapted_fields)

    @property
    def adapted_total_cells(self) -> int:
        return self.adapted_rows * len(self.adapted_fields)

    @property
    def adapted_missing_cell_rate(self) -> float | None:
        return _rate(self.adapted_missing_cells, self.adapted_total_cells)

    @property
    def required_missing_cells(self) -> int:
        return sum(
            field.missing_count for field in self.adapted_fields if field.required is True
        )

    @property
    def structural_missing_cells(self) -> int:
        return sum(
            field.missing_count
            for field in self.adapted_fields
            if field.classification == "structural"
        )


@dataclass(frozen=True, slots=True)
class CohortQuality:
    """Stable quality evidence for one verified adapted cohort."""

    label: str
    profile_name: str
    profile_sha256: str
    adaptation_fingerprint: str
    datasets: tuple[DatasetQuality, ...]

    @property
    def source_rows(self) -> int:
        return sum(dataset.source_rows for dataset in self.datasets)

    @property
    def adapted_rows(self) -> int:
        return sum(dataset.adapted_rows for dataset in self.datasets)

    @property
    def omitted_rows(self) -> int:
        return sum(dataset.omitted_rows for dataset in self.datasets)

    @property
    def overall_retention_rate(self) -> float | None:
        return _rate(self.adapted_rows, self.source_rows)

    @property
    def adapted_missing_cells(self) -> int:
        return sum(dataset.adapted_missing_cells for dataset in self.datasets)

    @property
    def adapted_total_cells(self) -> int:
        return sum(dataset.adapted_total_cells for dataset in self.datasets)

    @property
    def adapted_missing_cell_rate(self) -> float | None:
        return _rate(self.adapted_missing_cells, self.adapted_total_cells)


@dataclass(frozen=True, slots=True)
class SyntheaQualityReportSummary:
    """Paths and identities produced by one paired quality report."""

    comparison: SyntheaCohortComparisonSummary
    quality_fingerprint: str
    manifest_path: Path
    markdown_path: Path
    attrition_path: Path
    attrition_reasons_path: Path
    source_missingness_path: Path
    adapted_missingness_path: Path
    row_completeness_path: Path
    cohort_comparison_path: Path


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 8)


def _rate_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


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


def _read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"JSON manifest not found: {path}")
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, dict):
        raise SyntheaQualityReportError(f"JSON document must be an object: {path}")
    return {str(key): value for key, value in raw.items()}


def _read_csv_records(path: Path, expected_header: Sequence[str]) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Quality-report CSV not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        actual_header = tuple(reader.fieldnames or ())
        if actual_header != tuple(expected_header):
            raise SyntheaQualityReportError(
                f"Unexpected header for {path}: {actual_header}; "
                f"expected {tuple(expected_header)}."
            )
        records: list[dict[str, str]] = []
        for raw in reader:
            records.append(
                {
                    field: value if isinstance(value, str) else ""
                    for field, value in raw.items()
                    if isinstance(field, str)
                }
            )
    return records


def _field_missingness(
    rows: Sequence[Mapping[str, str]],
    fields: Sequence[str],
    *,
    required: Mapping[str, bool] | None = None,
    dataset: str | None = None,
) -> tuple[FieldMissingness, ...]:
    metrics: list[FieldMissingness] = []
    for field in fields:
        missing_count = sum(1 for row in rows if not row.get(field, "").strip())
        is_required = required.get(field) if required is not None else None
        if is_required is True:
            classification = "required"
        elif dataset is not None and (dataset, field) in STRUCTURAL_MISSING_FIELDS:
            classification = "structural"
        elif is_required is False:
            classification = "optional"
        else:
            classification = "source_field"
        metrics.append(
            FieldMissingness(
                field=field,
                required=is_required,
                classification=classification,
                rows_total=len(rows),
                missing_count=missing_count,
            )
        )
    return tuple(metrics)


def _row_completeness(
    rows: Sequence[Mapping[str, str]],
    fields: Sequence[str],
    required_fields: frozenset[str],
) -> tuple[int, int, int]:
    complete_all = 0
    missing_required = 0
    for row in rows:
        blank_fields = {field for field in fields if not row.get(field, "").strip()}
        if not blank_fields:
            complete_all += 1
        if blank_fields & required_fields:
            missing_required += 1
    return complete_all, len(rows) - complete_all, missing_required


def _source_directory(normalized_directory: Path) -> Path:
    manifest = _read_json_object(
        normalized_directory / "synthea-adaptation-manifest.json"
    )
    raw = manifest.get("source_directory")
    if not isinstance(raw, str) or not raw.strip():
        raise SyntheaQualityReportError(
            "Synthea adaptation manifest has no valid source_directory."
        )
    return Path(raw)


def _omission_reasons_by_dataset(
    omitted_rows: Mapping[str, int],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {
        dataset_name: {} for dataset_name in dataset_names()
    }
    for reason, count in omitted_rows.items():
        matches = [
            dataset_name
            for dataset_name, prefix in OMISSION_PREFIX_BY_DATASET.items()
            if reason.startswith(prefix)
        ]
        if len(matches) != 1:
            raise SyntheaQualityReportError(
                f"Omission reason {reason!r} cannot be assigned to exactly one dataset."
            )
        if count < 0:
            raise SyntheaQualityReportError(
                f"Omission reason {reason!r} has a negative count."
            )
        result[matches[0]][reason] = count
    return result


def _cohort_quality(
    label: str,
    profile_name: str,
    normalized_directory: Path,
) -> CohortQuality:
    profile = load_packaged_synthea_profile(profile_name)
    adaptation = verify_synthea_adaptation(normalized_directory, profile=profile)
    source_directory = _source_directory(normalized_directory)
    source_fingerprints = {
        item.name: item for item in inspect_synthea_csv_directory(source_directory)
    }
    reasons_by_dataset = _omission_reasons_by_dataset(adaptation.omitted_rows)
    quality_datasets: list[DatasetQuality] = []

    for dataset_name in dataset_names():
        definition = get_dataset_definition(dataset_name)
        contract = definition.contract
        source_file = SOURCE_FILE_BY_DATASET[dataset_name]
        source_header = SOURCE_HEADERS[source_file]
        source_rows = _read_csv_records(source_directory / source_file, source_header)
        adapted_rows = _read_csv_records(
            normalized_directory / f"{dataset_name}.csv",
            contract.column_names,
        )
        if source_fingerprints[source_file].row_count != len(source_rows):
            raise SyntheaQualityReportError(
                f"Source row count changed while reporting {source_file}."
            )
        if adaptation.dataset_rows[dataset_name] != len(adapted_rows):
            raise SyntheaQualityReportError(
                f"Adapted row count changed while reporting {dataset_name}."
            )

        omission_reasons = dict(sorted(reasons_by_dataset[dataset_name].items()))
        omitted_count = sum(omission_reasons.values())
        if len(adapted_rows) + omitted_count != len(source_rows):
            raise SyntheaQualityReportError(
                f"Attrition does not reconcile for {dataset_name}: "
                f"source={len(source_rows)}, adapted={len(adapted_rows)}, "
                f"omitted={omitted_count}."
            )

        required_map = {column.name: column.required for column in contract.columns}
        required_fields = frozenset(
            column.name for column in contract.columns if column.required
        )
        complete_all, with_missing, missing_required = _row_completeness(
            adapted_rows,
            contract.column_names,
            required_fields,
        )
        if missing_required:
            raise SyntheaQualityReportError(
                f"Verified adapted dataset {dataset_name} contains "
                f"{missing_required} rows with missing required fields."
            )

        quality_datasets.append(
            DatasetQuality(
                dataset=dataset_name,
                source_file=source_file,
                contract_path=contract.resource_path,
                contract_version=contract.version,
                contract_sha256=contract.sha256,
                source_rows=len(source_rows),
                adapted_rows=len(adapted_rows),
                omission_reasons=omission_reasons,
                source_fields=_field_missingness(source_rows, source_header),
                adapted_fields=_field_missingness(
                    adapted_rows,
                    contract.column_names,
                    required=required_map,
                    dataset=dataset_name,
                ),
                rows_complete_all_fields=complete_all,
                rows_with_any_missing=with_missing,
                rows_missing_required=missing_required,
            )
        )

    return CohortQuality(
        label=label,
        profile_name=profile.name,
        profile_sha256=profile.sha256,
        adaptation_fingerprint=adaptation.adaptation_fingerprint,
        datasets=tuple(quality_datasets),
    )


def _field_document(field: FieldMissingness) -> dict[str, object]:
    return {
        "field": field.field,
        "required": field.required,
        "classification": field.classification,
        "rows_total": field.rows_total,
        "present_count": field.present_count,
        "missing_count": field.missing_count,
        "missing_rate": field.missing_rate,
    }


def _dataset_document(dataset: DatasetQuality) -> dict[str, object]:
    return {
        "dataset": dataset.dataset,
        "source_file": dataset.source_file,
        "contract": {
            "path": dataset.contract_path,
            "version": dataset.contract_version,
            "sha256": dataset.contract_sha256,
        },
        "attrition": {
            "source_rows": dataset.source_rows,
            "adapted_rows": dataset.adapted_rows,
            "omitted_rows": dataset.omitted_rows,
            "retention_rate": dataset.retention_rate,
            "attrition_rate": dataset.attrition_rate,
            "reasons": dict(sorted(dataset.omission_reasons.items())),
        },
        "source_missingness": [
            _field_document(field) for field in dataset.source_fields
        ],
        "adapted_missingness": [
            _field_document(field) for field in dataset.adapted_fields
        ],
        "row_completeness": {
            "rows_total": dataset.adapted_rows,
            "rows_complete_all_fields": dataset.rows_complete_all_fields,
            "rows_with_any_missing": dataset.rows_with_any_missing,
            "rows_missing_required": dataset.rows_missing_required,
            "complete_all_rate": _rate(
                dataset.rows_complete_all_fields,
                dataset.adapted_rows,
            ),
            "any_missing_rate": _rate(
                dataset.rows_with_any_missing,
                dataset.adapted_rows,
            ),
            "missing_required_rate": _rate(
                dataset.rows_missing_required,
                dataset.adapted_rows,
            ),
            "adapted_total_cells": dataset.adapted_total_cells,
            "adapted_missing_cells": dataset.adapted_missing_cells,
            "adapted_missing_cell_rate": dataset.adapted_missing_cell_rate,
            "required_missing_cells": dataset.required_missing_cells,
            "structural_missing_cells": dataset.structural_missing_cells,
        },
    }


def _cohort_document(cohort: CohortQuality) -> dict[str, object]:
    return {
        "label": cohort.label,
        "profile_name": cohort.profile_name,
        "profile_sha256": cohort.profile_sha256,
        "adaptation_fingerprint": cohort.adaptation_fingerprint,
        "summary": {
            "source_rows": cohort.source_rows,
            "adapted_rows": cohort.adapted_rows,
            "omitted_rows": cohort.omitted_rows,
            "overall_retention_rate": cohort.overall_retention_rate,
            "adapted_total_cells": cohort.adapted_total_cells,
            "adapted_missing_cells": cohort.adapted_missing_cells,
            "adapted_missing_cell_rate": cohort.adapted_missing_cell_rate,
        },
        "datasets": [_dataset_document(dataset) for dataset in cohort.datasets],
    }


def _dataset_by_name(cohort: CohortQuality, dataset_name: str) -> DatasetQuality:
    for quality_dataset in cohort.datasets:
        if quality_dataset.dataset == dataset_name:
            return quality_dataset
    raise SyntheaQualityReportError(
        f"Cohort {cohort.label!r} has no quality evidence for {dataset_name!r}."
    )


def _comparison_document(
    cohort_a: CohortQuality,
    cohort_b: CohortQuality,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dataset_name in dataset_names():
        left = _dataset_by_name(cohort_a, dataset_name)
        right = _dataset_by_name(cohort_b, dataset_name)
        retention_difference = (
            None
            if left.retention_rate is None or right.retention_rate is None
            else round(right.retention_rate - left.retention_rate, 8)
        )
        missing_difference = (
            None
            if left.adapted_missing_cell_rate is None
            or right.adapted_missing_cell_rate is None
            else round(
                right.adapted_missing_cell_rate - left.adapted_missing_cell_rate,
                8,
            )
        )
        rows.append(
            {
                "dataset": dataset_name,
                "cohort_a_source_rows": left.source_rows,
                "cohort_b_source_rows": right.source_rows,
                "cohort_a_adapted_rows": left.adapted_rows,
                "cohort_b_adapted_rows": right.adapted_rows,
                "cohort_a_retention_rate": left.retention_rate,
                "cohort_b_retention_rate": right.retention_rate,
                "retention_rate_difference_b_minus_a": retention_difference,
                "cohort_a_adapted_missing_cell_rate": left.adapted_missing_cell_rate,
                "cohort_b_adapted_missing_cell_rate": right.adapted_missing_cell_rate,
                "missing_cell_rate_difference_b_minus_a": missing_difference,
            }
        )
    return rows


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(document, file, indent=2, sort_keys=True, ensure_ascii=False)
        file.write("\n")


def _write_csv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: "" if row.get(key) is None else row.get(key)
                    for key in fieldnames
                }
            )


def _attrition_rows(cohorts: Sequence[CohortQuality]) -> list[dict[str, object]]:
    return [
        {
            "cohort": cohort.label,
            "dataset": dataset.dataset,
            "source_file": dataset.source_file,
            "source_rows": dataset.source_rows,
            "adapted_rows": dataset.adapted_rows,
            "omitted_rows": dataset.omitted_rows,
            "retention_rate": dataset.retention_rate,
            "attrition_rate": dataset.attrition_rate,
        }
        for cohort in cohorts
        for dataset in cohort.datasets
    ]


def _attrition_reason_rows(
    cohorts: Sequence[CohortQuality],
) -> list[dict[str, object]]:
    return [
        {
            "cohort": cohort.label,
            "dataset": dataset.dataset,
            "reason": reason,
            "count": count,
            "share_of_source": _rate(count, dataset.source_rows),
            "share_of_omitted": _rate(count, dataset.omitted_rows),
        }
        for cohort in cohorts
        for dataset in cohort.datasets
        for reason, count in dataset.omission_reasons.items()
    ]


def _source_missingness_rows(
    cohorts: Sequence[CohortQuality],
) -> list[dict[str, object]]:
    return [
        {
            "cohort": cohort.label,
            "dataset": dataset.dataset,
            "source_file": dataset.source_file,
            "field": field.field,
            "rows_total": field.rows_total,
            "present_count": field.present_count,
            "missing_count": field.missing_count,
            "missing_rate": field.missing_rate,
        }
        for cohort in cohorts
        for dataset in cohort.datasets
        for field in dataset.source_fields
    ]


def _adapted_missingness_rows(
    cohorts: Sequence[CohortQuality],
) -> list[dict[str, object]]:
    return [
        {
            "cohort": cohort.label,
            "dataset": dataset.dataset,
            "contract_version": dataset.contract_version,
            "field": field.field,
            "required": field.required,
            "classification": field.classification,
            "rows_total": field.rows_total,
            "present_count": field.present_count,
            "missing_count": field.missing_count,
            "missing_rate": field.missing_rate,
        }
        for cohort in cohorts
        for dataset in cohort.datasets
        for field in dataset.adapted_fields
    ]


def _row_completeness_rows(
    cohorts: Sequence[CohortQuality],
) -> list[dict[str, object]]:
    return [
        {
            "cohort": cohort.label,
            "dataset": dataset.dataset,
            "rows_total": dataset.adapted_rows,
            "rows_complete_all_fields": dataset.rows_complete_all_fields,
            "rows_with_any_missing": dataset.rows_with_any_missing,
            "rows_missing_required": dataset.rows_missing_required,
            "complete_all_rate": _rate(
                dataset.rows_complete_all_fields,
                dataset.adapted_rows,
            ),
            "any_missing_rate": _rate(
                dataset.rows_with_any_missing,
                dataset.adapted_rows,
            ),
            "missing_required_rate": _rate(
                dataset.rows_missing_required,
                dataset.adapted_rows,
            ),
            "adapted_total_cells": dataset.adapted_total_cells,
            "adapted_missing_cells": dataset.adapted_missing_cells,
            "adapted_missing_cell_rate": dataset.adapted_missing_cell_rate,
            "required_missing_cells": dataset.required_missing_cells,
            "structural_missing_cells": dataset.structural_missing_cells,
        }
        for cohort in cohorts
        for dataset in cohort.datasets
    ]


def _write_markdown(
    path: Path,
    cohort_a: CohortQuality,
    cohort_b: CohortQuality,
    comparison_fingerprint: str,
    quality_fingerprint: str,
) -> None:
    lines = [
        "# Synthea attrition and missingness report",
        "",
        (
            "This report measures technical row attrition during adaptation and "
            "blank-value missingness in source and contract-ready CSV artifacts."
        ),
        (
            "It does not measure participant dropout, clinical follow-up loss, "
            "or epidemiological validity."
        ),
        "",
        "## Reproducible identity",
        "",
        f"- Cohort comparison: `sha256:{comparison_fingerprint}`",
        f"- Quality report: `sha256:{quality_fingerprint}`",
        "",
        "## Cohort overview",
        "",
        (
            "| Cohort | Source rows | Adapted rows | Omitted rows | Retention | "
            "Adapted missing cells |"
        ),
        "|---|---:|---:|---:|---:|---:|",
    ]
    for cohort in (cohort_a, cohort_b):
        lines.append(
            f"| `{cohort.label}` | {cohort.source_rows} | {cohort.adapted_rows} | "
            f"{cohort.omitted_rows} | {_rate_text(cohort.overall_retention_rate)} | "
            f"{cohort.adapted_missing_cells} / {cohort.adapted_total_cells} |"
        )

    lines.extend(
        [
            "",
            "## Attrition by entity",
            "",
            (
                "| Dataset | A source | A adapted | A retention | B source | "
                "B adapted | B retention |"
            ),
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for dataset_name in dataset_names():
        left = _dataset_by_name(cohort_a, dataset_name)
        right = _dataset_by_name(cohort_b, dataset_name)
        lines.append(
            f"| {dataset_name} | {left.source_rows} | {left.adapted_rows} | "
            f"{_rate_text(left.retention_rate)} | {right.source_rows} | "
            f"{right.adapted_rows} | {_rate_text(right.retention_rate)} |"
        )

    missing_fields: list[tuple[str, str, FieldMissingness]] = []
    for cohort in (cohort_a, cohort_b):
        for quality_dataset in cohort.datasets:
            for field in quality_dataset.adapted_fields:
                if field.missing_count:
                    missing_fields.append(
                        (cohort.label, quality_dataset.dataset, field)
                    )
    lines.extend(
        [
            "",
            "## Non-zero adapted missingness",
            "",
            "| Cohort | Dataset | Field | Classification | Missing | Rate |",
            "|---|---|---|---|---:|---:|",
        ]
    )
    if missing_fields:
        for label, dataset_name, field in missing_fields:
            lines.append(
                f"| `{label}` | {dataset_name} | `{field.field}` | "
                f"{field.classification} | {field.missing_count} / "
                f"{field.rows_total} | {_rate_text(field.missing_rate)} |"
            )
    else:
        lines.append("| — | — | — | — | 0 | 0.00% |")

    lines.extend(
        [
            "",
            "## Interpretation rules",
            "",
            (
                "- `required`: a blank value violates the active contract; "
                "verified reports require zero."
            ),
            (
                "- `optional`: absence is permitted and may represent a valid "
                "clinical state."
            ),
            (
                "- `structural`: the adapter lacks a reliable structured source "
                "value for the field."
            ),
            (
                "- Source missingness is descriptive and does not assign internal "
                "contract requirements upstream."
            ),
            (
                "- Rates compare synthetic artifacts descriptively; no hypothesis "
                "test or clinical inference is performed."
            ),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _validate_report_paths(
    cohort_a_directory: Path,
    cohort_b_directory: Path,
    output_directory: Path,
) -> tuple[Path, Path, Path]:
    cohort_a = _resolved(cohort_a_directory)
    cohort_b = _resolved(cohort_b_directory)
    output = _resolved(output_directory)
    for label, cohort in (("cohort A", cohort_a), ("cohort B", cohort_b)):
        if _paths_overlap(output, cohort):
            raise SyntheaQualityReportError(
                f"Quality-report output overlaps {label} input tree: {output} and {cohort}."
            )
    return cohort_a, cohort_b, output


def _output_is_nonempty(output_directory: Path) -> bool:
    return output_directory.exists() and any(output_directory.iterdir())


def _publish_staging_directory(
    staging_directory: Path,
    output_directory: Path,
    *,
    replace: bool,
) -> None:
    backup_directory: Path | None = None
    if output_directory.exists():
        if _output_is_nonempty(output_directory) and not replace:
            raise SyntheaQualityReportError(
                f"Quality-report output is not empty: {output_directory}; "
                "use replace=True."
            )
        backup_directory = output_directory.parent / (
            f".{output_directory.name}.backup-{uuid4().hex}"
        )
        os.replace(output_directory, backup_directory)

    try:
        os.replace(staging_directory, output_directory)
    except Exception:
        if backup_directory is not None and backup_directory.exists():
            if output_directory.exists():
                shutil.rmtree(output_directory, ignore_errors=True)
            os.replace(backup_directory, output_directory)
        raise
    else:
        if backup_directory is not None:
            shutil.rmtree(backup_directory, ignore_errors=True)


def _final_comparison(
    comparison: SyntheaCohortComparisonSummary,
    output_directory: Path,
) -> SyntheaCohortComparisonSummary:
    comparison_directory = output_directory / "cohort-comparison"
    return SyntheaCohortComparisonSummary(
        cohort_a=comparison.cohort_a,
        cohort_b=comparison.cohort_b,
        comparison_fingerprint=comparison.comparison_fingerprint,
        overlap_counts=dict(comparison.overlap_counts),
        manifest_path=comparison_directory / "synthea-cohort-comparison.json",
        markdown_path=comparison_directory / "synthea-cohort-comparison.md",
    )


def _write_report_artifacts(
    output_directory: Path,
    comparison: SyntheaCohortComparisonSummary,
    cohort_a: CohortQuality,
    cohort_b: CohortQuality,
) -> str:
    descriptive_comparison = _comparison_document(cohort_a, cohort_b)
    stable_document: dict[str, object] = {
        "schema_version": QUALITY_REPORT_SCHEMA_VERSION,
        "comparison_fingerprint": comparison.comparison_fingerprint,
        "cohorts": [_cohort_document(cohort_a), _cohort_document(cohort_b)],
        "descriptive_comparison": descriptive_comparison,
    }
    quality_fingerprint = _canonical_json_sha256(stable_document)

    manifest_path = output_directory / "synthea-quality-report.json"
    markdown_path = output_directory / "synthea-quality-report.md"
    attrition_path = output_directory / "attrition.csv"
    attrition_reasons_path = output_directory / "attrition-reasons.csv"
    source_missingness_path = output_directory / "source-missingness.csv"
    adapted_missingness_path = output_directory / "adapted-missingness.csv"
    row_completeness_path = output_directory / "row-completeness.csv"
    cohort_comparison_path = output_directory / "cohort-quality-comparison.csv"

    _write_json(
        manifest_path,
        {
            **stable_document,
            "created_at": datetime.now(UTC).isoformat(),
            "quality_fingerprint": quality_fingerprint,
            "artifacts": {
                "markdown": markdown_path.name,
                "attrition": attrition_path.name,
                "attrition_reasons": attrition_reasons_path.name,
                "source_missingness": source_missingness_path.name,
                "adapted_missingness": adapted_missingness_path.name,
                "row_completeness": row_completeness_path.name,
                "cohort_comparison": cohort_comparison_path.name,
                "cohort_comparison_directory": "cohort-comparison",
            },
        },
    )

    cohorts = (cohort_a, cohort_b)
    _write_csv(
        attrition_path,
        (
            "cohort",
            "dataset",
            "source_file",
            "source_rows",
            "adapted_rows",
            "omitted_rows",
            "retention_rate",
            "attrition_rate",
        ),
        _attrition_rows(cohorts),
    )
    _write_csv(
        attrition_reasons_path,
        (
            "cohort",
            "dataset",
            "reason",
            "count",
            "share_of_source",
            "share_of_omitted",
        ),
        _attrition_reason_rows(cohorts),
    )
    _write_csv(
        source_missingness_path,
        (
            "cohort",
            "dataset",
            "source_file",
            "field",
            "rows_total",
            "present_count",
            "missing_count",
            "missing_rate",
        ),
        _source_missingness_rows(cohorts),
    )
    _write_csv(
        adapted_missingness_path,
        (
            "cohort",
            "dataset",
            "contract_version",
            "field",
            "required",
            "classification",
            "rows_total",
            "present_count",
            "missing_count",
            "missing_rate",
        ),
        _adapted_missingness_rows(cohorts),
    )
    _write_csv(
        row_completeness_path,
        (
            "cohort",
            "dataset",
            "rows_total",
            "rows_complete_all_fields",
            "rows_with_any_missing",
            "rows_missing_required",
            "complete_all_rate",
            "any_missing_rate",
            "missing_required_rate",
            "adapted_total_cells",
            "adapted_missing_cells",
            "adapted_missing_cell_rate",
            "required_missing_cells",
            "structural_missing_cells",
        ),
        _row_completeness_rows(cohorts),
    )
    _write_csv(
        cohort_comparison_path,
        (
            "dataset",
            "cohort_a_source_rows",
            "cohort_b_source_rows",
            "cohort_a_adapted_rows",
            "cohort_b_adapted_rows",
            "cohort_a_retention_rate",
            "cohort_b_retention_rate",
            "retention_rate_difference_b_minus_a",
            "cohort_a_adapted_missing_cell_rate",
            "cohort_b_adapted_missing_cell_rate",
            "missing_cell_rate_difference_b_minus_a",
        ),
        descriptive_comparison,
    )
    _write_markdown(
        markdown_path,
        cohort_a,
        cohort_b,
        comparison.comparison_fingerprint,
        quality_fingerprint,
    )
    return quality_fingerprint


def generate_synthea_quality_report(
    cohort_a_directory: Path,
    cohort_b_directory: Path,
    output_directory: Path,
    *,
    cohort_a_profile_name: str = DEFAULT_COHORT_A_PROFILE,
    cohort_b_profile_name: str = DEFAULT_COHORT_B_PROFILE,
    cohort_a_label: str = "cohort_a",
    cohort_b_label: str = "cohort_b",
    replace: bool = False,
) -> SyntheaQualityReportSummary:
    """Generate and safely publish paired attrition and missingness evidence."""
    cohort_a_path, cohort_b_path, output_path = _validate_report_paths(
        cohort_a_directory,
        cohort_b_directory,
        output_directory,
    )
    if _output_is_nonempty(output_path) and not replace:
        raise SyntheaQualityReportError(
            f"Quality-report output is not empty: {output_path}; use replace=True."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = Path(
        tempfile.mkdtemp(
            prefix=f".{output_path.name}.staging-",
            dir=output_path.parent,
        )
    )
    try:
        staged_comparison = compare_synthea_cohorts(
            cohort_a_path,
            cohort_b_path,
            staging_path / "cohort-comparison",
            cohort_a_profile_name=cohort_a_profile_name,
            cohort_b_profile_name=cohort_b_profile_name,
            cohort_a_label=cohort_a_label,
            cohort_b_label=cohort_b_label,
        )
        cohort_a_quality = _cohort_quality(
            staged_comparison.cohort_a.label,
            cohort_a_profile_name,
            cohort_a_path,
        )
        cohort_b_quality = _cohort_quality(
            staged_comparison.cohort_b.label,
            cohort_b_profile_name,
            cohort_b_path,
        )
        quality_fingerprint = _write_report_artifacts(
            staging_path,
            staged_comparison,
            cohort_a_quality,
            cohort_b_quality,
        )
        _publish_staging_directory(staging_path, output_path, replace=replace)
    except Exception:
        shutil.rmtree(staging_path, ignore_errors=True)
        raise

    final_comparison = _final_comparison(staged_comparison, output_path)
    return SyntheaQualityReportSummary(
        comparison=final_comparison,
        quality_fingerprint=quality_fingerprint,
        manifest_path=output_path / "synthea-quality-report.json",
        markdown_path=output_path / "synthea-quality-report.md",
        attrition_path=output_path / "attrition.csv",
        attrition_reasons_path=output_path / "attrition-reasons.csv",
        source_missingness_path=output_path / "source-missingness.csv",
        adapted_missingness_path=output_path / "adapted-missingness.csv",
        row_completeness_path=output_path / "row-completeness.csv",
        cohort_comparison_path=output_path / "cohort-quality-comparison.csv",
    )
