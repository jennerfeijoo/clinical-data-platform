from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from clinical_data_platform.raw import (
    RawIntegrityError,
    RawLandingError,
    capture_raw_source,
    verify_raw_receipt,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATIENTS = REPOSITORY_ROOT / "data" / "sample" / "patients.csv"
RECEIVED_AT = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
RECEIPT_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_raw_capture_creates_verifiable_content_object_and_receipt(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"

    receipt = capture_raw_source(
        "patients",
        SAMPLE_PATIENTS,
        raw_root,
        received_at=RECEIVED_AT,
        receipt_id=RECEIPT_ID,
    )
    verified = verify_raw_receipt(raw_root, receipt.manifest_relative_path)

    assert receipt.object_created is True
    assert receipt.object_path.read_bytes() == SAMPLE_PATIENTS.read_bytes()
    assert verified.receipt_id == RECEIPT_ID
    assert verified.dataset == "patients"
    assert verified.sha256 == receipt.sha256
    assert verified.manifest_sha256 == receipt.manifest_sha256
    assert verified.object_relative_path.startswith("objects/sha256/")
    assert verified.manifest_relative_path == (
        "receipts/patients/2026/07/29/11111111-1111-4111-8111-111111111111.json"
    )


def test_identical_content_is_deduplicated_but_receipts_are_append_only(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"

    first = capture_raw_source("patients", SAMPLE_PATIENTS, raw_root)
    second = capture_raw_source("patients", SAMPLE_PATIENTS, raw_root)

    assert first.object_created is True
    assert second.object_created is False
    assert first.object_path == second.object_path
    assert first.receipt_id != second.receipt_id
    assert first.manifest_path != second.manifest_path


def test_existing_receipt_is_never_replaced(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    first = capture_raw_source(
        "patients",
        SAMPLE_PATIENTS,
        raw_root,
        received_at=RECEIVED_AT,
        receipt_id=RECEIPT_ID,
    )
    original_manifest = first.manifest_path.read_bytes()

    with pytest.raises(RawLandingError, match="will not be replaced"):
        capture_raw_source(
            "patients",
            SAMPLE_PATIENTS,
            raw_root,
            received_at=RECEIVED_AT,
            receipt_id=RECEIPT_ID,
        )

    assert first.manifest_path.read_bytes() == original_manifest


def test_corrupted_content_object_is_detected(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    receipt = capture_raw_source("patients", SAMPLE_PATIENTS, raw_root)
    receipt.object_path.chmod(0o644)
    receipt.object_path.write_text("corrupted\n", encoding="utf-8")

    with pytest.raises(RawIntegrityError, match="checksum mismatch"):
        verify_raw_receipt(raw_root, receipt.manifest_relative_path)


def test_raw_verification_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(RawIntegrityError, match="Unsafe raw relative path"):
        verify_raw_receipt(tmp_path, "../receipt.json")
