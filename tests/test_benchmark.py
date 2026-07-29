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
from clinical_data_platform.benchmark_cli import build_parser
from clinical_data_platform.migration import migrate_database


def test_benchmark_configuration_requires_increasing_unique_sizes() -> None:
    with pytest.raises(ValueError, match="unique and increasing"):
        BenchmarkConfiguration(patient_counts=(100, 50), repetitions=1, warmups=0)
    with pytest.raises(ValueError, match="positive"):
        BenchmarkConfiguration(patient_counts=(0,), repetitions=1, warmups=0)


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


def test_benchmark_cli_accepts_explicit_protocol() -> None:
    args = build_parser().parse_args(
        [
            "--patients",
            "10",
            "20",
            "--repetitions",
            "3",
            "--warmups",
            "0",
            "--seed",
            "42",
        ]
    )
    assert args.patients == [10, 20]
    assert args.repetitions == 3
    assert args.warmups == 0
    assert args.seed == 42


@pytest.mark.integration
def test_loading_benchmark_compares_equivalent_governed_results(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
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
