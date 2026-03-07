"""Tests for the status module (real-time dispatch tracking)."""

import json
import time
from unittest.mock import patch

import pytest

from modelmux.status import (
    DispatchStatus,
    _safe_filename,
    list_active,
    remove_status,
    write_status,
)


class TestSafeFilename:
    def test_normal_run_id(self):
        assert _safe_filename("abc123") == "abc123"

    def test_uuid_fragment(self):
        assert _safe_filename("a1b2c3d4") == "a1b2c3d4"

    def test_strips_path_traversal(self):
        assert _safe_filename("../../../etc/passwd") == "etcpasswd"

    def test_strips_special_chars(self):
        assert _safe_filename("run;rm -rf") == "runrm-rf"

    def test_truncates_long_ids(self):
        long_id = "a" * 100
        result = _safe_filename(long_id)
        assert len(result) <= 32

    def test_empty_string(self):
        assert _safe_filename("") == ""

    def test_allows_hyphens_underscores(self):
        assert _safe_filename("run-id_123") == "run-id_123"


class TestWriteAndRemoveStatus:
    def test_write_creates_file(self, tmp_path):
        with patch("modelmux.status._status_dir", return_value=tmp_path):
            status = DispatchStatus(
                run_id="test1",
                provider="codex",
                task_summary="hello",
                status="running",
                started_at=time.time(),
            )
            write_status(status)

        status_file = tmp_path / "test1.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert data["provider"] == "codex"
        assert data["status"] == "running"

    def test_remove_deletes_file(self, tmp_path):
        with patch("modelmux.status._status_dir", return_value=tmp_path):
            status = DispatchStatus(run_id="rm1", provider="test")
            write_status(status)
            assert (tmp_path / "rm1.json").exists()

            remove_status("rm1")
            assert not (tmp_path / "rm1.json").exists()

    def test_remove_missing_file_ok(self, tmp_path):
        with patch("modelmux.status._status_dir", return_value=tmp_path):
            remove_status("nonexistent")  # Should not raise

    def test_write_empty_run_id_skipped(self, tmp_path):
        with patch("modelmux.status._status_dir", return_value=tmp_path):
            write_status(DispatchStatus(run_id="", provider="test"))
        assert len(list(tmp_path.glob("*.json"))) == 0


class TestListActive:
    def test_empty_dir(self, tmp_path):
        with patch("modelmux.status._status_dir", return_value=tmp_path):
            assert list_active() == []

    def test_nonexistent_dir(self, tmp_path):
        with patch(
            "modelmux.status._status_dir",
            return_value=tmp_path / "nonexistent",
        ):
            assert list_active() == []

    def test_lists_active_status(self, tmp_path):
        now = time.time()
        data = {
            "run_id": "active1",
            "provider": "gemini",
            "task_summary": "test",
            "status": "running",
            "started_at": now,
        }
        (tmp_path / "active1.json").write_text(json.dumps(data))

        with patch("modelmux.status._status_dir", return_value=tmp_path):
            result = list_active()

        assert len(result) == 1
        assert result[0].run_id == "active1"
        assert result[0].provider == "gemini"

    def test_removes_stale_entries(self, tmp_path):
        stale_data = {
            "run_id": "old1",
            "provider": "test",
            "started_at": time.time() - 700,  # > 600s ago
        }
        (tmp_path / "old1.json").write_text(json.dumps(stale_data))

        with patch("modelmux.status._status_dir", return_value=tmp_path):
            result = list_active()

        assert len(result) == 0
        assert not (tmp_path / "old1.json").exists()

    def test_sorted_by_started_at(self, tmp_path):
        now = time.time()
        for i, offset in enumerate([3, 1, 2]):
            data = {
                "run_id": f"s{i}",
                "provider": "test",
                "started_at": now - offset,
            }
            (tmp_path / f"s{i}.json").write_text(json.dumps(data))

        with patch("modelmux.status._status_dir", return_value=tmp_path):
            result = list_active()

        assert len(result) == 3
        # Sorted by started_at ascending (oldest first)
        assert result[0].started_at <= result[1].started_at
        assert result[1].started_at <= result[2].started_at

    def test_skips_malformed_json(self, tmp_path):
        (tmp_path / "bad.json").write_text("not json")
        good_data = {
            "run_id": "good",
            "provider": "test",
            "started_at": time.time(),
        }
        (tmp_path / "good.json").write_text(json.dumps(good_data))

        with patch("modelmux.status._status_dir", return_value=tmp_path):
            result = list_active()

        assert len(result) == 1
        assert result[0].run_id == "good"


class TestDispatchStatus:
    def test_default_values(self):
        status = DispatchStatus()
        assert status.run_id == ""
        assert status.provider == ""
        assert status.status == "pending"
        assert status.output_lines == 0
        assert status.failover_from == ""

    def test_with_failover(self):
        status = DispatchStatus(
            run_id="f1",
            provider="gemini",
            failover_from="codex",
        )
        assert status.failover_from == "codex"
