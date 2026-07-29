"""Command-line interface for the clinical data platform."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from clinical_data_platform.cohort import build_hypertension_cohort
from clinical_data_platform.database import (
    apply_schema,
    connect_database,
    database_url_from_environment,
    persist_patient_validation_outputs,
)
from clinical_data_platform.demo import run_demo
from clinical_data_platform.entity_database import persist_entity_validation_outputs
from clinical_data_platform.entity_pipeline import DATASET_CONFIGURATION, run_entity_validation
from clinical_data_platform.pipeline import run_patient_validation


def _iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected an ISO date in YYYY-MM-DD format") from exc


def _database_url(explicit_value: str | None) -> str:
    return explicit_value or database_url_from_environment()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clinical-data",
        description="Run reproducible workflows for synthetic clinical data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_patients = subparsers.add_parser(
        "validate-patients",
        help="Validate a patient CSV file and write quality outputs.",
    )
    validate_patients.add_argument("input", type=Path)
    validate_patients.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/patients"),
    )
    validate_patients.add_argument("--reference-date", type=_iso_date, default=None)

    load_patients = subparsers.add_parser(
        "load-patients",
        help="Load patient validation outputs into PostgreSQL.",
    )
    load_patients.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/patients"),
    )
    load_patients.add_argument(
        "--schema",
        type=Path,
        default=Path("sql/schema.sql"),
    )
    load_patients.add_argument("--database-url", default=None)

    validate_entity = subparsers.add_parser(
        "validate-entity",
        help="Validate encounters, diagnoses, or observations.",
    )
    validate_entity.add_argument("dataset", choices=sorted(DATASET_CONFIGURATION))
    validate_entity.add_argument("input", type=Path)
    validate_entity.add_argument("--output-dir", type=Path, required=True)
    validate_entity.add_argument("--reference-date", type=_iso_date, default=None)

    load_entity = subparsers.add_parser(
        "load-entity",
        help="Load validated encounters, diagnoses, or observations.",
    )
    load_entity.add_argument("dataset", choices=sorted(DATASET_CONFIGURATION))
    load_entity.add_argument("--output-dir", type=Path, required=True)
    load_entity.add_argument(
        "--schema",
        type=Path,
        default=Path("sql/schema.sql"),
    )
    load_entity.add_argument("--database-url", default=None)

    build_cohort = subparsers.add_parser(
        "build-hypertension-cohort",
        help="Build and export the versioned hypertension feature cohort.",
    )
    build_cohort.add_argument(
        "--sql",
        type=Path,
        default=Path("sql/cohorts/hypertension.sql"),
    )
    build_cohort.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/analytics"),
    )
    build_cohort.add_argument("--minimum-age", type=int, default=18)
    build_cohort.add_argument("--minimum-follow-up-days", type=int, default=30)
    build_cohort.add_argument("--baseline-window-days", type=int, default=30)
    build_cohort.add_argument("--database-url", default=None)

    demo = subparsers.add_parser(
        "run-demo",
        help="Run validation, persistence, cohort construction, and feature export.",
    )
    demo.add_argument("--repository-root", type=Path, default=Path("."))
    demo.add_argument("--reference-date", type=_iso_date, default=date(2026, 7, 29))
    demo.add_argument("--database-url", default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-patients":
        validation_summary = run_patient_validation(
            args.input,
            args.output_dir,
            reference_date=args.reference_date,
        )
        print(
            "Patient validation completed: "
            f"run_id={validation_summary.run_id}, "
            f"received={validation_summary.rows_received}, "
            f"valid={validation_summary.rows_valid}, "
            f"invalid={validation_summary.rows_invalid}, "
            f"errors={validation_summary.validation_errors}"
        )
        return 0

    if args.command == "load-patients":
        with connect_database(_database_url(args.database_url)) as connection:
            apply_schema(connection, args.schema)
            patient_persistence = persist_patient_validation_outputs(
                connection,
                args.output_dir,
            )
        print(
            "Patient persistence completed: "
            f"run_id={patient_persistence.run_id}, "
            f"already_loaded={patient_persistence.already_loaded}, "
            f"patients={patient_persistence.patients_upserted}, "
            f"errors={patient_persistence.validation_errors_inserted}"
        )
        return 0

    if args.command == "validate-entity":
        entity_validation = run_entity_validation(
            args.dataset,
            args.input,
            args.output_dir,
            reference_date=args.reference_date,
        )
        print(
            f"{entity_validation.dataset} validation completed: "
            f"run_id={entity_validation.run_id}, "
            f"received={entity_validation.rows_received}, "
            f"valid={entity_validation.rows_valid}, "
            f"invalid={entity_validation.rows_invalid}, "
            f"errors={entity_validation.validation_errors}"
        )
        return 0

    if args.command == "load-entity":
        with connect_database(_database_url(args.database_url)) as connection:
            apply_schema(connection, args.schema)
            entity_persistence = persist_entity_validation_outputs(
                connection,
                args.dataset,
                args.output_dir,
            )
        print(
            f"{entity_persistence.dataset} persistence completed: "
            f"run_id={entity_persistence.run_id}, "
            f"already_loaded={entity_persistence.already_loaded}, "
            f"records={entity_persistence.records_upserted}, "
            f"errors={entity_persistence.validation_errors_inserted}"
        )
        return 0

    if args.command == "build-hypertension-cohort":
        with connect_database(_database_url(args.database_url)) as connection:
            cohort_summary = build_hypertension_cohort(
                connection,
                args.sql,
                args.output_dir,
                minimum_age=args.minimum_age,
                minimum_follow_up_days=args.minimum_follow_up_days,
                baseline_window_days=args.baseline_window_days,
            )
        print(
            "Hypertension cohort completed: "
            f"cohort_run_id={cohort_summary.cohort_run_id}, "
            f"rows={cohort_summary.row_count}, "
            f"features={cohort_summary.features_path}"
        )
        return 0

    if args.command == "run-demo":
        demo_summary = run_demo(
            args.repository_root.resolve(),
            _database_url(args.database_url),
            reference_date=args.reference_date,
        )
        print(
            "Demo completed: "
            f"patient_run_id={demo_summary.patient_run_id}, "
            f"cohort_run_id={demo_summary.cohort.cohort_run_id}, "
            f"cohort_rows={demo_summary.cohort.row_count}"
        )
        print(f"Feature output: {demo_summary.cohort.features_path}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2
