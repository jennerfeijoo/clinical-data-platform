"""Command-line interface for the clinical data platform."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from clinical_data_platform.database import (
    apply_schema,
    connect_database,
    database_url_from_environment,
    persist_patient_validation_outputs,
)
from clinical_data_platform.pipeline import run_patient_validation


def _iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected an ISO date in YYYY-MM-DD format") from exc


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
    validate_patients.add_argument("input", type=Path, help="Path to the source patient CSV.")
    validate_patients.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/patients"),
        help="Directory for valid, invalid, error, and quality-report outputs.",
    )
    validate_patients.add_argument(
        "--reference-date",
        type=_iso_date,
        default=None,
        help="Reference date for future-date validation (YYYY-MM-DD).",
    )

    load_patients = subparsers.add_parser(
        "load-patients",
        help="Load patient validation outputs into PostgreSQL.",
    )
    load_patients.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/patients"),
        help="Directory containing patient validation outputs.",
    )
    load_patients.add_argument(
        "--schema",
        type=Path,
        default=Path("sql/schema.sql"),
        help="PostgreSQL schema file to apply before loading data.",
    )
    load_patients.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL connection URL. Defaults to the DATABASE_URL environment variable.",
    )
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
        print(f"Quality report: {validation_summary.quality_report_path}")
        return 0

    if args.command == "load-patients":
        database_url = args.database_url or database_url_from_environment()
        with connect_database(database_url) as connection:
            apply_schema(connection, args.schema)
            persistence_summary = persist_patient_validation_outputs(
                connection,
                args.output_dir,
            )

        if persistence_summary.already_loaded:
            print(f"Validation run already loaded: run_id={persistence_summary.run_id}")
        else:
            print(
                "Patient persistence completed: "
                f"run_id={persistence_summary.run_id}, "
                f"patients={persistence_summary.patients_upserted}, "
                f"errors={persistence_summary.validation_errors_inserted}"
            )
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2
