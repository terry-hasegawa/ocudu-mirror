# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""Structured logging configuration shared by every pipeline stage.

Each log record is emitted as a single-line JSON object so that downstream log
processors (Loki, ELK, ...) can index the ``stage`` and any extra structured
fields attached via ``logger.info(msg, extra={"extra_fields": {...}})``.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

# Keys that are always present on a LogRecord; everything else attached to the
# record is treated as a structured extra field.
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "extra_fields", "taskName"}


class JsonFormatter(logging.Formatter):
    """Formats a :class:`logging.LogRecord` as a compact JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "stage": record.name,
            "msg": record.getMessage(),
        }

        # Structured fields can be passed either via extra={"extra_fields": {..}}
        # or as ad-hoc attributes on the record.
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key != "extra_fields":
                payload[key] = value

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO, *, json_format: bool = True) -> None:
    """Configures the root logger for the pipeline.

    Args:
        level: Minimum log level to emit.
        json_format: When ``True`` emit structured JSON lines, otherwise a
            human readable format (handy for interactive debugging).
    """
    handler = logging.StreamHandler(sys.stderr)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(stage: str) -> logging.Logger:
    """Returns a logger namespaced under ``ofh.<stage>``."""
    return logging.getLogger(f"ofh.{stage}")
