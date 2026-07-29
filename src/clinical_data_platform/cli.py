"""Command-line interface for the clinical data platform."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-patients":
        summary = run_patient_validation(
            args.input,
            args.output_dir,
            reference_date=args.reference_date,
        )
        print(
            "Patient validation completed: "
            f"received={summary.rows_received}, "
            f"valid={summary.rows_valid}, "
            f"invalid={summary.rows_invalid}, "
            f"errors={summary.validation_errors}"
        )
        print(f"Quality report: {summary.quality_report_path}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2
