"""Tests for the history module (dispatch result logging, queries, stats, trends)."""

import json
import time
from unittest.mock import MagicMock, patch

from modelmux.history import (
    HistoryQuery,
    _history_file,
    _maybe_rotate,
    get_history_stats,
    get_trends,
    log_result,
    read_history,
)


class TestHistoryFile:
    def test_returns_path(self):
        path = _history_file()
        assert str(path).endswith("history.jsonl")
        assert ".config/modelmux" in str(path)


class TestLogResult:
    def test_writes_entry(self, tmp_path):
        hf = tmp_path / "history.jsonl"
        with patch("modelmux.history._history_file", return_value=hf):
            log_result({"provider": "codex", "status": "success"}, task="test")

        assert hf.exists()
        data = json.loads(hf.read_text().strip())
        assert data["provider"] == "codex"
        assert data["status"] == "success"
        assert data["task"] == "test"
        assert data["source"] == "dispatch"
        assert "ts" in data

    def test_task_truncated(self, tmp_path):
        hf = tmp_path / "history.jsonl"
        with patch("modelmux.history._history_file", return_value=hf):
            log_result({"provider": "test"}, task="x" * 1000)

        data = json.loads(hf.read_text().strip())
        assert len(data["task"]) == 500

    def test_appends_multiple(self, tmp_path):
        hf = tmp_path / "history.jsonl"
        with patch("modelmux.history._history_file", return_value=hf):
            log_result({"provider": "a"}, task="t1")
            log_result({"provider": "b"}, task="t2")

        lines = hf.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["provider"] == "a"
        assert json.loads(lines[1])["provider"] == "b"

    def test_custom_source(self, tmp_path):
        hf = tmp_path / "history.jsonl"
        with patch("modelmux.history._history_file", return_value=hf):
            log_result({"provider": "test"}, source="broadcast")

        data = json.loads(hf.read_text().strip())
        assert data["source"] == "broadcast"

    def test_creates_parent_dirs(self, tmp_path):
        hf = tmp_path / "nested" / "dir" / "history.jsonl"
        with patch("modelmux.history._history_file", return_value=hf):
            log_result({"provider": "test"})

        assert hf.exists()


