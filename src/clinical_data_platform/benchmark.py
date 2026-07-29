"""Reproducible benchmark for governed PostgreSQL clinical loading paths."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Literal
from uuid import UUID, uuid5

import psycopg
from psycopg import sql

import clinical_data_platform
from clinical_data_platform.bulk import CopyMergePlan, copy_merge_rows
from clinical_data_platform.benchmark_safety import (
    assert_isolated_empty_benchmark_database,
)
from clinical_data_platform.models import ClinicalRecord
from clinical_data_platform.registry import dataset_names, get_dataset_definition

BenchmarkMethod = Literal["copy", "executemany"]
BENCHMARK_SCHEMA_VERSION = "1.0.0"
BENCHMARK_NAMESPACE = UUID("91f13568-8330-4d16-b16e-2acda4760910")
BENCHMARK_REFERENCE_DATE = date(2026, 7, 29)
BENCHMARK_METHODS: tuple[BenchmarkMethod, BenchmarkMethod] = ("copy", "executemany")


@dataclass(frozen=True, slots=True)
class BenchmarkConfiguration:
    """Parameters that define one reproducible benchmark execution."""

    patient_counts: tuple[int, ...] = (250, 1000, 2500)
    repetitions: int = 6
    warmups: int = 1
    seed: int = 20260729

    def __post_init__(self) -> None:
        if not self.patient_counts or any(value <= 0 for value in self.patient_counts):
            raise ValueError("Benchmark patient counts must contain positive integers.")
        if tuple(sorted(set(self.patient_counts))) != self.patient_counts:
            raise ValueError("Benchmark patient counts must be unique and increasing.")
        if self.repetitions <= 0 or self.repetitions % 2 != 0:
            raise ValueError(
                "Benchmark repetitions must be a positive even integer so method "
                "starting positions are balanced."
            )
        if self.warmups < 0:
            raise ValueError("Benchmark warmups must be non-negative.")


@dataclass(frozen=True, slots=True)
class BenchmarkWorkload:
    """One deterministic six-entity synthetic population."""

    patient_count: int
    seed: int
    records: Mapping[str, tuple[ClinicalRecord, ...]]
    row_counts: Mapping[str, int]
    total_rows: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class BenchmarkTrial:
    """One measured execution of one loading method."""

    patient_count: int
    total_rows: int
    repetition: int
    order_position: int
    method: BenchmarkMethod
    elapsed_ms: float
    rows_per_second: float
    dataset_elapsed_ms: Mapping[str, float]
    database_fingerprint: str


@dataclass(frozen=True, slots=True)
class BenchmarkArtifacts:
    """Files and headline comparisons emitted by a benchmark run."""

    report_path: Path
    trials_csv_path: Path
    summary_markdown_path: Path
    patient_counts: tuple[int, ...]
    total_trials: int
    median_speedup_by_patient_count: Mapping[int, float]


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _append_record(
    records: dict[str, list[ClinicalRecord]],
    dataset: str,
    record: ClinicalRecord,
) -> None:
    records[dataset].append(record)


def generate_benchmark_workload(patient_count: int, seed: int) -> BenchmarkWorkload:
    """Generate deterministic contract-compatible records for all six entities."""
    if patient_count <= 0:
        raise ValueError("Benchmark patient_count must be positive.")

    rng = random.Random(seed + patient_count)
    source_system = "synthetic_benchmark"
    records: dict[str, list[ClinicalRecord]] = {name: [] for name in dataset_names()}
    diagnosis_codes = ("I10", "E11.9", "E78.5", "J45.909")
    medication_profiles = (
        ("RXNORM", "197361", "10", "mg", "ORAL"),
        ("ATC", "C09AA05", "20", "mg", "ORAL"),
    )
    procedure_profiles = (("CPT", "93000"), ("SNOMED", "386053000"))
    observation_profiles = (
        ("SYSTOLIC_BP", "mmHg", 110.0, 48.0),
        ("DIASTOLIC_BP", "mmHg", 68.0, 28.0),
        ("HEART_RATE", "bpm", 55.0, 42.0),
    )

    for index in range(patient_count):
        patient_id = f"BP{index:08d}"
        birth_year = 1940 + rng.randrange(66)
        birth_date = date(birth_year, 1 + rng.randrange(12), 1 + rng.randrange(28))
        sex_at_birth = ("F", "M", "OTHER", "UNKNOWN")[rng.randrange(4)]
        _append_record(
            records,
            "patients",
            {
                "patient_id": patient_id,
                "sex_at_birth": sex_at_birth,
                "birth_date": birth_date.isoformat(),
                "death_date": "",
                "source_system": source_system,
            },
        )

        first_start = datetime(2025, 1, 1, 8, tzinfo=UTC) + timedelta(
            days=index % 480,
            hours=index % 8,
        )
        encounter_ids = (f"BE{index:08d}A", f"BE{index:08d}B")
        encounter_starts = (first_start, first_start + timedelta(days=30))

        for encounter_number, (encounter_id, encounter_start) in enumerate(
            zip(encounter_ids, encounter_starts, strict=True)
        ):
            _append_record(
                records,
                "encounters",
                {
                    "encounter_id": encounter_id,
                    "patient_id": patient_id,
                    "encounter_type": "OUTPATIENT",
                    "start_datetime": encounter_start.isoformat(),
                    "end_datetime": (encounter_start + timedelta(minutes=45)).isoformat(),
                    "source_system": source_system,
                },
            )

            diagnosis_code = diagnosis_codes[(index + encounter_number) % len(diagnosis_codes)]
            _append_record(
                records,
                "diagnoses",
                {
                    "diagnosis_id": f"BD{index:08d}{encounter_number}",
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "code_system": "ICD10",
                    "diagnosis_code": diagnosis_code,
                    "diagnosis_datetime": (encounter_start + timedelta(minutes=10)).isoformat(),
                    "source_system": source_system,
                },
            )

            for observation_number, (code, unit, minimum, spread) in enumerate(
                observation_profiles
            ):
                value = minimum + rng.random() * spread
                _append_record(
                    records,
                    "observations",
                    {
                        "observation_id": (
                            f"BO{index:08d}{encounter_number}{observation_number}"
                        ),
                        "patient_id": patient_id,
                        "encounter_id": encounter_id,
                        "observation_code": code,
                        "value_numeric": f"{value:.3f}",
                        "unit": unit,
                        "observed_at": (
                            encounter_start + timedelta(minutes=15 + observation_number)
                        ).isoformat(),
                        "source_system": source_system,
                    },
                )

            code_system, medication_code, dose_value, dose_unit, route = (
                medication_profiles[encounter_number]
            )
            _append_record(
                records,
                "medications",
                {
                    "medication_id": f"BM{index:08d}{encounter_number}",
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "code_system": code_system,
                    "medication_code": medication_code,
                    "status": "ACTIVE",
                    "start_datetime": (encounter_start + timedelta(minutes=5)).isoformat(),
                    "end_datetime": "",
                    "dose_value": dose_value,
                    "dose_unit": dose_unit,
                    "route": route,
                    "source_system": source_system,
                },
            )

            procedure_system, procedure_code = procedure_profiles[encounter_number]
            _append_record(
                records,
                "procedures",
                {
                    "procedure_id": f"BR{index:08d}{encounter_number}",
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "code_system": procedure_system,
                    "procedure_code": procedure_code,
                    "procedure_datetime": (
                        encounter_start + timedelta(minutes=20)
                    ).isoformat(),
                    "status": "COMPLETED",
                    "source_system": source_system,
                },
            )

    frozen_records = {name: tuple(records[name]) for name in dataset_names()}
    row_counts = {name: len(frozen_records[name]) for name in dataset_names()}
    hasher = hashlib.sha256()
    hasher.update(
        _canonical_json(
            {
                "schema_version": BENCHMARK_SCHEMA_VERSION,
                "patient_count": patient_count,
                "seed": seed,
                "reference_date": BENCHMARK_REFERENCE_DATE.isoformat(),
            }
        )
    )
    for dataset in dataset_names():
        for record in frozen_records[dataset]:
            hasher.update(dataset.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(_canonical_json(record))
            hasher.update(b"\n")

    return BenchmarkWorkload(
        patient_count=patient_count,
        seed=seed,
        records=frozen_records,
        row_counts=row_counts,
        total_rows=sum(row_counts.values()),
        fingerprint=hasher.hexdigest(),
    )


def _identifier_list(names: Sequence[str]) -> sql.Composed:
    return sql.SQL(", ").join(sql.Identifier(name) for name in names)


def _rowwise_upsert_statement(plan: CopyMergePlan) -> sql.Composed:
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in plan.columns)
    conflict_action: sql.SQL | sql.Composed
    if plan.update_columns:
        assignments: list[sql.Composable] = [
            sql.SQL("{} = EXCLUDED.{}").format(
                sql.Identifier(column),
                sql.Identifier(column),
            )
            for column in plan.update_columns
        ]
        if plan.touch_loaded_at:
            assignments.append(sql.SQL("loaded_at = CURRENT_TIMESTAMP"))
        conflict_action = sql.SQL("DO UPDATE SET {}").format(sql.SQL(", ").join(assignments))
    else:
        conflict_action = sql.SQL("DO NOTHING")

    return sql.SQL(
        "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) {}"
    ).format(
        sql.Identifier(plan.schema, plan.table),
        _identifier_list(plan.columns),
        placeholders,
        _identifier_list(plan.conflict_columns),
        conflict_action,
    )


def _truncate_benchmark_state(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction():
        connection.execute(
            "TRUNCATE TABLE audit.pipeline_runs RESTART IDENTITY CASCADE"
        )


def _benchmark_run_ids(
    workload: BenchmarkWorkload,
    trial_label: str,
) -> dict[str, UUID]:
    return {
        dataset: uuid5(
            BENCHMARK_NAMESPACE,
            f"{BENCHMARK_SCHEMA_VERSION}:{workload.fingerprint}:{trial_label}:{dataset}",
        )
        for dataset in dataset_names()
    }


def _register_benchmark_runs(
    connection: psycopg.Connection[Any],
    workload: BenchmarkWorkload,
    trial_label: str,
) -> dict[str, UUID]:
    run_ids = _benchmark_run_ids(workload, trial_label)
    now = datetime.now(UTC)
    with connection.transaction():
        for dataset in dataset_names():
            contract = get_dataset_definition(dataset).contract
            run_id = run_ids[dataset]
            row_count = workload.row_counts[dataset]
            connection.execute(
                """
                INSERT INTO audit.pipeline_runs (
                    run_id, dataset_name, source_path, source_sha256,
                    raw_receipt_id, raw_received_at, raw_storage_version,
                    raw_manifest_path, raw_manifest_sha256, raw_object_path,
                    raw_size_bytes, contract_path, contract_version, contract_sha256,
                    reference_date, rows_received, rows_valid, rows_invalid,
                    validation_errors, status, generated_at, current_stage,
                    attempt_count, started_at, validated_at,
                    local_journal_event_count, local_journal_head_sha256,
                    audit_event_count, audit_head_sha256, audit_gap_reason
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, 0, 0,
                    'validated', %s, 'benchmark_prepared', 0, %s, %s,
                    0, NULL, 0, NULL, 'benchmark_kernel_excludes_pipeline_audit'
                )
                """,
                (
                    run_id,
                    dataset,
                    f"benchmark://{workload.fingerprint}/{dataset}.csv",
                    workload.fingerprint,
                    uuid5(BENCHMARK_NAMESPACE, f"{run_id}:receipt"),
                    now,
                    "benchmark/1.0.0",
                    f"benchmark/{workload.fingerprint}/{dataset}/receipt.json",
                    workload.fingerprint,
                    f"benchmark/{workload.fingerprint}/{dataset}/source.csv",
                    row_count,
                    contract.resource_path,
                    contract.version,
                    contract.sha256,
                    BENCHMARK_REFERENCE_DATE,
                    row_count,
                    row_count,
                    now,
                    now,
                    now,
                ),
            )
    return run_ids


def _load_with_copy(
    connection: psycopg.Connection[Any],
    dataset: str,
    records: Sequence[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> int:
    definition = get_dataset_definition(dataset)
    with connection.transaction():
        summary = copy_merge_rows(
            connection,
            definition.copy_plan,
            definition.row_builder(records, run_id, source_sha256),
        )
    return summary.rows_copied


def _load_with_executemany(
    connection: psycopg.Connection[Any],
    dataset: str,
    records: Sequence[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> int:
    definition = get_dataset_definition(dataset)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.executemany(
                _rowwise_upsert_statement(definition.copy_plan),
                definition.row_builder(records, run_id, source_sha256),
            )
    return len(records)


def _database_evidence(
    connection: psycopg.Connection[Any],
    workload: BenchmarkWorkload,
) -> str:
    counts: dict[str, int] = {}
    digests: dict[str, str] = {}
    for dataset in dataset_names():
        definition = get_dataset_definition(dataset)
        row = connection.execute(
            sql.SQL(
                "SELECT COUNT(*), "
                "COALESCE(md5(string_agg(record_sha256::text, '' ORDER BY {})), md5('')) "
                "FROM {}"
            ).format(
                sql.Identifier(definition.id_column),
                sql.Identifier(definition.copy_plan.schema, definition.copy_plan.table),
            )
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Benchmark could not inspect dataset {dataset!r}.")
        counts[dataset] = int(row[0])
        digests[dataset] = str(row[1])
        if counts[dataset] != workload.row_counts[dataset]:
            raise RuntimeError(
                f"Benchmark row count mismatch for {dataset}: "
                f"expected {workload.row_counts[dataset]}, found {counts[dataset]}."
            )

    history_row = connection.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) FILTER (WHERE is_current),
            COALESCE(md5(string_agg(record_sha256::text, '' ORDER BY patient_id)), md5(''))
        FROM clinical.patient_history
        """
    ).fetchone()
    if history_row is None:
        raise RuntimeError("Benchmark could not inspect patient history.")
    counts["patient_history"] = int(history_row[0])
    counts["patient_history_current"] = int(history_row[1])
    digests["patient_history"] = str(history_row[2])
    if counts["patient_history"] != workload.patient_count:
        raise RuntimeError("Benchmark patient history count does not match patient count.")
    if counts["patient_history_current"] != workload.patient_count:
        raise RuntimeError("Benchmark current patient history count is inconsistent.")

    normalized_expected = sum(
        workload.row_counts[name]
        for name in ("diagnoses", "observations", "medications", "procedures")
    )
    normalized_row = connection.execute(
        "SELECT COUNT(*) FROM terminology.normalized_clinical_codes"
    ).fetchone()
    normalized_count = int(normalized_row[0]) if normalized_row is not None else -1
    counts["normalized_clinical_codes"] = normalized_count
    if normalized_count != normalized_expected:
        raise RuntimeError(
            "Benchmark terminology binding count does not match terminology-linked rows."
        )

    return hashlib.sha256(
        _canonical_json({"counts": counts, "digests": digests})
    ).hexdigest()


