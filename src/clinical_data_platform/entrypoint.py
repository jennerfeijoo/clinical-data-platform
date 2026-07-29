"""Console entrypoint that configures structured logging before CLI dispatch."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Sequence

from clinical_data_platform.cli import main as cli_main
from clinical_data_platform.structured_logging import (
    bind_log_context,
    configure_logging,
    emit_log,
    ensure_correlation_id,
    get_logger,
    safe_exception_fields,
)

LOGGER = get_logger("cli")


def _command_name(argv: Sequence[str]) -> str:
    return argv[0] if argv else "unknown"


def main() -> int:
    """Configure logging, correlate the command, and delegate to the CLI."""
    configure_logging()
    command = _command_name(sys.argv[1:])
    started = time.perf_counter()
    with ensure_correlation_id(), bind_log_context(command=command):
        emit_log(
            LOGGER,
            logging.INFO,
            "cli.command.started",
            "Started CLI command.",
            outcome="started",
        )
        try:
            result = cli_main()
        except BaseException as error:
            duration_ms = max(0, round((time.perf_counter() - started) * 1000))
            emit_log(
                LOGGER,
                logging.ERROR,
                "cli.command.failed",
                "CLI command failed.",
                outcome="failure",
                duration_ms=duration_ms,
                **safe_exception_fields(error),
            )
            raise
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        emit_log(
            LOGGER,
            logging.INFO,
            "cli.command.completed",
            "Completed CLI command.",
            outcome="success",
            duration_ms=duration_ms,
            exit_code=result,
        )
        return result
