from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_clinical_pilot_documents_preserve_scope_boundaries() -> None:
    pilot = (ROOT / "PILOT.md").read_text(encoding="utf-8")
    readiness = (ROOT / "docs" / "clinical-pilot-readiness.md").read_text(
        encoding="utf-8"
    )
    coverage = (ROOT / "docs" / "clinical-data-coverage.md").read_text(
        encoding="utf-8"
    )

    assert "not approved for identifiable patient data" in pilot
    assert "not a production electronic health record" in readiness
    assert "no automated clinical action" in readiness
    assert "synthetic data" in readiness
    assert "de-identified" in readiness
    assert "not a complete electronic health record" in coverage
    assert "Allergies and intolerances" in coverage
    assert "Genomics and other omics" in coverage


def test_clinical_pilot_templates_have_governance_fields() -> None:
    inventory_path = ROOT / "templates" / "clinical-pilot-data-inventory.csv"
    risk_path = ROOT / "templates" / "clinical-pilot-risk-register.csv"

    with inventory_path.open(encoding="utf-8", newline="") as handle:
        inventory_header = next(csv.reader(handle))
    with risk_path.open(encoding="utf-8", newline="") as handle:
        risk_header = next(csv.reader(handle))

    assert {
        "contains_direct_identifiers",
        "contains_free_text",
        "legal_or_ethical_approval",
        "approved_processing_location",
        "retention_period",
        "deletion_method",
    }.issubset(inventory_header)
    assert {"risk_id", "category", "risk", "mitigation", "evidence", "status"}.issubset(
        risk_header
    )


def test_documentation_index_links_pilot_material() -> None:
    index = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")

    assert "../PILOT.md" in index
    assert "clinical-pilot-readiness.md" in index
    assert "clinical-data-coverage.md" in index
    assert "clinical-pilot-data-inventory.csv" in index
    assert "clinical-pilot-risk-register.csv" in index


def test_security_policy_identifies_current_stable_release() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "Version `1.0.0` is the current stable release" in security
    assert "under active development toward `1.0.0`" not in security