class TestMaybeRotate:
    def test_no_rotation_small_file(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        hf.write_text("line1\nline2\nline3\n")
        _maybe_rotate(hf, max_bytes=1000)
        assert hf.read_text().count("\n") == 3

    def test_rotates_large_file(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        # Write many lines to exceed limit
        lines = [json.dumps({"i": i}) for i in range(100)]
        hf.write_text("\n".join(lines) + "\n")
        original_size = hf.stat().st_size
        _maybe_rotate(hf, max_bytes=100)
        new_size = hf.stat().st_size
        assert new_size < original_size

    def test_keeps_half(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        lines = [f"line{i}" for i in range(10)]
        hf.write_text("\n".join(lines) + "\n")
        _maybe_rotate(hf, max_bytes=1)
        remaining = hf.read_text().strip().split("\n")
        assert len(remaining) == 5  # half of 10

    def test_nonexistent_file(self, tmp_path):
        hf = tmp_path / "nope.jsonl"
        _maybe_rotate(hf)  # Should not raise


class TestReadHistory:
    def _write_entries(self, path, entries):
        lines = [json.dumps(e) for e in entries]
        path.write_text("\n".join(lines) + "\n")

    def test_empty_file(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        hf.write_text("")
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history()
        assert result == []

    def test_file_not_exists(self, tmp_path):
        hf = tmp_path / "nope.jsonl"
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history()
        assert result == []

    def test_returns_entries(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "a", "ts": now - 2, "status": "success"},
            {"provider": "b", "ts": now - 1, "status": "success"},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history()
        assert len(result) == 2
        # Most recent first
        assert result[0]["provider"] == "b"

    def test_limit(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [{"provider": f"p{i}", "ts": now - i} for i in range(10)]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history(HistoryQuery(limit=3))
        assert len(result) == 3

    def test_filter_provider(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "codex", "ts": now - 2},
            {"provider": "gemini", "ts": now - 1},
            {"provider": "codex", "ts": now},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history(HistoryQuery(provider="codex"))
        assert len(result) == 2
        assert all(r["provider"] == "codex" for r in result)

    def test_filter_status(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "a", "ts": now - 1, "status": "success"},
            {"provider": "b", "ts": now, "status": "error"},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history(HistoryQuery(status="error"))
        assert len(result) == 1
        assert result[0]["status"] == "error"

    def test_filter_source(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "a", "ts": now - 1, "source": "dispatch"},
            {"provider": "b", "ts": now, "source": "broadcast"},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history(HistoryQuery(source="broadcast"))
        assert len(result) == 1
        assert result[0]["source"] == "broadcast"

    def test_filter_hours(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "old", "ts": now - 7200},  # 2 hours ago
            {"provider": "new", "ts": now - 60},  # 1 min ago
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history(HistoryQuery(hours=1))
        assert len(result) == 1
        assert result[0]["provider"] == "new"

    def test_skips_malformed_json(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        hf.write_text('not json\n{"provider": "ok", "ts": ' + str(time.time()) + "}\n")
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history()
        assert len(result) == 1
        assert result[0]["provider"] == "ok"

    def test_skips_blank_lines(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        hf.write_text(
            f'\n{json.dumps({"provider": "a", "ts": now})}\n\n'
        )
        with patch("modelmux.history._history_file", return_value=hf):
            result = read_history()
        assert len(result) == 1


class TestHistoryQuery:
    def test_defaults(self):
        q = HistoryQuery()
        assert q.limit == 20
        assert q.provider == ""
        assert q.status == ""
        assert q.source == ""
        assert q.hours == 0


class TestGetHistoryStats:
    def _write_entries(self, path, entries):
        lines = [json.dumps(e) for e in entries]
        path.write_text("\n".join(lines) + "\n")

    def test_no_file(self, tmp_path):
        hf = tmp_path / "nope.jsonl"
        with patch("modelmux.history._history_file", return_value=hf):
            stats = get_history_stats()
        assert stats == {"total": 0}

    def test_basic_stats(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {
                "provider": "codex",
                "status": "success",
                "duration_seconds": 10,
                "ts": now,
                "source": "dispatch",
            },
            {
                "provider": "codex",
                "status": "error",
                "duration_seconds": 5,
                "ts": now,
                "source": "dispatch",
            },
            {
                "provider": "gemini",
                "status": "success",
                "duration_seconds": 8,
                "ts": now,
                "source": "broadcast",
            },
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            stats = get_history_stats()

        assert stats["total"] == 3
        assert "codex" in stats["by_provider"]
        assert "gemini" in stats["by_provider"]
        assert stats["by_provider"]["codex"]["calls"] == 2
        assert stats["by_provider"]["codex"]["success"] == 1
        assert stats["by_provider"]["codex"]["error"] == 1
        assert stats["by_provider"]["codex"]["success_rate"] == 50.0
        assert stats["by_source"]["dispatch"] == 2
        assert stats["by_source"]["broadcast"] == 1

    def test_hours_filter(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "old", "status": "success", "ts": now - 7200, "source": "d"},
            {"provider": "new", "status": "success", "ts": now - 60, "source": "d"},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            stats = get_history_stats(hours=1)
        assert stats["total"] == 1

    def test_avg_duration(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "a", "status": "success", "duration_seconds": 10, "ts": now},
            {"provider": "a", "status": "success", "duration_seconds": 20, "ts": now},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            stats = get_history_stats()
        assert stats["by_provider"]["a"]["avg_duration"] == 15.0


class TestGetTrends:
    def _write_entries(self, path, entries):
        lines = [json.dumps(e) for e in entries]
        path.write_text("\n".join(lines) + "\n")

    def test_no_file(self, tmp_path):
        hf = tmp_path / "nope.jsonl"
        with patch("modelmux.history._history_file", return_value=hf):
            result = get_trends()
        assert result["buckets"] == []

    def test_empty_file(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        hf.write_text("")
        with patch("modelmux.history._history_file", return_value=hf):
            result = get_trends()
        assert result["buckets"] == []

    def test_basic_trends(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {
                "provider": "codex",
                "status": "success",
                "duration_seconds": 5,
                "ts": now - 60,
            },
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = get_trends(hours=1)
        assert result["total_entries"] == 1
        assert len(result["buckets"]) > 0
        # At least one bucket should have count > 0
        active = [b for b in result["buckets"] if b["count"] > 0]
        assert len(active) == 1
        assert active[0]["success"] == 1
        assert active[0]["success_rate"] == 100.0

    def test_error_tracking(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "a", "status": "error", "ts": now - 30},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = get_trends(hours=1)
        active = [b for b in result["buckets"] if b["count"] > 0]
        assert active[0]["error"] == 1
        assert active[0]["success_rate"] == 0

    def test_by_provider(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "codex", "status": "success", "ts": now - 30},
            {"provider": "gemini", "status": "success", "ts": now - 20},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = get_trends(hours=1)
        active = [b for b in result["buckets"] if b["count"] > 0]
        assert len(active) == 1
        assert active[0]["by_provider"]["codex"] == 1
        assert active[0]["by_provider"]["gemini"] == 1

    def test_malformed_json_skipped(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        hf.write_text(
            f'{json.dumps({"provider": "a", "status": "success", "ts": now - 30})}\n'
            "not json\n"
        )
        with patch("modelmux.history._history_file", return_value=hf):
            result = get_trends(hours=1)
        assert result["total_entries"] == 1

    def test_blank_lines_skipped(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        hf.write_text(
            f'\n{json.dumps({"provider": "a", "status": "success", "ts": now - 30})}\n\n'
        )
        with patch("modelmux.history._history_file", return_value=hf):
            result = get_trends(hours=1)
        assert result["total_entries"] == 1

    def test_oserror_returns_empty(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        hf.write_text("data\n")
        with (
            patch("modelmux.history._history_file", return_value=hf),
            patch("builtins.open", side_effect=OSError("fail")),
        ):
            result = get_trends(hours=1)
        assert result["buckets"] == []

    def test_cost_tracking_with_token_usage(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {
                "provider": "codex",
                "status": "success",
                "ts": now - 30,
                "duration_seconds": 2.0,
                "token_usage": {"input_tokens": 100, "output_tokens": 50},
            },
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            result = get_trends(hours=1)
        active = [b for b in result["buckets"] if b["count"] > 0]
        assert len(active) == 1
        # Cost should be computed (value depends on pricing, just check it exists)
        assert "cost" in active[0]
        assert "cumulative_cost" in active[0]

    def test_cost_estimation_failure_handled(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {
                "provider": "codex",
                "status": "success",
                "ts": now - 30,
                "token_usage": {"input_tokens": 100, "output_tokens": 50},
            },
        ]
        self._write_entries(hf, entries)
        with (
            patch("modelmux.history._history_file", return_value=hf),
            patch("modelmux.costs.estimate_cost", side_effect=Exception("pricing error")),
        ):
            result = get_trends(hours=1)
        # Should not crash, just skip cost
        assert result["total_entries"] == 1


class TestLogResultEdgeCases:
    def test_routing_cache_invalidation(self, tmp_path):
        hf = tmp_path / "history.jsonl"
        mock_invalidate = MagicMock()
        with (
            patch("modelmux.history._history_file", return_value=hf),
            patch("modelmux.routing.invalidate_routing_cache", mock_invalidate),
        ):
            log_result({"provider": "codex"})
        mock_invalidate.assert_called_once()

    def test_notification_failure_handled(self, tmp_path):
        hf = tmp_path / "history.jsonl"
        with (
            patch("modelmux.history._history_file", return_value=hf),
            patch("modelmux.notifications.notify_dispatch", side_effect=Exception("webhook fail")),
        ):
            # Should not raise
            log_result({"provider": "codex"})
        assert hf.exists()

    def test_oserror_handled(self, tmp_path):
        hf = tmp_path / "history.jsonl"
        with (
            patch("modelmux.history._history_file", return_value=hf),
            patch("builtins.open", side_effect=OSError("disk full")),
        ):
            # Should not raise
            log_result({"provider": "codex"})


class TestGetHistoryStatsEdgeCases:
    def _write_entries(self, path, entries):
        lines = [json.dumps(e) for e in entries]
        path.write_text("\n".join(lines) + "\n")

    def test_malformed_json_skipped(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        hf.write_text(
            f'{json.dumps({"provider": "a", "status": "success", "ts": now, "duration_seconds": 1.0})}\n'
            "bad json\n"
        )
        with patch("modelmux.history._history_file", return_value=hf):
            stats = get_history_stats()
        assert stats["total"] == 1

    def test_blank_lines_skipped(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        hf.write_text(
            f'\n{json.dumps({"provider": "a", "status": "success", "ts": now, "duration_seconds": 1.0})}\n\n'
        )
        with patch("modelmux.history._history_file", return_value=hf):
            stats = get_history_stats()
        assert stats["total"] == 1

    def test_oserror_returns_empty(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        hf.write_text("data\n")
        with (
            patch("modelmux.history._history_file", return_value=hf),
            patch("builtins.open", side_effect=OSError("fail")),
        ):
            stats = get_history_stats()
        assert stats["total"] == 0

    def test_include_costs(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {
                "provider": "codex",
                "status": "success",
                "ts": now,
                "duration_seconds": 1.0,
                "token_usage": {"input_tokens": 100, "output_tokens": 50},
            },
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            stats = get_history_stats(include_costs=True)
        assert stats["total"] == 1
        assert "costs" in stats

    def test_include_costs_no_token_entries(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "codex", "status": "success", "ts": now, "duration_seconds": 1.0},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            stats = get_history_stats(include_costs=True)
        assert stats["total"] == 1
        assert "costs" not in stats  # no token usage entries

    def test_hours_filter_excludes_old(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        now = time.time()
        entries = [
            {"provider": "old", "status": "success", "ts": now - 7200, "duration_seconds": 1.0},
            {"provider": "new", "status": "success", "ts": now, "duration_seconds": 2.0},
        ]
        self._write_entries(hf, entries)
        with patch("modelmux.history._history_file", return_value=hf):
            stats = get_history_stats(hours=1)
        assert stats["total"] == 1
        assert "new" in stats["by_provider"]
        assert "old" not in stats["by_provider"]


class TestReadHistoryEdgeCases:
    def test_oserror_returns_empty(self, tmp_path):
        hf = tmp_path / "h.jsonl"
        hf.write_text("data\n")
        with (
            patch("modelmux.history._history_file", return_value=hf),
            patch("builtins.open", side_effect=OSError("read error")),
        ):
            result = read_history()
        assert result == []
