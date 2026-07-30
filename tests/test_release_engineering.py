from __future__ import annotations

import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import pytest

from clinical_data_platform.cohort import load_hypertension_cohort_sql

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_gate_passes_for_current_version() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_release.py",
            "--expected-version",
            "0.21.0",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary["version"] == "0.21.0"
    assert summary["expected_tag"] == "v0.21.0"
    assert summary["packaged_cohort_sql_matches_repository"] is True


def test_packaged_hypertension_definition_matches_repository_copy() -> None:
    sql, source = load_hypertension_cohort_sql()

    assert source == (
        "clinical_data_platform.cohort_definitions:hypertension.sql"
    )
    assert sql == (ROOT / "sql" / "cohorts" / "hypertension.sql").read_text(
        encoding="utf-8"
    )
    assert "INSERT INTO analytics.hypertension_features" in sql


def test_missing_default_repository_sql_path_falls_back_to_package(
    tmp_path: Path,
) -> None:
    default_path = tmp_path / "sql" / "cohorts" / "hypertension.sql"

    sql, source = load_hypertension_cohort_sql(default_path)

    assert "hypertension_features" in sql
    assert source.startswith("clinical_data_platform.cohort_definitions:")


def test_missing_explicit_sql_override_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Cohort SQL file not found"):
        load_hypertension_cohort_sql(tmp_path / "custom-definition.sql")


def test_wheel_runtime_markers_are_available_from_source_tree() -> None:
    package_root = files("clinical_data_platform")

    assert package_root.joinpath("py.typed").is_file()
    assert package_root.joinpath(
        "cohort_definitions", "hypertension.sql"
    ).is_file()
