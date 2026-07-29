import csv
import json
import os
from pathlib import Path

import pytest

from clinical_data_platform import synthea_quality
from clinical_data_platform.cohort_cli import build_parser
from clinical_data_platform.synthea import SyntheaManifestError, adapt_synthea_csv
from clinical_data_platform.synthea_cohorts import (
    DEFAULT_COHORT_A_PROFILE,
    DEFAULT_COHORT_B_PROFILE,
    load_packaged_synthea_profile,
)
from clinical_data_platform.synthea_quality import (
    SyntheaQualityReportError,
    generate_synthea_quality_report,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_A = REPOSITORY_ROOT / "tests" / "fixtures" / "synthea" / "csv"
FIXTURE_B = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "synthea" / "cohort_b" / "csv"
)


def _adapt_pair(tmp_path: Path) -> tuple[Path, Path]:
    cohort_a = tmp_path / "cohort_a"
    cohort_b = tmp_path / "cohort_b"
    adapt_synthea_csv(
        FIXTURE_A,
        cohort_a,
        profile=load_packaged_synthea_profile(DEFAULT_COHORT_A_PROFILE),
    )
    adapt_synthea_csv(
        FIXTURE_B,
        cohort_b,
        profile=load_packaged_synthea_profile(DEFAULT_COHORT_B_PROFILE),
    )
    return cohort_a, cohort_b


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def test_quality_report_is_deterministic_and_reconciles_attrition(
    tmp_path: Path,
) -> None:
    cohort_a, cohort_b = _adapt_pair(tmp_path)

    first = generate_synthea_quality_report(
        cohort_a,
        cohort_b,
        tmp_path / "quality_1",
    )
    second = generate_synthea_quality_report(
        cohort_a,
        cohort_b,
        tmp_path / "quality_2",
    )

    assert first.quality_fingerprint == second.quality_fingerprint
    assert first.comparison.comparison_fingerprint == (
        second.comparison.comparison_fingerprint
    )
    assert len(first.quality_fingerprint) == 64
    assert first.manifest_path.parent == (tmp_path / "quality_1").resolve()
    assert ".staging-" not in str(first.comparison.manifest_path)

    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["quality_fingerprint"] == first.quality_fingerprint
    assert manifest["comparison_fingerprint"] == (
        first.comparison.comparison_fingerprint
    )

    attrition = _csv_rows(first.attrition_path)
    observations = [
        row
        for row in attrition
        if row["cohort"] == "cohort_a" and row["dataset"] == "observations"
    ]
    assert observations == [
        {
            "cohort": "cohort_a",
            "dataset": "observations",
            "source_file": "observations.csv",
            "source_rows": "4",
            "adapted_rows": "3",
            "omitted_rows": "1",
            "retention_rate": "0.75",
            "attrition_rate": "0.25",
        }
    ]
    reasons = _csv_rows(first.attrition_reasons_path)
    assert {
        "cohort": "cohort_a",
        "dataset": "observations",
        "reason": "observation_outside_supported_subset",
        "count": "1",
        "share_of_source": "0.25",
        "share_of_omitted": "1.0",
    } in reasons


def test_quality_report_classifies_optional_and_structural_missingness(
    tmp_path: Path,
) -> None:
    cohort_a, cohort_b = _adapt_pair(tmp_path)
    report = generate_synthea_quality_report(
        cohort_a,
        cohort_b,
        tmp_path / "quality",
    )

    missingness = _csv_rows(report.adapted_missingness_path)
    by_key = {
        (row["cohort"], row["dataset"], row["field"]): row
        for row in missingness
    }

    death_date = by_key[("cohort_a", "patients", "death_date")]
    assert death_date["required"] == "False"
    assert death_date["classification"] == "optional"
    assert death_date["missing_count"] == "2"
    assert death_date["missing_rate"] == "1.0"

    dose_value = by_key[("cohort_a", "medications", "dose_value")]
    assert dose_value["classification"] == "structural"
    assert dose_value["missing_count"] == "2"
    assert dose_value["missing_rate"] == "1.0"

    required_missing = [
        row
        for row in missingness
        if row["required"] == "True" and row["missing_count"] != "0"
    ]
    assert required_missing == []

    completeness = _csv_rows(report.row_completeness_path)
    medication_row = next(
        row
        for row in completeness
        if row["cohort"] == "cohort_a" and row["dataset"] == "medications"
    )
    assert medication_row["rows_missing_required"] == "0"
    assert medication_row["structural_missing_cells"] == "6"


