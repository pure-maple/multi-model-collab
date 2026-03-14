"""Centralized logging configuration for vyane.

Usage:
    from vyane.log import setup_logging
    setup_logging()  # reads VYANE_LOG_LEVEL / MODELMUX_LOG_LEVEL env vars

Supports:
    - VYANE_LOG_LEVEL / MODELMUX_LOG_LEVEL env var
    - VYANE_LOG_FORMAT / MODELMUX_LOG_FORMAT env var
    - Programmatic configuration via setup_logging(level=, fmt=)
"""

from __future__ import annotations

import json
import logging
import os
import time


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["error"] = str(record.exc_info[1])
        return json.dumps(entry, ensure_ascii=False)


_TEXT_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_configured = False


def setup_logging(
    level: str = "",
    fmt: str = "",
) -> None:
    """Configure the Vyane logger hierarchy.

    Args:
        level: Log level (DEBUG/INFO/WARNING/ERROR). Defaults to
            VYANE_LOG_LEVEL, then MODELMUX_LOG_LEVEL, then WARNING.
        fmt: Format type ("text" or "json"). Defaults to
            VYANE_LOG_FORMAT, then MODELMUX_LOG_FORMAT, then "text".
    """
    global _configured
    if _configured:
        return
    _configured = True

    level = (
        level
        or os.environ.get("VYANE_LOG_LEVEL")
        or os.environ.get("MODELMUX_LOG_LEVEL", "WARNING")
    )
    fmt = (
        fmt
        or os.environ.get("VYANE_LOG_FORMAT")
        or os.environ.get("MODELMUX_LOG_FORMAT", "text")
    )

    log_level = getattr(logging, level.upper(), logging.WARNING)
    root_loggers = [logging.getLogger("vyane"), logging.getLogger("modelmux")]
    for root_logger in root_loggers:
        root_logger.setLevel(log_level)

    existing_handlers: list[logging.Handler] = []
    for root_logger in root_loggers:
        if root_logger.handlers:
            existing_handlers = list(root_logger.handlers)
            break

    if existing_handlers:
        for root_logger in root_loggers:
            if not root_logger.handlers:
                for handler in existing_handlers:
                    root_logger.addHandler(handler)
        return

    handler = logging.StreamHandler()
    handler.setLevel(log_level)

    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT, datefmt=_DATE_FORMAT))

    for root_logger in root_loggers:
        root_logger.addHandler(handler)
