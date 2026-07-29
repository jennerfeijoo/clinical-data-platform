"""Content-addressed, append-only landing storage for source datasets."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TypedDict
from uuid import UUID, uuid4

RAW_STORAGE_VERSION = "1.0.0"
RAW_MEDIA_TYPE = "text/csv"
_DATASET_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RawLandingError(RuntimeError):
    """Base class for raw landing-zone failures."""


class RawIntegrityError(RawLandingError):
    """Raised when a raw object or receipt does not match its recorded lineage."""


class RawReceiptDocument(TypedDict):
    """Serialized fields stored in one immutable raw receipt."""

    storage_version: str
    receipt_id: str
    dataset: str
    received_at: str
    source_path: str
    source_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    object_path: str


@dataclass(frozen=True, slots=True)
class RawReceipt:
    """Verified reference to one captured source object and receipt manifest."""

    receipt_id: UUID
    dataset: str
    received_at: datetime
    source_path: str
    source_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    object_path: Path
    object_relative_path: str
    manifest_path: Path
    manifest_relative_path: str
    manifest_sha256: str
    object_created: bool


def _validate_dataset_name(dataset: str) -> None:
    if _DATASET_NAME.fullmatch(dataset) is None:
        raise RawLandingError(
            "Dataset names must start with a lowercase letter and contain only "
            "lowercase letters, digits, and underscores."
        )


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
            size_bytes += len(chunk)
    return digest.hexdigest(), size_bytes


def _relative_text(path: Path) -> str:
    return PurePosixPath(*path.parts).as_posix()


def _resolve_relative(raw_root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise RawIntegrityError(f"Unsafe raw relative path: {relative_path!r}")

    root = raw_root.resolve()
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RawIntegrityError(
            f"Raw path escapes the configured landing root: {relative_path!r}"
        ) from exc
    return candidate


def _object_relative_path(sha256: str) -> Path:
    return Path("objects") / "sha256" / sha256[:2] / sha256 / "source.csv"


def _receipt_relative_path(
    dataset: str,
    received_at: datetime,
    receipt_id: UUID,
) -> Path:
    return (
        Path("receipts")
        / dataset
        / f"{received_at.year:04d}"
        / f"{received_at.month:02d}"
        / f"{received_at.day:02d}"
        / f"{receipt_id}.json"
    )


def _make_read_only(path: Path) -> None:
    try:
        path.chmod(0o444)
    except OSError as exc:
        raise RawLandingError(f"Unable to mark raw artifact read-only: {path}") from exc


def _verify_object(path: Path, expected_sha256: str, expected_size: int) -> None:
    if not path.is_file():
        raise RawIntegrityError(f"Raw object is missing: {path}")
    actual_sha256, actual_size = _hash_file(path)
    if actual_sha256 != expected_sha256:
        raise RawIntegrityError(
            f"Raw object checksum mismatch for {path}: "
            f"expected {expected_sha256}, received {actual_sha256}."
        )
    if actual_size != expected_size:
        raise RawIntegrityError(
            f"Raw object size mismatch for {path}: "
            f"expected {expected_size}, received {actual_size}."
        )


def _copy_to_staging(
    source_path: Path,
    staging_path: Path,
    expected_sha256: str,
    expected_size: int,
) -> None:
    digest = hashlib.sha256()
    copied_size = 0
    with source_path.open("rb") as source, staging_path.open("xb") as target:
        while chunk := source.read(1024 * 1024):
            target.write(chunk)
            digest.update(chunk)
            copied_size += len(chunk)
        target.flush()
        os.fsync(target.fileno())

    if digest.hexdigest() != expected_sha256 or copied_size != expected_size:
        raise RawIntegrityError("The source changed while it was being captured.")


def _publish_staged_file(staging_path: Path, final_path: Path) -> bool:
    """Publish with an atomic hard link and never replace an existing path."""
    try:
        os.link(staging_path, final_path)
    except FileExistsError:
        return False
    except OSError as exc:
        raise RawLandingError(
            "Atomic raw publication requires hard-link support in the landing filesystem."
        ) from exc
    return True


def _create_content_object(
    source_path: Path,
    object_path: Path,
    expected_sha256: str,
    expected_size: int,
) -> bool:
    object_path.parent.mkdir(parents=True, exist_ok=True)
    if object_path.exists():
        _verify_object(object_path, expected_sha256, expected_size)
        return False

    staging_path = object_path.parent / f".{uuid4()}.staging"
    try:
        _copy_to_staging(
            source_path,
            staging_path,
            expected_sha256,
            expected_size,
        )
        created = _publish_staged_file(staging_path, object_path)
        if created:
            _make_read_only(object_path)
        else:
            _verify_object(object_path, expected_sha256, expected_size)
        return created
    finally:
        staging_path.unlink(missing_ok=True)


def _write_receipt(path: Path, document: RawReceiptDocument) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    staging_path = path.parent / f".{uuid4()}.staging"
    try:
        with staging_path.open("xb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        if not _publish_staged_file(staging_path, path):
            raise RawLandingError(
                f"Raw receipt already exists and will not be replaced: {path}"
            )
        _make_read_only(path)
    finally:
        staging_path.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def capture_raw_source(
    dataset: str,
    source_path: Path,
    raw_root: Path,
    *,
    received_at: datetime | None = None,
    receipt_id: UUID | None = None,
) -> RawReceipt:
    """Capture source bytes before parsing, without replacing existing artifacts."""
    _validate_dataset_name(dataset)
    if not source_path.exists():
        raise FileNotFoundError(f"Source dataset not found: {source_path}")
    if not source_path.is_file():
        raise RawLandingError(f"Source dataset path is not a file: {source_path}")
    if source_path.suffix.lower() != ".csv":
        raise RawLandingError(
            "The current raw landing profile accepts CSV files, received: "
            f"{source_path.suffix or '<none>'}"
        )

    effective_received_at = received_at or datetime.now(UTC)
    if effective_received_at.tzinfo is None or effective_received_at.utcoffset() is None:
        raise RawLandingError("received_at must be timezone-aware.")
    effective_received_at = effective_received_at.astimezone(UTC)
    effective_receipt_id = receipt_id or uuid4()

    source_sha256, size_bytes = _hash_file(source_path)
    object_relative = _object_relative_path(source_sha256)
    object_path = raw_root / object_relative
    object_created = _create_content_object(
        source_path,
        object_path,
        source_sha256,
        size_bytes,
    )

    receipt_relative = _receipt_relative_path(
        dataset,
        effective_received_at,
        effective_receipt_id,
    )
    receipt_path = raw_root / receipt_relative
    document = RawReceiptDocument(
        storage_version=RAW_STORAGE_VERSION,
        receipt_id=str(effective_receipt_id),
        dataset=dataset,
        received_at=effective_received_at.isoformat(),
        source_path=str(source_path.resolve()),
        source_filename=source_path.name,
        media_type=RAW_MEDIA_TYPE,
        size_bytes=size_bytes,
        sha256=source_sha256,
        object_path=_relative_text(object_relative),
    )
    manifest_sha256 = _write_receipt(receipt_path, document)

    return RawReceipt(
        receipt_id=effective_receipt_id,
        dataset=dataset,
        received_at=effective_received_at,
        source_path=document["source_path"],
        source_filename=document["source_filename"],
        media_type=RAW_MEDIA_TYPE,
        size_bytes=size_bytes,
        sha256=source_sha256,
        object_path=object_path,
        object_relative_path=document["object_path"],
        manifest_path=receipt_path,
        manifest_relative_path=_relative_text(receipt_relative),
        manifest_sha256=manifest_sha256,
        object_created=object_created,
    )


def _parse_receipt_document(raw: object) -> RawReceiptDocument:
    if not isinstance(raw, dict):
        raise RawIntegrityError("A raw receipt must contain a JSON object.")

    string_fields = (
        "storage_version",
        "receipt_id",
        "dataset",
        "received_at",
        "source_path",
        "source_filename",
        "media_type",
        "sha256",
        "object_path",
    )
    for field in string_fields:
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            raise RawIntegrityError(
                f"Raw receipt field must be a non-empty string: {field}"
            )

    size_bytes = raw.get("size_bytes")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
        raise RawIntegrityError("Raw receipt size_bytes must be a non-negative integer.")

    return RawReceiptDocument(
        storage_version=raw["storage_version"],
        receipt_id=raw["receipt_id"],
        dataset=raw["dataset"],
        received_at=raw["received_at"],
        source_path=raw["source_path"],
        source_filename=raw["source_filename"],
        media_type=raw["media_type"],
        size_bytes=size_bytes,
        sha256=raw["sha256"],
        object_path=raw["object_path"],
    )


def verify_raw_receipt(raw_root: Path, manifest_relative_path: str) -> RawReceipt:
    """Verify a receipt, its deterministic location, and its referenced object."""
    manifest_path = _resolve_relative(raw_root, manifest_relative_path)
    if not manifest_path.is_file():
        raise RawIntegrityError(f"Raw receipt is missing: {manifest_path}")

    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    try:
        raw_document = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RawIntegrityError(
            f"Raw receipt is not valid UTF-8 JSON: {manifest_path}"
        ) from exc
    document = _parse_receipt_document(raw_document)

    if document["storage_version"] != RAW_STORAGE_VERSION:
        raise RawIntegrityError(
            f"Unsupported raw storage version: {document['storage_version']!r}"
        )
    _validate_dataset_name(document["dataset"])
    if document["media_type"] != RAW_MEDIA_TYPE:
        raise RawIntegrityError(f"Unsupported raw media type: {document['media_type']!r}")
    if _SHA256.fullmatch(document["sha256"]) is None:
        raise RawIntegrityError("Raw receipt sha256 must contain 64 lowercase hex characters.")
    if Path(document["source_filename"]).name != document["source_filename"]:
        raise RawIntegrityError("source_filename must not contain directory components.")

    try:
        parsed_receipt_id = UUID(document["receipt_id"])
        parsed_received_at = datetime.fromisoformat(document["received_at"])
    except ValueError as exc:
        raise RawIntegrityError("Raw receipt contains an invalid UUID or datetime.") from exc
    if parsed_received_at.tzinfo is None or parsed_received_at.utcoffset() is None:
        raise RawIntegrityError("Raw receipt received_at must be timezone-aware.")
    parsed_received_at = parsed_received_at.astimezone(UTC)

    expected_manifest_relative = _relative_text(
        _receipt_relative_path(
            document["dataset"],
            parsed_received_at,
            parsed_receipt_id,
        )
    )
    if manifest_relative_path != expected_manifest_relative:
        raise RawIntegrityError(
            "Raw receipt path does not match its dataset, date, and receipt identifier."
        )

    expected_object_relative = _relative_text(_object_relative_path(document["sha256"]))
    if document["object_path"] != expected_object_relative:
        raise RawIntegrityError("Raw object path is not the deterministic content address.")
    object_path = _resolve_relative(raw_root, document["object_path"])
    _verify_object(object_path, document["sha256"], document["size_bytes"])

    return RawReceipt(
        receipt_id=parsed_receipt_id,
        dataset=document["dataset"],
        received_at=parsed_received_at,
        source_path=document["source_path"],
        source_filename=document["source_filename"],
        media_type=document["media_type"],
        size_bytes=document["size_bytes"],
        sha256=document["sha256"],
        object_path=object_path,
        object_relative_path=document["object_path"],
        manifest_path=manifest_path,
        manifest_relative_path=manifest_relative_path,
        manifest_sha256=manifest_sha256,
        object_created=False,
    )
