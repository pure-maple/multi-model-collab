"""Tests for history trends (time-series aggregation)."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from modelmux.history import get_trends


@pytest.fixture
def history_dir(tmp_path):
    """Create a temp history file."""
    config_dir = tmp_path / ".config" / "modelmux"
    config_dir.mkdir(parents=True)
    return config_dir


def _write_history(history_dir: Path, entries: list[dict]) -> Path:
    path = history_dir / "history.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


class TestGetTrendsEmpty:
    def test_no_file(self, tmp_path):
        fake_path = tmp_path / "nonexistent" / "history.jsonl"
        with patch("modelmux.history._history_file", return_value=fake_path):
            result = get_trends(hours=24)
        assert result["buckets"] == []

    def test_empty_file(self, history_dir):
        path = history_dir / "history.jsonl"
        path.write_text("")
        with patch("modelmux.history._history_file", return_value=path):
            result = get_trends(hours=24)
        assert result["buckets"] == []

    def test_all_entries_too_old(self, history_dir):
        now = time.time()
        old_ts = now - 48 * 3600  # 48 hours ago
        entries = [
            {"ts": old_ts, "provider": "codex", "status": "success", "duration_seconds": 5},
        ]
        path = _write_history(history_dir, entries)
        with patch("modelmux.history._history_file", return_value=path):
            result = get_trends(hours=24)
        assert result["buckets"] == [] or all(b["count"] == 0 for b in result["buckets"])


class TestGetTrendsWithData:
    def test_single_entry(self, history_dir):
        now = time.time()
        entries = [
            {
                "ts": now - 600,
                "provider": "codex",
                "status": "success",
                "duration_seconds": 10.5,
            },
        ]
        path = _write_history(history_dir, entries)
        with patch("modelmux.history._history_file", return_value=path):
            result = get_trends(hours=2, bucket_minutes=60)
        assert result["total_entries"] == 1
        filled = [b for b in result["buckets"] if b["count"] > 0]
        assert len(filled) == 1
        assert filled[0]["count"] == 1
        assert filled[0]["success"] == 1
        assert filled[0]["error"] == 0
        assert filled[0]["success_rate"] == 100.0
        assert filled[0]["avg_duration"] == 10.5

    def test_multiple_entries_same_bucket(self, history_dir):
        now = time.time()
        base = now - 300
        entries = [
            {"ts": base, "provider": "codex", "status": "success", "duration_seconds": 10},
            {"ts": base + 60, "provider": "gemini", "status": "success", "duration_seconds": 20},
            {"ts": base + 120, "provider": "codex", "status": "error", "duration_seconds": 5},
        ]
        path = _write_history(history_dir, entries)
        with patch("modelmux.history._history_file", return_value=path):
            result = get_trends(hours=1, bucket_minutes=60)
        filled = [b for b in result["buckets"] if b["count"] > 0]
        assert len(filled) == 1
        b = filled[0]
        assert b["count"] == 3
        assert b["success"] == 2
        assert b["error"] == 1
        assert b["success_rate"] == 66.7
        assert b["by_provider"]["codex"] == 2
        assert b["by_provider"]["gemini"] == 1

    def test_entries_across_buckets(self, history_dir):
        now = time.time()
        entries = [
            {"ts": now - 7200, "provider": "codex", "status": "success", "duration_seconds": 5},
            {"ts": now - 3600, "provider": "gemini", "status": "success", "duration_seconds": 8},
            {"ts": now - 600, "provider": "claude", "status": "error", "duration_seconds": 3},
        ]
        path = _write_history(history_dir, entries)
        with patch("modelmux.history._history_file", return_value=path):
            result = get_trends(hours=4, bucket_minutes=60)
        filled = [b for b in result["buckets"] if b["count"] > 0]
        assert len(filled) >= 2  # Should be in different buckets
        assert result["total_entries"] == 3

    def test_cumulative_cost(self, history_dir):
        now = time.time()
        entries = [
            {
                "ts": now - 7200,
                "provider": "codex",
                "status": "success",
                "duration_seconds": 5,
                "token_usage": {"input_tokens": 1000, "output_tokens": 500},
            },
            {
                "ts": now - 600,
                "provider": "codex",
                "status": "success",
                "duration_seconds": 8,
                "token_usage": {"input_tokens": 2000, "output_tokens": 1000},
            },
        ]
        path = _write_history(history_dir, entries)
        with patch("modelmux.history._history_file", return_value=path):
            result = get_trends(hours=4, bucket_minutes=60)
        # Cumulative cost should be non-decreasing
        costs = [b["cumulative_cost"] for b in result["buckets"]]
        for i in range(1, len(costs)):
            assert costs[i] >= costs[i - 1]
        # Last bucket should have total cost
        assert costs[-1] > 0


class TestGetTrendsBucketSize:
    def test_small_buckets(self, history_dir):
        now = time.time()
        entries = [
            {"ts": now - 300, "provider": "codex", "status": "success", "duration_seconds": 5},
        ]
        path = _write_history(history_dir, entries)
        with patch("modelmux.history._history_file", return_value=path):
            result = get_trends(hours=1, bucket_minutes=15)
        # 1 hour / 15 min = ~4-5 buckets
        assert len(result["buckets"]) >= 4
        assert result["bucket_minutes"] == 15

    def test_returns_metadata(self, history_dir):
        path = history_dir / "history.jsonl"
        path.write_text("")
        with patch("modelmux.history._history_file", return_value=path):
            result = get_trends(hours=12, bucket_minutes=30)
        assert result["hours"] == 12
        assert result["bucket_minutes"] == 30