def _execute_trial(
    connection: psycopg.Connection[Any],
    workload: BenchmarkWorkload,
    method: BenchmarkMethod,
    repetition: int,
    order_position: int,
    *,
    measured: bool,
) -> BenchmarkTrial | None:
    phase = "measured" if measured else "warmup"
    trial_label = f"{method}:{repetition}:{order_position}:{phase}"
    _truncate_benchmark_state(connection)
    run_ids = _register_benchmark_runs(connection, workload, trial_label)

    dataset_elapsed_ms: dict[str, float] = {}
    total_started = perf_counter_ns()
    for dataset in dataset_names():
        started = perf_counter_ns()
        if method == "copy":
            rows_loaded = _load_with_copy(
                connection,
                dataset,
                workload.records[dataset],
                run_ids[dataset],
                workload.fingerprint,
            )
        else:
            rows_loaded = _load_with_executemany(
                connection,
                dataset,
                workload.records[dataset],
                run_ids[dataset],
                workload.fingerprint,
            )
        dataset_elapsed_ms[dataset] = (perf_counter_ns() - started) / 1_000_000
        if rows_loaded != workload.row_counts[dataset]:
            raise RuntimeError(
                f"Benchmark loader reported {rows_loaded} rows for {dataset}, "
                f"expected {workload.row_counts[dataset]}."
            )
    elapsed_ms = (perf_counter_ns() - total_started) / 1_000_000
    database_fingerprint = _database_evidence(connection, workload)

    if not measured:
        return None
    return BenchmarkTrial(
        patient_count=workload.patient_count,
        total_rows=workload.total_rows,
        repetition=repetition,
        order_position=order_position,
        method=method,
        elapsed_ms=elapsed_ms,
        rows_per_second=workload.total_rows / (elapsed_ms / 1000),
        dataset_elapsed_ms=dataset_elapsed_ms,
        database_fingerprint=database_fingerprint,
    )


