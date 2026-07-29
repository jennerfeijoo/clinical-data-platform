import json
import logging
import sys
from datetime import date
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest

from clinical_data_platform import entrypoint
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.structured_logging import (
    LOG_SCHEMA_VERSION,
    bind_log_context,
    configure_logging,
    current_log_context,
    emit_log,
    get_logger,
    log_operation,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATIENTS = REPOSITORY_ROOT / "data" / "sample" / "patients.csv"


def _documents(stream: StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def test_json_log_contains_stable_schema_context_and_redaction() -> None:
    stream = StringIO()
    configuration = configure_logging(
        level="INFO",
        output_format="json",
        stream=stream,
    )
    logger = get_logger("test_component")

    with bind_log_context(
        correlation_id="corr-001",
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
        dataset="patients",
        patient_id="P001",
    ):
        emit_log(
            logger,
            logging.INFO,
            "test.event",
            "Connecting to postgresql://clinical_user:clinical_password@localhost/db",
            operation="test_operation",
            database_url="postgresql://user:secret@localhost/db",
        )

    documents = _documents(stream)
    assert configuration.level == "INFO"
    assert configuration.output_format == "json"
    assert len(documents) == 1
    document = documents[0]
    assert document["schema_version"] == LOG_SCHEMA_VERSION
    assert str(document["timestamp"]).endswith("Z")
    assert document["level"] == "info"
    assert document["event"] == "test.event"
    assert document["component"] == "test_component"
    assert document["correlation_id"] == "corr-001"
    assert document["run_id"] == "00000000-0000-0000-0000-000000000001"
    assert document["dataset"] == "patients"
    assert document["patient_id"] == "<redacted>"
    assert document["database_url"] == "<redacted>"
    assert "clinical_password" not in str(document["message"])


def test_operation_logs_duration_and_completion_fields() -> None:
    stream = StringIO()
    configure_logging(level="INFO", output_format="json", stream=stream)
    logger = get_logger("operation_test")

    with log_operation(
        logger,
        "test.operation",
        operation="calculate_summary",
        stage="test",
        dataset="patients",
    ) as completion:
        completion["rows_processed"] = 8

    documents = _documents(stream)
    assert [document["event"] for document in documents] == [
        "test.operation.started",
        "test.operation.completed",
    ]
    assert documents[0]["outcome"] == "started"
    assert documents[1]["outcome"] == "success"
    assert documents[1]["rows_processed"] == 8
    assert isinstance(documents[1]["duration_ms"], int)
    assert int(documents[1]["duration_ms"]) >= 0


def test_operation_failure_logs_sqlstate_without_database_key_values() -> None:
    class FakeDatabaseError(RuntimeError):
        sqlstate = "23503"

    stream = StringIO()
    configure_logging(level="INFO", output_format="json", stream=stream)
    logger = get_logger("operation_test")

    with pytest.raises(FakeDatabaseError):
        with log_operation(
            logger,
            "test.database",
            operation="persist_rows",
            stage="persistence",
        ):
            raise FakeDatabaseError(
                "Foreign key failure\nDETAIL: Key (patient_id)=(P001) is not present."
            )

    failure = _documents(stream)[-1]
    assert failure["event"] == "test.database.failed"
    assert failure["outcome"] == "failure"
    assert failure["error_code"] == "23503"
    assert str(failure["error_type"]).endswith("FakeDatabaseError")
    assert "P001" not in str(failure["error_message"])
    assert "DETAIL: <redacted>" in str(failure["error_message"])


def test_nested_context_is_restored_after_scope_exit() -> None:
    assert current_log_context() == {}
    with bind_log_context(correlation_id="outer", dataset="patients"):
        assert current_log_context() == {
            "correlation_id": "outer",
            "dataset": "patients",
        }
        with bind_log_context(dataset="encounters", run_id="run-002"):
            assert current_log_context() == {
                "correlation_id": "outer",
                "dataset": "encounters",
                "run_id": "run-002",
            }
        assert current_log_context() == {
            "correlation_id": "outer",
            "dataset": "patients",
        }
    assert current_log_context() == {}


def test_invalid_environment_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_DATA_LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValueError, match="Unsupported log level"):
        configure_logging(stream=StringIO())


def test_pipeline_emits_correlated_aggregate_logs_without_clinical_values(
    tmp_path: Path,
) -> None:
    stream = StringIO()
    configure_logging(level="INFO", output_format="json", stream=stream)

    summary = run_dataset_validation(
        "patients",
        SAMPLE_PATIENTS,
        tmp_path / "processed",
        raw_root=tmp_path / "raw",
        reference_date=date(2026, 7, 29),
    )

    documents = _documents(stream)
    events = {str(document["event"]) for document in documents}
    assert {
        "pipeline.run.started",
        "pipeline.raw_capture.completed",
        "pipeline.validation.completed",
        "pipeline.output_write.completed",
        "pipeline.quality_report.completed",
        "pipeline.run.validated",
    }.issubset(events)
    run_documents = [
        document for document in documents if document.get("run_id") == str(summary.run_id)
    ]
    assert run_documents
    assert {document["dataset"] for document in run_documents} == {"patients"}
    serialized = "\n".join(json.dumps(document) for document in documents)
    assert "P001" not in serialized
    assert "patient_id" not in serialized


def test_console_entrypoint_logs_command_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CLINICAL_DATA_LOG_FORMAT", "json")
    monkeypatch.setenv("CLINICAL_DATA_LOG_LEVEL", "INFO")
    monkeypatch.setattr(entrypoint, "cli_main", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["clinical-data", "validate-contracts"])

    assert entrypoint.main() == 0

    documents = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.strip()
    ]
    assert [document["event"] for document in documents] == [
        "cli.command.started",
        "cli.command.completed",
    ]
    assert {document["command"] for document in documents} == {"validate-contracts"}
    assert len({document["correlation_id"] for document in documents}) == 1
