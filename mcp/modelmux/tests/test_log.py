"""Tests for structured logging configuration."""

from __future__ import annotations

import json
import logging

import pytest


@pytest.fixture(autouse=True)
def _reset_logging():
    """Reset the logging module state before each test."""
    import vyane.log as log_mod

    log_mod._configured = False
    loggers = [logging.getLogger("vyane"), logging.getLogger("modelmux")]
    for logger in loggers:
        logger.handlers.clear()
        logger.setLevel(logging.WARNING)
    yield
    log_mod._configured = False
    for logger in loggers:
        logger.handlers.clear()


class TestSetupLogging:
    def test_default_level_is_warning(self):
        from vyane.log import setup_logging

        setup_logging()
        logger = logging.getLogger("modelmux")
        assert logger.level == logging.WARNING

    def test_custom_level_from_arg(self):
        from vyane.log import setup_logging

        setup_logging(level="DEBUG")
        logger = logging.getLogger("modelmux")
        assert logger.level == logging.DEBUG

    def test_level_from_env(self, monkeypatch):
        from vyane.log import setup_logging

        monkeypatch.setenv("MODELMUX_LOG_LEVEL", "INFO")
        setup_logging()
        logger = logging.getLogger("modelmux")
        assert logger.level == logging.INFO

    def test_arg_overrides_env(self, monkeypatch):
        from vyane.log import setup_logging

        monkeypatch.setenv("MODELMUX_LOG_LEVEL", "INFO")
        setup_logging(level="ERROR")
        logger = logging.getLogger("modelmux")
        assert logger.level == logging.ERROR

    def test_text_format_default(self):
        from vyane.log import setup_logging

        setup_logging(level="DEBUG")
        logger = logging.getLogger("modelmux")
        assert len(logger.handlers) == 1
        assert not isinstance(logger.handlers[0].formatter, type(None))

    def test_json_format(self):
        from vyane.log import JSONFormatter, setup_logging

        setup_logging(level="DEBUG", fmt="json")
        logger = logging.getLogger("modelmux")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, JSONFormatter)

    def test_idempotent(self):
        from vyane.log import setup_logging

        setup_logging(level="DEBUG")
        setup_logging(level="ERROR")  # should be ignored
        logger = logging.getLogger("modelmux")
        assert logger.level == logging.DEBUG

    def test_child_loggers_inherit(self):
        from vyane.log import setup_logging

        setup_logging(level="DEBUG")
        child = logging.getLogger("vyane.a2a.http")
        assert child.getEffectiveLevel() == logging.DEBUG


class TestJSONFormatter:
    def test_format_produces_valid_json(self):
        from vyane.log import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="vyane.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "vyane.test"
        assert parsed["msg"] == "hello world"
        assert "ts" in parsed

    def test_format_includes_error(self):
        from vyane.log import JSONFormatter

        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="vyane.test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "error" in parsed
        assert "test error" in parsed["error"]