def _git_commit() -> str | None:
    environment_sha = os.getenv("GITHUB_SHA", "").strip()
    if environment_sha:
        return environment_sha
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _cpu_model() -> str | None:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                return line.split(":", maxsplit=1)[1].strip()
    processor = platform.processor().strip()
    return processor or None


def _memory_bytes() -> int | None:
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def _environment_document(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    settings: dict[str, str] = {}
    for setting in (
        "fsync",
        "full_page_writes",
        "shared_buffers",
        "synchronous_commit",
        "wal_level",
    ):
        row = connection.execute("SELECT current_setting(%s)", (setting,)).fetchone()
        settings[setting] = str(row[0]) if row is not None else "unknown"
    version_row = connection.execute("SHOW server_version").fetchone()
    return {
        "package_version": clinical_data_platform.__version__,
        "git_commit": _git_commit(),
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "operating_system": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": _cpu_model(),
        "logical_cpu_count": os.cpu_count(),
        "physical_memory_bytes": _memory_bytes(),
        "postgresql_version": str(version_row[0]) if version_row is not None else "unknown",
        "postgresql_settings": settings,
        "github_runner_name": os.getenv("RUNNER_NAME"),
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
    }


def _aggregate_trials(trials: Sequence[BenchmarkTrial]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, BenchmarkMethod], list[BenchmarkTrial]] = defaultdict(list)
    for trial in trials:
        grouped[(trial.patient_count, trial.method)].append(trial)

    aggregates: list[dict[str, Any]] = []
    for patient_count, method in sorted(grouped):
        method_trials = grouped[(patient_count, method)]
        elapsed = [trial.elapsed_ms for trial in method_trials]
        throughput = [trial.rows_per_second for trial in method_trials]
        aggregates.append(
            {
                "patient_count": patient_count,
                "total_rows": method_trials[0].total_rows,
                "method": method,
                "repetitions": len(method_trials),
                "median_elapsed_ms": statistics.median(elapsed),
                "mean_elapsed_ms": statistics.mean(elapsed),
                "stdev_elapsed_ms": statistics.stdev(elapsed) if len(elapsed) > 1 else 0.0,
                "minimum_elapsed_ms": min(elapsed),
                "maximum_elapsed_ms": max(elapsed),
                "median_rows_per_second": statistics.median(throughput),
                "dataset_median_elapsed_ms": {
                    dataset: statistics.median(
                        trial.dataset_elapsed_ms[dataset] for trial in method_trials
                    )
                    for dataset in dataset_names()
                },
            }
        )
    return aggregates


