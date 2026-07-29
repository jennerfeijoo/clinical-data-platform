"""Inspection and validation helpers for the local terminology subset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg


class TerminologyStateError(RuntimeError):
    """Raised when database terminology bindings are incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class TerminologySystem:
    """One locally registered code-system subset."""

    code_system_id: str
    canonical_uri: str
    display_name: str
    authority: str
    upstream_version: str | None
    subset_version: str
    complete_release: bool


@dataclass(frozen=True, slots=True)
class TerminologyConcept:
    """One normalized terminology concept resolved from a source code."""

    concept_id: int
    code_system_id: str
    canonical_uri: str
    code: str
    display: str
    domain: str
    active: bool
    verification_status: str


@dataclass(frozen=True, slots=True)
class TerminologyValidationSummary:
    """Counts produced by validating the installed terminology layer."""

    code_systems: int
    concepts: int
    mappings: int
    normalized_clinical_rows: int
    invalid_bindings: int


def list_terminology_systems(
    connection: psycopg.Connection[Any],
) -> tuple[TerminologySystem, ...]:
    """Return registered code systems in deterministic order."""
    rows = connection.execute(
        """
        SELECT
            code_system_id,
            canonical_uri,
            display_name,
            authority,
            upstream_version,
            subset_version,
            complete_release
        FROM terminology.code_systems
        ORDER BY code_system_id
        """
    ).fetchall()
    return tuple(
        TerminologySystem(
            code_system_id=str(row[0]),
            canonical_uri=str(row[1]),
            display_name=str(row[2]),
            authority=str(row[3]),
            upstream_version=str(row[4]) if row[4] is not None else None,
            subset_version=str(row[5]),
            complete_release=bool(row[6]),
        )
        for row in rows
    )


def resolve_terminology_concept(
    connection: psycopg.Connection[Any],
    source_system: str,
    source_code: str,
    expected_domain: str,
) -> TerminologyConcept:
    """Resolve a source code through aliases and optional concept mappings."""
    row = connection.execute(
        """
        SELECT
            concept.concept_id,
            concept.code_system_id,
            system.canonical_uri,
            concept.code,
            concept.display,
            concept.domain,
            concept.active,
            concept.verification_status
        FROM terminology.concepts AS concept
        JOIN terminology.code_systems AS system
          ON system.code_system_id = concept.code_system_id
        WHERE concept.concept_id = terminology.resolve_concept(%s, %s, %s)
        """,
        (source_system, source_code, expected_domain),
    ).fetchone()
    if row is None:
        raise TerminologyStateError(
            f"Resolver returned no concept for {source_system}:{source_code}."
        )
    return TerminologyConcept(
        concept_id=int(row[0]),
        code_system_id=str(row[1]),
        canonical_uri=str(row[2]),
        code=str(row[3]),
        display=str(row[4]),
        domain=str(row[5]),
        active=bool(row[6]),
        verification_status=str(row[7]),
    )


def validate_terminology_bindings(
    connection: psycopg.Connection[Any],
) -> TerminologyValidationSummary:
    """Verify every coded clinical row resolves to an active concept in its domain."""
    count_row = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM terminology.code_systems),
            (SELECT COUNT(*) FROM terminology.concepts),
            (SELECT COUNT(*) FROM terminology.concept_mappings),
            (SELECT COUNT(*) FROM terminology.normalized_clinical_codes)
        """
    ).fetchone()
    if count_row is None:
        raise TerminologyStateError("Terminology count query returned no row.")

    invalid_row = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT diagnosis.normalized_concept_id, 'condition'::TEXT AS expected_domain
            FROM clinical.diagnoses AS diagnosis
            UNION ALL
            SELECT observation.normalized_concept_id, 'observation'
            FROM clinical.observations AS observation
            UNION ALL
            SELECT medication.normalized_concept_id, 'medication'
            FROM clinical.medications AS medication
            UNION ALL
            SELECT procedure.normalized_concept_id, 'procedure'
            FROM clinical.procedures AS procedure
        ) AS binding
        LEFT JOIN terminology.concepts AS concept
          ON concept.concept_id = binding.normalized_concept_id
        WHERE concept.concept_id IS NULL
           OR NOT concept.active
           OR concept.domain <> binding.expected_domain
        """
    ).fetchone()
    invalid = int(invalid_row[0]) if invalid_row is not None else 1
    summary = TerminologyValidationSummary(
        code_systems=int(count_row[0]),
        concepts=int(count_row[1]),
        mappings=int(count_row[2]),
        normalized_clinical_rows=int(count_row[3]),
        invalid_bindings=invalid,
    )
    if summary.invalid_bindings:
        raise TerminologyStateError(
            f"Terminology validation found {summary.invalid_bindings} invalid bindings."
        )
    return summary
