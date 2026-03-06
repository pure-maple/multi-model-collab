"""Tests for the export module."""

import csv
import io
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from modelmux.export import export_csv, export_json, export_markdown, run_export

SAMPLE_ENTRIES = [
    {
        "ts": 1700000000,
        "provider": "codex",
        "status": "success",
        "duration_seconds": 12.5,
        "task": "Fix the bug in pool.py",
        "source": "dispatch",
        "run_id": "abc123",
        "token_usage": {"input_tokens": 1000, "output_tokens": 500},
    },
    {
        "ts": 1700001000,
        "provider": "gemini",
        "status": "error",
        "duration_seconds": 5.0,
        "task": "Review security policy",
        "source": "broadcast",
        "run_id": "def456",
    },
]


class TestExportCSV:
    def test_csv_has_header(self):
        result = export_csv([])
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert "timestamp" in header
        assert "provider" in header
        assert "status" in header

    def test_csv_with_entries(self):
        result = export_csv(SAMPLE_ENTRIES)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["provider"] == "codex"
        assert rows[0]["status"] == "success"
        assert rows[0]["input_tokens"] == "1000"
        assert rows[1]["provider"] == "gemini"

    def test_csv_empty_token_usage(self):
        entries = [{"ts": 1700000000, "provider": "ollama", "status": "success"}]
        result = export_csv(entries)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[0]["input_tokens"] == ""


class TestExportJSON:
    def test_json_valid(self):
        result = export_json(SAMPLE_ENTRIES)
        data = json.loads(result)
        assert data["count"] == 2
        assert "exported_at" in data
        assert len(data["entries"]) == 2

    def test_json_with_stats(self):
        stats = {"total": 42, "by_provider": {"codex": {"calls": 20}}}
        result = export_json(SAMPLE_ENTRIES, stats=stats)
        data = json.loads(result)
        assert data["statistics"]["total"] == 42

    def test_json_empty(self):
        result = export_json([])
        data = json.loads(result)
        assert data["count"] == 0
        assert data["entries"] == []


class TestExportMarkdown:
    def test_markdown_has_title(self):
        result = export_markdown([], title="Test Report")
        assert "# Test Report" in result

    def test_markdown_with_stats(self):
        stats = {
            "total": 10,
            "by_provider": {
                "codex": {
                    "calls": 8,
                    "success_rate": 87.5,
                    "avg_duration": 15.0,
                }
            },
            "by_source": {"dispatch": 7, "broadcast": 3},
        }
        result = export_markdown(SAMPLE_ENTRIES, stats=stats)
        assert "## Summary" in result
        assert "10" in result
        assert "## Provider Breakdown" in result
        assert "codex" in result
        assert "87.5%" in result

    def test_markdown_with_costs(self):
        stats = {
            "total": 5,
            "costs": {
                "entries_with_usage": 3,
                "total_cost_usd": 0.0123,
                "total_input_tokens": 5000,
                "total_output_tokens": 2000,
            },
        }
        result = export_markdown([], stats=stats)
        assert "## Cost Summary" in result
        assert "$0.0123" in result

    def test_markdown_entries_table(self):
        result = export_markdown(SAMPLE_ENTRIES)
        assert "## Recent Dispatches" in result
        assert "codex" in result
        assert "gemini" in result

    def test_markdown_caps_entries(self):
        entries = [
            {"ts": 1700000000 + i, "provider": "codex", "status": "success"}
            for i in range(100)
        ]
        result = export_markdown(entries)
        # Should cap at 50 table rows
        assert result.count("| codex |") <= 50


class TestRunExport:
    def test_run_csv(self):
        with patch("modelmux.export.read_history", return_value=SAMPLE_ENTRIES):
            with patch(
                "modelmux.export.get_history_stats", return_value={"total": 2}
            ):
                content = run_export(fmt="csv")
        assert "provider" in content
        assert "codex" in content

    def test_run_json(self):
        with patch("modelmux.export.read_history", return_value=SAMPLE_ENTRIES):
            with patch(
                "modelmux.export.get_history_stats", return_value={"total": 2}
            ):
                content = run_export(fmt="json")
        data = json.loads(content)
        assert data["count"] == 2

    def test_run_markdown(self):
        with patch("modelmux.export.read_history", return_value=SAMPLE_ENTRIES):
            with patch(
                "modelmux.export.get_history_stats", return_value={"total": 2}
            ):
                content = run_export(fmt="md")
        assert "# modelmux Report" in content

    def test_run_to_file(self, tmp_path):
        outfile = str(tmp_path / "report.csv")
        with patch("modelmux.export.read_history", return_value=SAMPLE_ENTRIES):
            with patch(
                "modelmux.export.get_history_stats", return_value={"total": 2}
            ):
                run_export(fmt="csv", output=outfile)
        assert Path(outfile).exists()
        content = Path(outfile).read_text()
        assert "codex" in content

    def test_unknown_format(self):
        with patch("modelmux.export.read_history", return_value=[]):
            with patch(
                "modelmux.export.get_history_stats", return_value={"total": 0}
            ):
                with pytest.raises(ValueError, match="Unknown format"):
                    run_export(fmt="xml")