def _comparisons(aggregates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_size: dict[int, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for aggregate in aggregates:
        by_size[int(aggregate["patient_count"])][str(aggregate["method"])] = aggregate

    comparisons: list[dict[str, Any]] = []
    for patient_count in sorted(by_size):
        copy_result = by_size[patient_count]["copy"]
        rowwise_result = by_size[patient_count]["executemany"]
        copy_median = float(copy_result["median_elapsed_ms"])
        rowwise_median = float(rowwise_result["median_elapsed_ms"])
        comparisons.append(
            {
                "patient_count": patient_count,
                "total_rows": int(copy_result["total_rows"]),
                "copy_median_elapsed_ms": copy_median,
                "executemany_median_elapsed_ms": rowwise_median,
                "copy_speedup": rowwise_median / copy_median,
                "elapsed_reduction_percent": (1 - copy_median / rowwise_median) * 100,
            }
        )
    return comparisons


def _validate_equivalent_fingerprints(trials: Sequence[BenchmarkTrial]) -> None:
    fingerprints: dict[int, set[str]] = defaultdict(set)
    for trial in trials:
        fingerprints[trial.patient_count].add(trial.database_fingerprint)
    for patient_count, values in fingerprints.items():
        if len(values) != 1:
            raise RuntimeError(
                "Benchmark methods produced different governed database content for "
                f"patient_count={patient_count}."
            )


def _write_trial_csv(path: Path, trials: Sequence[BenchmarkTrial]) -> None:
    fieldnames = [
        "patient_count",
        "total_rows",
        "repetition",
        "order_position",
        "method",
        "elapsed_ms",
        "rows_per_second",
        "database_fingerprint",
        *(f"{dataset}_elapsed_ms" for dataset in dataset_names()),
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for trial in trials:
            row: dict[str, Any] = {
                "patient_count": trial.patient_count,
                "total_rows": trial.total_rows,
                "repetition": trial.repetition,
                "order_position": trial.order_position,
                "method": trial.method,
                "elapsed_ms": f"{trial.elapsed_ms:.6f}",
                "rows_per_second": f"{trial.rows_per_second:.3f}",
                "database_fingerprint": trial.database_fingerprint,
            }
            row.update(
                {
                    f"{dataset}_elapsed_ms": f"{trial.dataset_elapsed_ms[dataset]:.6f}"
                    for dataset in dataset_names()
                }
            )
            writer.writerow(row)


def _write_summary_markdown(path: Path, report: Mapping[str, Any]) -> None:
    configuration: Mapping[str, Any] = report["configuration"]
    environment: Mapping[str, Any] = report["environment"]
    aggregates: Sequence[Mapping[str, Any]] = report["aggregates"]
    comparisons: Sequence[Mapping[str, Any]] = report["comparisons"]

    lines = [
        "# PostgreSQL loading benchmark",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Protocol",
        "",
        "- Synthetic deterministic six-entity workload.",
        "- Actual governed clinical tables and active triggers/constraints.",
        "- COPY uses temporary staging plus set-based merge.",
        "- Reference uses psycopg `executemany` with the equivalent upsert.",
        "- Warm-up per method; measured method order alternates by repetition.",
        (
            "- Timing includes row conversion, transfer, triggers, constraints, "
            "merge/upsert and commit."
        ),
        (
            "- Timing excludes generation, raw capture, contract validation, "
            "audit registration and verification queries."
        ),
        "",
        "## Configuration",
        "",
        f"- Patient counts: `{configuration['patient_counts']}`",
        f"- Repetitions: `{configuration['repetitions']}`",
        f"- Warm-ups: `{configuration['warmups']}`",
        f"- Seed: `{configuration['seed']}`",
        "",
        "## Environment",
        "",
        f"- Package: `{environment['package_version']}`",
        f"- Git commit: `{environment['git_commit']}`",
        f"- Python: `{environment['python_version']}`",
        f"- PostgreSQL: `{environment['postgresql_version']}`",
        f"- OS: `{environment['operating_system']}`",
        f"- CPU: `{environment['cpu_model']}`",
        f"- Logical CPUs: `{environment['logical_cpu_count']}`",
        f"- Physical memory bytes: `{environment['physical_memory_bytes']}`",
        "",
        "## Aggregate results",
        "",
        (
            "| Patients | Clinical rows | Method | n | Median ms | Min ms | "
            "Max ms | Median rows/s |"
        ),
        "|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for item in aggregates:
        lines.append(
            "| {patient_count} | {total_rows} | {method} | {repetitions} | "
            "{median_elapsed_ms:.3f} | {minimum_elapsed_ms:.3f} | "
            "{maximum_elapsed_ms:.3f} | {median_rows_per_second:.1f} |".format(
                **item
            )
        )

    lines.extend(
        [
            "",
            "## COPY comparison",
            "",
            (
                "| Patients | Clinical rows | COPY median ms | executemany median ms | "
                "COPY speedup | Elapsed reduction |"
            ),
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in comparisons:
        lines.append(
            "| {patient_count} | {total_rows} | {copy_median_elapsed_ms:.3f} | "
            "{executemany_median_elapsed_ms:.3f} | {copy_speedup:.3f}x | "
            "{elapsed_reduction_percent:.2f}% |".format(**item)
        )

    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            (
                "- Environment-specific engineering measurements, not universal "
                "PostgreSQL constants."
            ),
            "- GitHub-hosted runner hardware and contention can vary between runs.",
            (
                "- `executemany` is the previous application reference path, not "
                "every batching strategy."
            ),
            (
                "- Initial governed loading only; no updates, concurrency or "
                "end-to-end pipeline latency."
            ),
            (
                "- No peak-memory claim because Python allocation tracking omits "
                "PostgreSQL and native-driver memory."
            ),
            (
                "- Descriptive medians only; the repetition count does not support "
                "inferential confidence intervals."
            ),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_loading_benchmark(
    connection: psycopg.Connection[Any],
    output_directory: Path,
    *,
    configuration: BenchmarkConfiguration | None = None,
) -> BenchmarkArtifacts:
    """Run, verify and export a reproducible COPY versus executemany benchmark."""
    assert_isolated_empty_benchmark_database(connection)
    effective = configuration or BenchmarkConfiguration()
    output_directory.mkdir(parents=True, exist_ok=True)
    workloads = [
        generate_benchmark_workload(patient_count, effective.seed)
        for patient_count in effective.patient_counts
    ]
    trials: list[BenchmarkTrial] = []

    for workload in workloads:
        for method in BENCHMARK_METHODS:
            for warmup in range(effective.warmups):
                _execute_trial(
                    connection,
                    workload,
                    method,
                    repetition=-(warmup + 1),
                    order_position=0,
                    measured=False,
                )

        for repetition in range(1, effective.repetitions + 1):
            method_order = (
                BENCHMARK_METHODS
                if repetition % 2 == 1
                else tuple(reversed(BENCHMARK_METHODS))
            )
            for order_position, method in enumerate(method_order, start=1):
                trial = _execute_trial(
                    connection,
                    workload,
                    method,
                    repetition=repetition,
                    order_position=order_position,
                    measured=True,
                )
                if trial is None:
                    raise RuntimeError("Measured benchmark trial returned no result.")
                trials.append(trial)

    _validate_equivalent_fingerprints(trials)
    aggregates = _aggregate_trials(trials)
    comparisons = _comparisons(aggregates)
    report: dict[str, Any] = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "generated_at": _iso(datetime.now(UTC)),
        "configuration": {
            "patient_counts": list(effective.patient_counts),
            "repetitions": effective.repetitions,
            "warmups": effective.warmups,
            "seed": effective.seed,
            "reference_date": BENCHMARK_REFERENCE_DATE.isoformat(),
            "methods": list(BENCHMARK_METHODS),
            "method_order_policy": "alternating_ab_ba",
        },
        "environment": _environment_document(connection),
        "workloads": [
            {
                "patient_count": workload.patient_count,
                "seed": workload.seed,
                "row_counts": dict(workload.row_counts),
                "total_rows": workload.total_rows,
                "fingerprint": workload.fingerprint,
            }
            for workload in workloads
        ],
        "measurement_scope": {
            "included": [
                "contract row conversion",
                "driver transfer",
                "temporary staging for COPY",
                "set-based merge or executemany upsert",
                "clinical triggers and constraints",
                "transaction commit",
            ],
            "excluded": [
                "workload generation",
                "immutable raw capture",
                "contract validation",
                "full durable pipeline audit lifecycle",
                "post-load verification queries",
            ],
        },
        "trials": [asdict(trial) for trial in trials],
        "aggregates": aggregates,
        "comparisons": comparisons,
        "limitations": [
            "environment_specific",
            "shared_runner_variability",
            "initial_load_only",
            "single_writer",
            "descriptive_statistics_only",
            "no_peak_memory_claim",
        ],
    }

    report_path = output_directory / "benchmark-results.json"
    trials_csv_path = output_directory / "benchmark-trials.csv"
    summary_markdown_path = output_directory / "benchmark-summary.md"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_trial_csv(trials_csv_path, trials)
    _write_summary_markdown(summary_markdown_path, report)

    return BenchmarkArtifacts(
        report_path=report_path,
        trials_csv_path=trials_csv_path,
        summary_markdown_path=summary_markdown_path,
        patient_counts=effective.patient_counts,
        total_trials=len(trials),
        median_speedup_by_patient_count={
            int(item["patient_count"]): float(item["copy_speedup"])
            for item in comparisons
        },
    )
