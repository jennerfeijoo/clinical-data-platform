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
    connect_database,
    database_url_from_environment,
    persist_dataset_validation_outputs,
)
from clinical_data_platform.demo import run_demo
from clinical_data_platform.migration import (
    migrate_database,
    migration_status,
    validate_database_migrations,
)
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.raw import capture_raw_source, verify_raw_receipt
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


def _default_raw_root() -> Path:
    return Path("data") / "raw"


def _add_database_url(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database-url", default=None)


def _add_baseline_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--baseline-existing",
        action="store_true",
        help=(
            "Adopt a recognized pre-migration schema after explicit review. "
            "Do not use for unknown or partially modified databases."
        ),
    )


def _add_raw_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=_default_raw_root(),
        help="Root directory for immutable content objects and receipt manifests.",
    )


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

    capture_raw = subparsers.add_parser(
        "raw-capture",
        help="Capture one CSV source into immutable content-addressed storage.",
    )
    capture_raw.add_argument("dataset", choices=supported_datasets)
    capture_raw.add_argument("input", type=Path)
    _add_raw_root(capture_raw)

    verify_raw = subparsers.add_parser(
        "raw-verify",
        help="Verify a receipt manifest and the content object it references.",
    )
    verify_raw.add_argument("manifest", help="Receipt path relative to --raw-root.")
    _add_raw_root(verify_raw)

    migrate = subparsers.add_parser(
        "database-migrate",
        help="Apply packaged PostgreSQL migrations in version order.",
    )
    migrate.add_argument("--target-version", type=int, default=None)
    _add_baseline_flag(migrate)
    _add_database_url(migrate)

    status = subparsers.add_parser(
        "database-status",
        help="Show applied, detected, and pending database migration versions.",
    )
    _add_database_url(status)

    validate_database = subparsers.add_parser(
        "database-validate",
        help="Validate migration history, checksums, and database currentness.",
    )
    _add_database_url(validate_database)

    validate_dataset = subparsers.add_parser(
        "validate-dataset",
        help="Capture and validate any registered dataset and write quality outputs.",
    )
    validate_dataset.add_argument("dataset", choices=supported_datasets)
    validate_dataset.add_argument("input", type=Path)
    validate_dataset.add_argument("--output-dir", type=Path, default=None)
    validate_dataset.add_argument("--reference-date", type=_iso_date, default=None)
    _add_raw_root(validate_dataset)

    load_dataset = subparsers.add_parser(
        "load-dataset",
        help="Verify raw lineage, migrate PostgreSQL, and load validated data.",
    )
    load_dataset.add_argument("dataset", choices=supported_datasets)
    load_dataset.add_argument("--output-dir", type=Path, default=None)
    _add_raw_root(load_dataset)
    _add_baseline_flag(load_dataset)
    _add_database_url(load_dataset)

    build_cohort = subparsers.add_parser(
        "build-hypertension-cohort",
        help="Migrate PostgreSQL and build the versioned hypertension feature cohort.",
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
    _add_baseline_flag(build_cohort)
    _add_database_url(build_cohort)

    demo = subparsers.add_parser(
        "run-demo",
        help="Run raw capture, migrations, validation, persistence, cohort, and export.",
    )
    demo.add_argument("--repository-root", type=Path, default=Path("."))
    demo.add_argument("--reference-date", type=_iso_date, default=date(2026, 7, 29))
    _add_baseline_flag(demo)
    _add_database_url(demo)

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

    if args.command == "raw-capture":
        receipt = capture_raw_source(args.dataset, args.input, args.raw_root)
        print(
            "Raw capture completed: "
            f"receipt_id={receipt.receipt_id}, "
            f"sha256={receipt.sha256}, size={receipt.size_bytes}, "
            f"object_created={receipt.object_created}, "
            f"manifest={receipt.manifest_relative_path}, "
            f"object={receipt.object_relative_path}"
        )
        return 0

    if args.command == "raw-verify":
        receipt = verify_raw_receipt(args.raw_root, args.manifest)
        print(
            "Raw receipt verified: "
            f"receipt_id={receipt.receipt_id}, dataset={receipt.dataset}, "
            f"sha256={receipt.sha256}, size={receipt.size_bytes}, "
            f"manifest_sha256={receipt.manifest_sha256}"
        )
        return 0

    if args.command == "database-migrate":
        with connect_database(_database_url(args.database_url)) as connection:
            summary = migrate_database(
                connection,
                target_version=args.target_version,
                baseline_existing=args.baseline_existing,
            )
        print(
            "Database migration completed: "
            f"previous={summary.previous_version}, "
            f"current={summary.current_version}, "
            f"target={summary.target_version}, "
            f"baselined={list(summary.baselined_versions)}, "
            f"applied={list(summary.applied_versions)}"
        )
        return 0

    if args.command == "database-status":
        with connect_database(_database_url(args.database_url)) as connection:
            status = migration_status(connection)
        print(
            "Database migration status: "
            f"managed={status.managed}, "
            f"detected={status.detected_schema_version}, "
            f"current={status.current_version}, "
            f"latest={status.latest_version}, "
            f"pending={[item.version for item in status.pending]}"
        )
        for record in status.applied:
            print(
                f"V{record.version:03d} {record.name} "
                f"type={record.execution_type} checksum={record.checksum}"
            )
        return 0

    if args.command == "database-validate":
        with connect_database(_database_url(args.database_url)) as connection:
            status = validate_database_migrations(connection)
        print(
            f"Database migration history is valid at V{status.current_version:03d}; "
            f"latest=V{status.latest_version:03d}."
        )
        return 0

    if args.command == "validate-dataset":
        output_directory = args.output_dir or _default_output_directory(args.dataset)
        summary = run_dataset_validation(
            args.dataset,
            args.input,
            output_directory,
            raw_root=args.raw_root,
            reference_date=args.reference_date,
        )
        print(
            f"{summary.dataset} validation completed: "
            f"run_id={summary.run_id}, raw_receipt_id={summary.raw_receipt_id}, "
            f"contract={summary.contract_version}, received={summary.rows_received}, "
            f"valid={summary.rows_valid}, invalid={summary.rows_invalid}, "
            f"errors={summary.validation_errors}"
        )
        return 0

    if args.command == "load-dataset":
        output_directory = args.output_dir or _default_output_directory(args.dataset)
        with connect_database(_database_url(args.database_url)) as connection:
            migrate_database(connection, baseline_existing=args.baseline_existing)
            summary = persist_dataset_validation_outputs(
                connection,
                args.dataset,
                output_directory,
                raw_root=args.raw_root,
            )
        print(
            f"{summary.dataset} persistence completed: "
            f"run_id={summary.run_id}, contract={summary.contract_version}, "
            f"already_loaded={summary.already_loaded}, "
            f"records={summary.records_upserted}, "
            f"errors={summary.validation_errors_inserted}"
        )
        return 0

    if args.command == "build-hypertension-cohort":
        with connect_database(_database_url(args.database_url)) as connection:
            migrate_database(connection, baseline_existing=args.baseline_existing)
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
            baseline_existing=args.baseline_existing,
        )
        print(
            "Demo completed: "
            f"patient_run_id={demo_summary.patient_run_id}, "
            f"patient_raw_receipt_id={demo_summary.raw_receipt_ids['patients']}, "
            f"cohort_run_id={demo_summary.cohort.cohort_run_id}, "
            f"cohort_rows={demo_summary.cohort.row_count}"
        )
        print(f"Feature output: {demo_summary.cohort.features_path}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2
