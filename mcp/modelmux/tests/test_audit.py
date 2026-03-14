"""Tests for audit.py — dispatch audit logging."""

import datetime
import json
import time
from unittest.mock import patch

import pytest

from vyane.audit import (
    AuditEntry,
    _audit_file,
    count_recent,
    get_audit_stats,
    log_dispatch,
    read_recent,
)


class TestAuditEntry:
    def test_default_fields(self):
        entry = AuditEntry()
        assert entry.provider == ""
        assert entry.status == ""
        assert entry.duration_seconds == 0.0

    def test_with_fields(self):
        entry = AuditEntry(
            timestamp="2026-03-07T12:00:00+00:00",
            provider="codex",
            task_summary="test",
            status="success",
            duration_seconds=5.0,
        )
        assert entry.provider == "codex"
        assert entry.duration_seconds == 5.0


class TestLogDispatch:
    def test_writes_entry(self, tmp_path):
        audit = tmp_path / "audit.jsonl"
        with (
            patch("vyane.audit._audit_dir", return_value=tmp_path),
            patch("vyane.audit._audit_file", return_value=audit),
        ):
            entry = AuditEntry(
                timestamp="2026-03-07T12:00:00+00:00",
                provider="codex",
                task_summary="review code",
                status="success",
                duration_seconds=3.0,
            )
            log_dispatch(entry)

        lines = audit.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["provider"] == "codex"
        assert data["status"] == "success"

    def test_appends_multiple(self, tmp_path):
        audit = tmp_path / "audit.jsonl"
        with (
            patch("vyane.audit._audit_dir", return_value=tmp_path),
            patch("vyane.audit._audit_file", return_value=audit),
        ):
            log_dispatch(AuditEntry(provider="codex", status="success"))
            log_dispatch(AuditEntry(provider="gemini", status="error"))

        lines = audit.read_text().strip().split("\n")
        assert len(lines) == 2


class TestReadRecent:
    def test_reads_recent(self, tmp_path):
        audit = tmp_path / "audit.jsonl"
        now = datetime.datetime.now(datetime.timezone.utc)
        recent_ts = now.isoformat()
        old_ts = (now - datetime.timedelta(hours=2)).isoformat()

        entries = [
            {"timestamp": old_ts, "provider": "codex", "status": "success"},
            {"timestamp": recent_ts, "provider": "gemini", "status": "success"},
        ]
        audit.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        with patch("vyane.audit._audit_file", return_value=audit):
            result = read_recent(hours=1)
        assert len(result) == 1
        assert result[0].provider == "gemini"

    def test_no_file(self, tmp_path):
        audit = tmp_path / "nonexistent.jsonl"
        with patch("vyane.audit._audit_file", return_value=audit):
            result = read_recent()
        assert result == []

    def test_malformed_json_skipped(self, tmp_path):
        audit = tmp_path / "audit.jsonl"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        audit.write_text(
            f'{{"timestamp": "{now}", "provider": "codex", "status": "ok"}}\n'
            "not json\n"
        )
        with patch("vyane.audit._audit_file", return_value=audit):
            result = read_recent(hours=1)
        assert len(result) == 1


class TestCountRecent:
    def test_count(self, tmp_path):
        audit = tmp_path / "audit.jsonl"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entries = [
            {"timestamp": now, "provider": "codex", "status": "success"},
            {"timestamp": now, "provider": "gemini", "status": "error"},
        ]
        audit.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        with patch("vyane.audit._audit_file", return_value=audit):
            assert count_recent(hours=1) == 2


class TestGetAuditStats:
    def test_no_file(self, tmp_path):
        audit = tmp_path / "nonexistent.jsonl"
        with patch("vyane.audit._audit_file", return_value=audit):
            stats = get_audit_stats()
        assert stats["total_entries"] == 0

    def test_with_entries(self, tmp_path):
        audit = tmp_path / "audit.jsonl"
        entries = [
            {"provider": "codex", "status": "success"},
            {"provider": "codex", "status": "error"},
            {"provider": "gemini", "status": "success"},
        ]
        audit.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        with patch("vyane.audit._audit_file", return_value=audit):
            stats = get_audit_stats()
        assert stats["total_entries"] == 3
        assert stats["by_provider"]["codex"] == 2
        assert stats["by_provider"]["gemini"] == 1
        assert stats["by_status"]["success"] == 2
        assert stats["by_status"]["error"] == 1
        assert stats["file_size_bytes"] > 0
