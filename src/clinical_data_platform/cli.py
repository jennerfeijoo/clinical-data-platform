"""Command-line interface for the clinical data platform."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from clinical_data_platform.cohort import build_hypertension_cohort
from clinical_data_platform.contract import load_contract, validate_all_contracts
from clinical_data_platform.database import (
    apply_schema,
    connect_database,
    database_url_from_environment,
    persist_dataset_validation_outputs,
)
from clinical_data_platform.demo import run_demo
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.registry import dataset_names


def _iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected an ISO date in YYYY-MM-DD format") from exc


def _database_url(explicit_value: str | None) -> str:
    return explicit_value or database_url_from_environment()


def _default_output_directory(dataset: str) -> Path:
    return Path("data") / "processed" / dataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clinical-data",
        description="Run reproducible workflows for synthetic clinical data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    supported_datasets = dataset_names()

    subparsers.add_parser(
        "list-contracts",
        help="List active dataset contract versions selected by the manifest.",
    )

    show_contract = subparsers.add_parser(
        "show-contract",
        help="Display one active executable contract as JSON.",
    )
    show_contract.add_argument("dataset", choices=supported_datasets)

    subparsers.add_parser(
        "validate-contracts",
        help="Load and validate every active contract definition.",
    )

    validate_dataset = subparsers.add_parser(
        "validate-dataset",
        help="Validate any registered dataset and write quality outputs.",
    )
    validate_dataset.add_argument("dataset", choices=supported_datasets)
    validate_dataset.add_argument("input", type=Path)
    validate_dataset.add_argument("--output-dir", type=Path, default=None)
    validate_dataset.add_argument("--reference-date", type=_iso_date, default=None)

    load_dataset = subparsers.add_parser(
        "load-dataset",
        help="Load any registered dataset validation output into PostgreSQL.",
    )
    load_dataset.add_argument("dataset", choices=supported_datasets)
    load_dataset.add_argument("--output-dir", type=Path, default=None)
    load_dataset.add_argument(
        "--schema",
        type=Path,
        default=Path("sql/schema.sql"),
    )
    load_dataset.add_argument("--database-url", default=None)

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


def _contract_document(dataset: str) -> dict[str, object]:
    contract = load_contract(dataset)
    measurement = contract.measurement_rule
    return {
        "name": contract.name,
        "version": contract.version,
        "resource_path": contract.resource_path,
        "sha256": contract.sha256,
        "primary_key": contract.primary_key,
        "patient_id_column": contract.patient_id_column,
        "allow_extra_columns": contract.allow_extra_columns,
        "columns": [
            {
                "name": column.name,
                "type": column.data_type,
                "required": column.required,
                "unique": column.unique,
                "allowed_values": list(column.allowed_values),
            }
            for column in contract.columns
        ],
        "not_future_fields": list(contract.not_future_fields),
        "order_rules": [
            {
                "earlier_field": rule.earlier_field,
                "later_field": rule.later_field,
            }
            for rule in contract.order_rules
        ],
        "measurement_profiles": (
            [
                {
                    "code": profile.code,
                    "unit": profile.unit,
                    "minimum": profile.minimum,
                    "maximum": profile.maximum,
                }
                for profile in measurement.profiles.values()
            ]
            if measurement is not None
            else []
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list-contracts":
        for dataset in dataset_names():
            contract = load_contract(dataset)
            print(
                f"{dataset}: version={contract.version}, "
                f"sha256={contract.sha256}, path={contract.resource_path}"
            )
        return 0

    if args.command == "show-contract":
        print(json.dumps(_contract_document(args.dataset), indent=2, sort_keys=True))
        return 0

    if args.command == "validate-contracts":
        contracts = validate_all_contracts()
        print(f"Validated {len(contracts)} active contracts.")
        for contract in contracts:
            print(f"{contract.name} {contract.version} {contract.sha256}")
        return 0

    if args.command == "validate-dataset":
        output_directory = args.output_dir or _default_output_directory(args.dataset)
        validation_summary = run_dataset_validation(
            args.dataset,
            args.input,
            output_directory,
            reference_date=args.reference_date,
        )
        print(
            f"{validation_summary.dataset} validation completed: "
            f"run_id={validation_summary.run_id}, "
            f"contract={validation_summary.contract_version}, "
            f"received={validation_summary.rows_received}, "
            f"valid={validation_summary.rows_valid}, "
            f"invalid={validation_summary.rows_invalid}, "
            f"errors={validation_summary.validation_errors}"
        )
        return 0

    if args.command == "load-dataset":
        output_directory = args.output_dir or _default_output_directory(args.dataset)
        with connect_database(_database_url(args.database_url)) as connection:
            apply_schema(connection, args.schema)
            persistence_summary = persist_dataset_validation_outputs(
                connection,
                args.dataset,
                output_directory,
            )
        print(
            f"{persistence_summary.dataset} persistence completed: "
            f"run_id={persistence_summary.run_id}, "
            f"contract={persistence_summary.contract_version}, "
            f"already_loaded={persistence_summary.already_loaded}, "
            f"records={persistence_summary.records_upserted}, "
            f"errors={persistence_summary.validation_errors_inserted}"
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