def test_quality_report_refuses_tampered_adapted_artifacts(tmp_path: Path) -> None:
    cohort_a, cohort_b = _adapt_pair(tmp_path)
    patients_path = cohort_a / "patients.csv"
    patients_path.write_text(
        patients_path.read_text(encoding="utf-8").replace("P001", "P999", 1),
        encoding="utf-8",
    )

    with pytest.raises(SyntheaManifestError, match="hash mismatch"):
        generate_synthea_quality_report(
            cohort_a,
            cohort_b,
            tmp_path / "quality",
        )


def test_quality_report_output_requires_explicit_replacement(tmp_path: Path) -> None:
    cohort_a, cohort_b = _adapt_pair(tmp_path)
    output = tmp_path / "quality"
    generate_synthea_quality_report(cohort_a, cohort_b, output)

    with pytest.raises(SyntheaQualityReportError, match="not empty"):
        generate_synthea_quality_report(cohort_a, cohort_b, output)

    replaced = generate_synthea_quality_report(
        cohort_a,
        cohort_b,
        output,
        replace=True,
    )
    assert replaced.manifest_path.exists()
    assert not list(tmp_path.glob(".quality.staging-*"))
    assert not list(tmp_path.glob(".quality.backup-*"))


@pytest.mark.parametrize("output_kind", ["cohort", "ancestor", "descendant"])
def test_quality_report_rejects_output_overlap_without_deleting_inputs(
    tmp_path: Path,
    output_kind: str,
) -> None:
    cohort_a, cohort_b = _adapt_pair(tmp_path)
    sentinel = cohort_a / "patients.csv"
    original = sentinel.read_bytes()
    if output_kind == "cohort":
        output = cohort_a
    elif output_kind == "ancestor":
        output = tmp_path
    else:
        output = cohort_a / "quality"

    with pytest.raises(SyntheaQualityReportError, match="overlaps"):
        generate_synthea_quality_report(
            cohort_a,
            cohort_b,
            output,
            replace=True,
        )

    assert sentinel.exists()
    assert sentinel.read_bytes() == original
    assert cohort_b.exists()


def test_invalid_replacement_preserves_previous_report(tmp_path: Path) -> None:
    cohort_a, cohort_b = _adapt_pair(tmp_path)
    output = tmp_path / "quality"
    first = generate_synthea_quality_report(cohort_a, cohort_b, output)
    original_manifest = first.manifest_path.read_bytes()

    patients_path = cohort_a / "patients.csv"
    patients_path.write_text(
        patients_path.read_text(encoding="utf-8").replace("P001", "P999", 1),
        encoding="utf-8",
    )
    with pytest.raises(SyntheaManifestError, match="hash mismatch"):
        generate_synthea_quality_report(
            cohort_a,
            cohort_b,
            output,
            replace=True,
        )

    assert (output / "synthea-quality-report.json").read_bytes() == original_manifest
    assert not list(tmp_path.glob(".quality.staging-*"))
    assert not list(tmp_path.glob(".quality.backup-*"))


def test_publication_failure_restores_previous_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cohort_a, cohort_b = _adapt_pair(tmp_path)
    output = tmp_path / "quality"
    first = generate_synthea_quality_report(cohort_a, cohort_b, output)
    original_manifest = first.manifest_path.read_bytes()
    real_replace = os.replace
    call_count = 0

    def fail_second_replace(source: os.PathLike[str], target: os.PathLike[str]) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("simulated publication failure")
        real_replace(source, target)

    monkeypatch.setattr(synthea_quality.os, "replace", fail_second_replace)
    with pytest.raises(OSError, match="simulated publication failure"):
        generate_synthea_quality_report(
            cohort_a,
            cohort_b,
            output,
            replace=True,
        )

    assert (output / "synthea-quality-report.json").read_bytes() == original_manifest
    assert not list(tmp_path.glob(".quality.staging-*"))
    assert not list(tmp_path.glob(".quality.backup-*"))


def test_cohort_cli_exposes_quality_report_command() -> None:
    args = build_parser().parse_args(
        [
            "quality-report",
            "cohort-a",
            "cohort-b",
            "--output-dir",
            "quality-output",
            "--replace",
        ]
    )

    assert args.command == "quality-report"
    assert args.output_dir == Path("quality-output")
    assert args.replace is True
