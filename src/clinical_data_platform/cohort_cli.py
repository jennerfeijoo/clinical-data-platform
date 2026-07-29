"""Console commands for independent reproducible Synthea cohorts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from clinical_data_platform.database import (
    connect_database,
    database_url_from_environment,
)
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.synthea import (
    adapt_synthea_csv,
    generate_synthea_dataset,
    synthea_profile_document,
    verify_synthea_adaptation,
)
from clinical_data_platform.synthea_cohorts import (
    DEFAULT_COHORT_A_PROFILE,
    DEFAULT_COHORT_B_PROFILE,
    compare_synthea_cohorts,
    load_packaged_synthea_profile,
    load_synthea_cohort_pair,
    packaged_synthea_profile_names,
)


def _add_profile_name(parser: argparse.ArgumentParser, argument: str = "profile_name") -> None:
    parser.add_argument(argument, choices=packaged_synthea_profile_names())


def _add_pair_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("cohort_a_directory", type=Path)
    parser.add_argument("cohort_b_directory", type=Path)
    parser.add_argument(
        "--cohort-a-profile",
        choices=packaged_synthea_profile_names(),
        default=DEFAULT_COHORT_A_PROFILE,
    )
    parser.add_argument(
        "--cohort-b-profile",
        choices=packaged_synthea_profile_names(),
        default=DEFAULT_COHORT_B_PROFILE,
    )
    parser.add_argument("--cohort-a-label", default="cohort_a")
    parser.add_argument("--cohort-b-label", default="cohort_b")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/synthea/cohort-comparison"),
    )
    parser.add_argument("--replace", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clinical-data-cohort",
        description=(
            "Generate, verify, compare, and load independent matched-design "
            "Synthea cohorts."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "list-profiles",
        help="List packaged Synthea cohort profiles.",
    )

    profile = subparsers.add_parser(
        "profile",
        help="Display one packaged Synthea profile as JSON.",
    )
    _add_profile_name(profile)

    generate = subparsers.add_parser(
        "generate",
        help="Generate source CSV files from one packaged pinned profile.",
    )
    _add_profile_name(generate)
    generate.add_argument("--workspace", type=Path, default=None)
    generate.add_argument("--checkout", type=Path, default=None)
    generate.add_argument("--replace", action="store_true")

    adapt = subparsers.add_parser(
        "adapt",
        help="Adapt one generated cohort into the six executable contracts.",
    )
    _add_profile_name(adapt)
    adapt.add_argument("csv_directory", type=Path)
    adapt.add_argument("--output-dir", type=Path, default=None)
    adapt.add_argument("--generation-manifest", type=Path, default=None)
    adapt.add_argument("--replace", action="store_true")

    verify = subparsers.add_parser(
        "verify",
        help="Verify one adapted cohort against its packaged profile.",
    )
    _add_profile_name(verify)
    verify.add_argument("normalized_directory", type=Path)

    compare = subparsers.add_parser(
        "compare",
        help="Verify two matched-design cohorts and prove identifier disjointness.",
    )
    _add_pair_arguments(compare)

    load_pair = subparsers.add_parser(
        "load-pair",
        help="Compare and load both cohorts with separate processing lineage.",
    )
    _add_pair_arguments(load_pair)
    load_pair.add_argument(
        "--processed-root",
        type=Path,
        default=Path("data/processed/synthea-cohorts"),
    )
    load_pair.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    load_pair.add_argument("--database-url", default=None)
    load_pair.add_argument("--baseline-existing", action="store_true")

    return parser


def _workspace_for_profile(profile_name: str) -> Path:
    return Path("data") / "synthea" / profile_name


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list-profiles":
        for profile_name in packaged_synthea_profile_names():
            profile = load_packaged_synthea_profile(profile_name)
            print(
                f"{profile.name}: population={profile.population_size}, "
                f"seed={profile.random_seed}, clinician_seed={profile.clinician_seed}, "
                f"reference_date={profile.reference_date.isoformat()}, "
                f"sha256={profile.sha256}"
            )
        return 0

    if args.command == "profile":
        selected = load_packaged_synthea_profile(args.profile_name)
        print(json.dumps(synthea_profile_document(selected), indent=2, sort_keys=True))
        return 0

    if args.command == "generate":
        selected = load_packaged_synthea_profile(args.profile_name)
        workspace = args.workspace or _workspace_for_profile(selected.name)
        summary = generate_synthea_dataset(
            workspace,
            profile=selected,
            checkout_directory=args.checkout,
            replace=args.replace,
        )
        print(
            "Synthea cohort generation completed: "
            f"profile={summary.profile_name}, "
            f"upstream_commit={summary.upstream_commit}, "
            f"fingerprint={summary.dataset_fingerprint}, "
            f"manifest={summary.manifest_path}"
        )
        return 0

    if args.command == "adapt":
        selected = load_packaged_synthea_profile(args.profile_name)
        output_directory = args.output_dir or (
            _workspace_for_profile(selected.name) / "normalized"
        )
        summary = adapt_synthea_csv(
            args.csv_directory,
            output_directory,
            profile=selected,
            generation_manifest_path=args.generation_manifest,
            replace=args.replace,
        )
        print(
            "Synthea cohort adaptation completed: "
            f"profile={summary.profile_name}, rows={summary.dataset_rows}, "
            f"omitted={summary.omitted_rows}, "
            f"fingerprint={summary.adaptation_fingerprint}"
        )
        return 0

    if args.command == "verify":
        selected = load_packaged_synthea_profile(args.profile_name)
        summary = verify_synthea_adaptation(
            args.normalized_directory,
            profile=selected,
        )
        print(
            "Synthea cohort verified: "
            f"profile={summary.profile_name}, rows={summary.dataset_rows}, "
            f"fingerprint={summary.adaptation_fingerprint}"
        )
        return 0

    if args.command == "compare":
        summary = compare_synthea_cohorts(
            args.cohort_a_directory,
            args.cohort_b_directory,
            args.output_dir,
            cohort_a_profile_name=args.cohort_a_profile,
            cohort_b_profile_name=args.cohort_b_profile,
            cohort_a_label=args.cohort_a_label,
            cohort_b_label=args.cohort_b_label,
            replace=args.replace,
        )
        print(
            "Synthea cohort comparison completed: "
            f"fingerprint={summary.comparison_fingerprint}, "
            f"overlaps={summary.overlap_counts}, "
            f"manifest={summary.manifest_path}"
        )
        return 0

    if args.command == "load-pair":
        database_url = args.database_url or database_url_from_environment()
        with connect_database(database_url) as connection:
            migrate_database(connection, baseline_existing=args.baseline_existing)
            summary = load_synthea_cohort_pair(
                connection,
                args.cohort_a_directory,
                args.cohort_b_directory,
                args.processed_root,
                args.output_dir,
                raw_root=args.raw_root,
                cohort_a_profile_name=args.cohort_a_profile,
                cohort_b_profile_name=args.cohort_b_profile,
                cohort_a_label=args.cohort_a_label,
                cohort_b_label=args.cohort_b_label,
                replace_comparison=args.replace,
            )
        print(
            "Synthea cohort pair loaded: "
            f"comparison={summary.comparison.comparison_fingerprint}, "
            f"cohort_a_records={summary.cohort_a_load.records_persisted}, "
            f"cohort_b_records={summary.cohort_b_load.records_persisted}, "
            f"load_manifest={summary.load_manifest_path}"
        )
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
