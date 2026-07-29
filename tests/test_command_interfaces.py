from __future__ import annotations

import json
from contextlib import AbstractContextManager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from clinical_data_platform import benchmark_cli, cli, cohort_cli, demo, entrypoint
from clinical_data_platform.synthea_cohorts import (
    DEFAULT_COHORT_A_PROFILE,
    DEFAULT_COHORT_B_PROFILE,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SYNTHEA_FIXTURE_A = REPOSITORY_ROOT / "tests" / "fixtures" / "synthea" / "csv"
SYNTHEA_FIXTURE_B = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "synthea" / "cohort_b" / "csv"
)


class _ConnectionContext(AbstractContextManager[object]):
    def __init__(self) -> None:
        self.connection = object()

    def __enter__(self) -> object:
        return self.connection

    def __exit__(self, *args: object) -> None:
        return None


def _patch_connection(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    monkeypatch.setattr(module, "connect_database", lambda _url: _ConnectionContext())


def test_cli_contract_raw_and_validation_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["list-contracts"]) == 0
    assert "patients: version=" in capsys.readouterr().out

    assert cli.main(["show-contract", "observations"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["name"] == "observations"
    assert document["measurement_profiles"]

    assert cli.main(["show-contract", "patients"]) == 0
    patient_document = json.loads(capsys.readouterr().out)
    assert patient_document["measurement_profiles"] == []

    assert cli.main(["validate-contracts"]) == 0
    assert "Validated 6 active contracts." in capsys.readouterr().out

    raw_root = tmp_path / "raw"
    source = REPOSITORY_ROOT / "data" / "sample" / "patients.csv"
    assert cli.main(["raw-capture", "patients", str(source), "--raw-root", str(raw_root)]) == 0
    capture_output = capsys.readouterr().out
    assert "Raw capture completed:" in capture_output

    manifests = tuple((raw_root / "receipts" / "patients").rglob("*.json"))
    assert len(manifests) == 1
    relative_manifest = manifests[0].relative_to(raw_root)
    assert cli.main(
        ["raw-verify", str(relative_manifest), "--raw-root", str(raw_root)]
    ) == 0
    assert "Raw receipt verified:" in capsys.readouterr().out

    processed = tmp_path / "processed"
    assert cli.main(
        [
            "validate-dataset",
            "patients",
            str(source),
            "--output-dir",
            str(processed),
            "--raw-root",
            str(raw_root),
            "--reference-date",
            "2026-07-29",
        ]
    ) == 0
    validation_output = capsys.readouterr().out
    assert "patients validation completed:" in validation_output
    assert (processed / "quality_report.json").exists()


def test_cli_rejects_invalid_iso_date() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["validate-dataset", "patients", "patients.csv", "--reference-date", "29-07-2026"]
        )


def test_cli_database_commands(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_connection(monkeypatch, cli)
    migration_summary = SimpleNamespace(
        previous_version=0,
        current_version=8,
        target_version=8,
        baselined_versions=(1,),
        applied_versions=(2, 3, 4, 5, 6, 7, 8),
    )
    monkeypatch.setattr(cli, "migrate_database", lambda *_args, **_kwargs: migration_summary)

    assert cli.main(
        [
            "database-migrate",
            "--database-url",
            "postgresql://example",
            "--target-version",
            "8",
            "--baseline-existing",
        ]
    ) == 0
    assert "current=8" in capsys.readouterr().out

    status = SimpleNamespace(
        managed=True,
        detected_schema_version=8,
        current_version=8,
        latest_version=8,
        pending=(),
        applied=(
            SimpleNamespace(
                version=8,
                name="execution lifecycle",
                execution_type="versioned",
                checksum="abc123",
            ),
        ),
    )
    monkeypatch.setattr(cli, "migration_status", lambda _connection: status)
    assert cli.main(["database-status", "--database-url", "postgresql://example"]) == 0
    status_output = capsys.readouterr().out
    assert "managed=True" in status_output
    assert "V008 execution lifecycle" in status_output

    monkeypatch.setattr(cli, "validate_database_migrations", lambda _connection: status)
    assert cli.main(["database-validate", "--database-url", "postgresql://example"]) == 0
    assert "valid at V008" in capsys.readouterr().out


def test_cli_persistence_cohort_load_and_demo_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_connection(monkeypatch, cli)
    monkeypatch.setattr(
        cli,
        "migrate_database",
        lambda *_args, **_kwargs: SimpleNamespace(current_version=8),
    )

    persistence_summary = SimpleNamespace(
        dataset="patients",
        run_id=uuid4(),
        contract_version="1.0.0",
        already_loaded=False,
        records_upserted=2,
        validation_errors_inserted=0,
    )
    monkeypatch.setattr(
        cli,
        "persist_dataset_validation_outputs",
        lambda *_args, **_kwargs: persistence_summary,
    )
    assert cli.main(
        [
            "load-dataset",
            "patients",
            "--output-dir",
            str(tmp_path / "processed"),
            "--raw-root",
            str(tmp_path / "raw"),
            "--database-url",
            "postgresql://example",
        ]
    ) == 0
    assert "records=2" in capsys.readouterr().out

    cohort_summary = SimpleNamespace(
        cohort_run_id=uuid4(),
        row_count=3,
        features_path=tmp_path / "features.csv",
    )
    monkeypatch.setattr(cli, "build_hypertension_cohort", lambda *_args, **_kwargs: cohort_summary)
    assert cli.main(
        [
            "build-hypertension-cohort",
            "--database-url",
            "postgresql://example",
            "--minimum-age",
            "21",
            "--minimum-follow-up-days",
            "60",
            "--baseline-window-days",
            "14",
        ]
    ) == 0
    assert "rows=3" in capsys.readouterr().out

    terminology = SimpleNamespace(concepts_inserted=4, concepts_existing=2)
    synthea_load_summary = SimpleNamespace(
        terminology=terminology,
        records_persisted={"patients": 2},
    )
    monkeypatch.setattr(
        cli,
        "load_adapted_synthea_dataset",
        lambda *_args, **_kwargs: synthea_load_summary,
    )
    assert cli.main(
        [
            "synthea-load",
            str(tmp_path / "normalized"),
            "--processed-root",
            str(tmp_path / "synthea-processed"),
            "--raw-root",
            str(tmp_path / "raw"),
            "--database-url",
            "postgresql://example",
        ]
    ) == 0
    assert "terminology_inserted=4" in capsys.readouterr().out

    patient_run_id = uuid4()
    raw_receipt_id = uuid4()
    demo_summary = SimpleNamespace(
        patient_run_id=patient_run_id,
        raw_receipt_ids={"patients": raw_receipt_id},
        cohort=cohort_summary,
    )
    monkeypatch.setattr(cli, "run_demo", lambda *_args, **_kwargs: demo_summary)
    assert cli.main(
        [
            "run-demo",
            "--repository-root",
            str(tmp_path),
            "--database-url",
            "postgresql://example",
            "--baseline-existing",
        ]
    ) == 0
    demo_output = capsys.readouterr().out
    assert str(patient_run_id) in demo_output
    assert "Feature output:" in demo_output


def test_cli_synthea_profile_generation_adaptation_and_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["synthea-profile"]) == 0
    profile_document = json.loads(capsys.readouterr().out)
    assert profile_document["name"] == DEFAULT_COHORT_A_PROFILE

    generation_summary = SimpleNamespace(
        profile_name=DEFAULT_COHORT_A_PROFILE,
        upstream_commit="deadbeef",
        files=(object(),) * 6,
        dataset_fingerprint="f" * 64,
        manifest_path=tmp_path / "generation.json",
    )
    monkeypatch.setattr(
        cli,
        "generate_synthea_dataset",
        lambda *_args, **_kwargs: generation_summary,
    )
    assert cli.main(
        [
            "synthea-generate",
            "--workspace",
            str(tmp_path / "workspace"),
            "--checkout",
            str(tmp_path / "checkout"),
            "--replace",
        ]
    ) == 0
    assert "files=6" in capsys.readouterr().out

    normalized = tmp_path / "normalized"
    assert cli.main(
        [
            "synthea-adapt",
            str(SYNTHEA_FIXTURE_A),
            "--output-dir",
            str(normalized),
        ]
    ) == 0
    adaptation_output = capsys.readouterr().out
    assert "Synthea adaptation completed:" in adaptation_output
    assert "terminology=" in adaptation_output

    assert cli.main(["synthea-verify", str(normalized)]) == 0
    assert "Synthea adaptation verified:" in capsys.readouterr().out


def test_cohort_cli_all_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cohort_cli.main(["list-profiles"]) == 0
    listed = capsys.readouterr().out
    assert DEFAULT_COHORT_A_PROFILE in listed
    assert DEFAULT_COHORT_B_PROFILE in listed

    assert cohort_cli.main(["profile", DEFAULT_COHORT_B_PROFILE]) == 0
    profile_document = json.loads(capsys.readouterr().out)
    assert profile_document["name"] == DEFAULT_COHORT_B_PROFILE

    generation_summary = SimpleNamespace(
        profile_name=DEFAULT_COHORT_A_PROFILE,
        upstream_commit="deadbeef",
        dataset_fingerprint="a" * 64,
        manifest_path=tmp_path / "generation.json",
    )
    monkeypatch.setattr(
        cohort_cli,
        "generate_synthea_dataset",
        lambda *_args, **_kwargs: generation_summary,
    )
    assert cohort_cli.main(
        [
            "generate",
            DEFAULT_COHORT_A_PROFILE,
            "--workspace",
            str(tmp_path / "workspace"),
            "--checkout",
            str(tmp_path / "checkout"),
            "--replace",
        ]
    ) == 0
    assert "upstream_commit=deadbeef" in capsys.readouterr().out

    cohort_a = tmp_path / "cohort_a"
    cohort_b = tmp_path / "cohort_b"
    assert cohort_cli.main(
        ["adapt", DEFAULT_COHORT_A_PROFILE, str(SYNTHEA_FIXTURE_A), "--output-dir", str(cohort_a)]
    ) == 0
    assert "cohort adaptation completed" in capsys.readouterr().out
    assert cohort_cli.main(
        ["adapt", DEFAULT_COHORT_B_PROFILE, str(SYNTHEA_FIXTURE_B), "--output-dir", str(cohort_b)]
    ) == 0
    capsys.readouterr()

    assert cohort_cli.main(["verify", DEFAULT_COHORT_A_PROFILE, str(cohort_a)]) == 0
    assert "cohort verified" in capsys.readouterr().out

    comparison_dir = tmp_path / "comparison"
    assert cohort_cli.main(
        ["compare", str(cohort_a), str(cohort_b), "--output-dir", str(comparison_dir)]
    ) == 0
    assert "overlaps=" in capsys.readouterr().out

    quality_dir = tmp_path / "quality"
    assert cohort_cli.main(
        ["quality-report", str(cohort_a), str(cohort_b), "--output-dir", str(quality_dir)]
    ) == 0
    assert "attrition and missingness report completed" in capsys.readouterr().out

    _patch_connection(monkeypatch, cohort_cli)
    monkeypatch.setattr(
        cohort_cli,
        "migrate_database",
        lambda *_args, **_kwargs: SimpleNamespace(current_version=8),
    )
    pair_summary = SimpleNamespace(
        comparison=SimpleNamespace(comparison_fingerprint="c" * 64),
        cohort_a_load=SimpleNamespace(records_persisted={"patients": 2}),
        cohort_b_load=SimpleNamespace(records_persisted={"patients": 2}),
        load_manifest_path=tmp_path / "load.json",
    )
    monkeypatch.setattr(
        cohort_cli,
        "load_synthea_cohort_pair",
        lambda *_args, **_kwargs: pair_summary,
    )
    assert cohort_cli.main(
        [
            "load-pair",
            str(cohort_a),
            str(cohort_b),
            "--processed-root",
            str(tmp_path / "processed"),
            "--raw-root",
            str(tmp_path / "raw"),
            "--database-url",
            "postgresql://example",
            "--baseline-existing",
            "--replace",
        ]
    ) == 0
    assert "cohort pair loaded" in capsys.readouterr().out


def test_benchmark_cli_guards_and_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        benchmark_cli.main([])

    with pytest.raises(SystemExit):
        benchmark_cli.main(
            ["--allow-destructive-reset", "--patients", "10", "5"]
        )

    _patch_connection(monkeypatch, benchmark_cli)
    monkeypatch.setattr(
        benchmark_cli,
        "migrate_database",
        lambda _connection: SimpleNamespace(current_version=8),
    )
    monkeypatch.setattr(
        benchmark_cli,
        "assert_isolated_empty_benchmark_database",
        lambda _connection: None,
    )
    artifacts = SimpleNamespace(
        patient_counts=(5, 10),
        total_trials=8,
        median_speedup_by_patient_count={5: 1.2, 10: 1.3},
        report_path=tmp_path / "report.json",
        trials_csv_path=tmp_path / "trials.csv",
        summary_markdown_path=tmp_path / "summary.md",
    )
    monkeypatch.setattr(
        benchmark_cli,
        "run_loading_benchmark",
        lambda *_args, **_kwargs: artifacts,
    )
    assert benchmark_cli.main(
        [
            "--allow-destructive-reset",
            "--patients",
            "5",
            "10",
            "--repetitions",
            "4",
            "--warmups",
            "0",
            "--output-dir",
            str(tmp_path),
            "--database-url",
            "postgresql://example",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "trials=8" in output
    assert "Markdown summary:" in output


def test_demo_orchestrates_all_datasets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    datasets = ("patients", "encounters")
    monkeypatch.setattr(demo, "dataset_names", lambda: datasets)

    validation_ids = {dataset: uuid4() for dataset in datasets}
    receipt_ids = {dataset: uuid4() for dataset in datasets}

    def validate(dataset: str, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            run_id=validation_ids[dataset],
            raw_receipt_id=receipt_ids[dataset],
            rows_valid=2,
            rows_invalid=0,
        )

    monkeypatch.setattr(demo, "run_dataset_validation", validate)
    _patch_connection(monkeypatch, demo)
    monkeypatch.setattr(
        demo,
        "migrate_database",
        lambda *_args, **_kwargs: SimpleNamespace(
            previous_version=0,
            current_version=8,
            applied_versions=(1, 2, 3, 4, 5, 6, 7, 8),
        ),
    )
    monkeypatch.setattr(
        demo,
        "persist_dataset_validation_outputs",
        lambda *_args, **_kwargs: SimpleNamespace(records_upserted=2),
    )
    cohort = SimpleNamespace(
        cohort_run_id=uuid4(),
        row_count=1,
        features_path=tmp_path / "features.csv",
    )
    monkeypatch.setattr(demo, "build_hypertension_cohort", lambda *_args: cohort)

    summary = demo.run_demo(
        tmp_path,
        "postgresql://example",
        reference_date=date(2026, 7, 29),
        baseline_existing=True,
    )
    assert summary.patient_run_id == validation_ids["patients"]
    assert summary.dataset_run_ids == validation_ids
    assert summary.raw_receipt_ids == receipt_ids
    assert summary.cohort is cohort


def test_entrypoint_logs_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(entrypoint, "configure_logging", lambda: None)
    monkeypatch.setattr(
        entrypoint,
        "emit_log",
        lambda _logger, _level, event, _message, **fields: events.append((event, fields)),
    )
    monkeypatch.setattr(entrypoint.sys, "argv", ["clinical-data", "validate-contracts"])
    monkeypatch.setattr(entrypoint.time, "perf_counter", iter((1.0, 1.025)).__next__)
    monkeypatch.setattr(entrypoint, "cli_main", lambda: 0)

    assert entrypoint._command_name(()) == "unknown"
    assert entrypoint.main() == 0
    assert [event for event, _fields in events] == [
        "cli.command.started",
        "cli.command.completed",
    ]
    assert events[-1][1]["exit_code"] == 0

    events.clear()
    monkeypatch.setattr(entrypoint.time, "perf_counter", iter((2.0, 2.01)).__next__)

    def fail() -> int:
        raise RuntimeError("expected failure")

    monkeypatch.setattr(entrypoint, "cli_main", fail)
    with pytest.raises(RuntimeError, match="expected failure"):
        entrypoint.main()
    assert [event for event, _fields in events] == [
        "cli.command.started",
        "cli.command.failed",
    ]
