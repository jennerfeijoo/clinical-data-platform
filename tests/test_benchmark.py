import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkConfiguration,
    generate_benchmark_workload,
    run_loading_benchmark,
)
from clinical_data_platform.benchmark_cli import (
    assert_isolated_empty_benchmark_database,
    build_parser,
    main,
)
from clinical_data_platform.migration import migrate_database

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIRECTORY = (
    REPOSITORY_ROOT
    / "benchmarks"
    / "loading"
    / "github-actions-run-30466706538"
)


def test_benchmark_configuration_requires_increasing_unique_sizes() -> None:
    with pytest.raises(ValueError, match="unique and increasing"):
        BenchmarkConfiguration(patient_counts=(100, 50), repetitions=2, warmups=0)
    with pytest.raises(ValueError, match="positive"):
        BenchmarkConfiguration(patient_counts=(0,), repetitions=2, warmups=0)


def test_benchmark_workload_is_deterministic_and_has_expected_ratios() -> None:
    first = generate_benchmark_workload(3, 20260729)
    second = generate_benchmark_workload(3, 20260729)
    changed = generate_benchmark_workload(3, 20260730)

    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != changed.fingerprint
    assert first.row_counts == {
        "patients": 3,
        "encounters": 6,
        "diagnoses": 6,
        "observations": 18,
        "medications": 6,
        "procedures": 6,
    }
    assert first.total_rows == 45
    assert first.records["patients"][0]["patient_id"] == "BP00000000"


def test_benchmark_cli_accepts_explicit_balanced_protocol() -> None:
    args = build_parser().parse_args(
        [
            "--allow-destructive-reset",
            "--patients",
            "10",
            "20",
            "--repetitions",
            "4",
            "--warmups",
            "0",
            "--seed",
            "42",
        ]
    )
    assert args.allow_destructive_reset is True
    assert args.patients == [10, 20]
    assert args.repetitions == 4
    assert args.warmups == 0
    assert args.seed == 42


def test_benchmark_cli_defaults_to_balanced_repetitions() -> None:
    assert build_parser().parse_args([]).repetitions == 6


def test_benchmark_cli_requires_destructive_confirmation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--patients", "1", "--repetitions", "2", "--warmups", "0"])
    assert error.value.code == 2
    assert "--allow-destructive-reset is required" in capsys.readouterr().err


def test_benchmark_cli_rejects_unbalanced_repetitions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--allow-destructive-reset",
                "--patients",
                "1",
                "--repetitions",
                "3",
                "--warmups",
                "0",
            ]
        )
    assert error.value.code == 2
    assert "positive even integer" in capsys.readouterr().err


def test_committed_reference_evidence_is_internally_consistent() -> None:
    reference_path = REFERENCE_DIRECTORY / "reference-run.json"
    trials_path = REFERENCE_DIRECTORY / "benchmark-trials.csv"
    document = json.loads(reference_path.read_text(encoding="utf-8"))

    committed_bytes = trials_path.read_bytes().replace(b"\r\n", b"\n")
    source_artifact_bytes = committed_bytes.replace(b"\n", b"\r\n")
    source_trials_sha256 = hashlib.sha256(source_artifact_bytes).hexdigest()
    assert document["schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert document["evidence"]["workflow_run_id"] == "30466706538"
    assert document["evidence"]["source_trials_sha256"] == source_trials_sha256
    assert document["configuration"]["patient_counts"] == [250, 1000, 2500]
    assert document["configuration"]["repetitions"] == 5
    assert all(item["copy_speedup"] > 1 for item in document["comparisons"])

    with trials_path.open(encoding="utf-8", newline="") as file:
        trials = list(csv.DictReader(file))

    assert len(trials) == 30
    for patient_count in ("250", "1000", "2500"):
        size_trials = [trial for trial in trials if trial["patient_count"] == patient_count]
        assert len(size_trials) == 10
        assert {trial["method"] for trial in size_trials} == {"copy", "executemany"}
        assert len({trial["database_fingerprint"] for trial in size_trials}) == 1


@pytest.mark.integration
def test_benchmark_refuses_populated_governed_database(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
    with connection.transaction():
        connection.execute("CREATE TABLE analytics.benchmark_guard_fixture (id INTEGER)")
        connection.execute("INSERT INTO analytics.benchmark_guard_fixture VALUES (1)")

    with pytest.raises(RuntimeError, match="Benchmark target is not empty"):
        assert_isolated_empty_benchmark_database(connection)


@pytest.mark.integration
def test_loading_benchmark_compares_equivalent_governed_results(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
    assert_isolated_empty_benchmark_database(connection)
    artifacts = run_loading_benchmark(
        connection,
        tmp_path / "benchmark",
        configuration=BenchmarkConfiguration(
            patient_counts=(8,),
            repetitions=2,
            warmups=0,
            seed=20260729,
        ),
    )

    report = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
    trials = report["trials"]
    aggregates = report["aggregates"]
    comparisons = report["comparisons"]

    assert report["schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert report["configuration"]["method_order_policy"] == "alternating_ab_ba"
    assert len(trials) == 4
    assert {trial["method"] for trial in trials} == {"copy", "executemany"}
    assert len({trial["database_fingerprint"] for trial in trials}) == 1
    assert len(aggregates) == 2
    assert len(comparisons) == 1
    assert comparisons[0]["copy_speedup"] > 0
    assert artifacts.total_trials == 4
    assert artifacts.trials_csv_path.exists()
    assert artifacts.summary_markdown_path.exists()
    assert "Interpretation limits" in artifacts.summary_markdown_path.read_text(
        encoding="utf-8"
    )

    counts = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM clinical.patients),
            (SELECT COUNT(*) FROM clinical.encounters),
            (SELECT COUNT(*) FROM clinical.diagnoses),
            (SELECT COUNT(*) FROM clinical.observations),
            (SELECT COUNT(*) FROM clinical.medications),
            (SELECT COUNT(*) FROM clinical.procedures),
            (SELECT COUNT(*) FROM clinical.patient_history)
        """
    ).fetchone()
    assert counts == (8, 16, 16, 48, 16, 16, 8)
