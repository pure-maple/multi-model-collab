"""Tests for the benchmark suite."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vyane.benchmark import (
    BENCHMARK_TASKS,
    BenchmarkReport,
    BenchmarkResult,
    _build_summary,
    _check_keywords,
    format_report,
    run_benchmark,
    save_report,
)


class TestCheckKeywords:
    def test_all_keywords_found(self):
        hits, total = _check_keywords("None TypeError enumerate", ["None", "TypeError"])
        assert hits == 2
        assert total == 2

    def test_partial_match(self):
        hits, total = _check_keywords("found None but not other", ["None", "TypeError"])
        assert hits == 1
        assert total == 2

    def test_case_insensitive(self):
        hits, total = _check_keywords("none typeerror", ["None", "TypeError"])
        assert hits == 2

    def test_empty_keywords(self):
        hits, total = _check_keywords("anything", [])
        assert hits == 0
        assert total == 0


class TestBenchmarkResult:
    def test_keyword_score(self):
        r = BenchmarkResult(keyword_hits=3, keyword_total=4)
        assert r.keyword_score == 0.75

    def test_keyword_score_zero_total(self):
        r = BenchmarkResult(keyword_hits=0, keyword_total=0)
        assert r.keyword_score == 1.0


class TestBuildSummary:
    def test_empty_results(self):
        summary = _build_summary([])
        assert summary["total_runs"] == 0
        assert summary["by_provider"] == {}

    def test_single_provider(self):
        results = [
            BenchmarkResult(
                provider="codex",
                status="success",
                duration_seconds=5.0,
                keyword_hits=2,
                keyword_total=3,
            ),
            BenchmarkResult(
                provider="codex",
                status="success",
                duration_seconds=3.0,
                keyword_hits=3,
                keyword_total=3,
            ),
        ]
        summary = _build_summary(results)
        codex = summary["by_provider"]["codex"]
        assert codex["total"] == 2
        assert codex["success"] == 2
        assert codex["success_rate"] == 100.0
        assert codex["avg_duration"] == 4.0

    def test_mixed_results(self):
        results = [
            BenchmarkResult(provider="codex", status="success", duration_seconds=5),
            BenchmarkResult(provider="codex", status="error", duration_seconds=2),
        ]
        summary = _build_summary(results)
        assert summary["by_provider"]["codex"]["success_rate"] == 50.0


class TestRunBenchmark:
    def test_run_with_mock_adapter(self):
        from vyane.adapters.base import AdapterResult

        mock_result = AdapterResult(
            run_id="test",
            provider="codex",
            status="success",
            summary="Review complete",
            output="None check needed, use enumerate",
        )

        mock_adapter = MagicMock()
        mock_adapter._binary_name.return_value = "codex"
        mock_adapter.run = AsyncMock(return_value=mock_result)

        with patch("vyane.adapters.get_all_adapters", return_value={"codex": mock_adapter}):
            with patch("vyane.adapters.ADAPTERS", {"codex": type(mock_adapter)}):
                report = run_benchmark(
                    providers=["codex"],
                    task_names=["code_review"],
                )

        assert len(report.results) == 1
        r = report.results[0]
        assert r.provider == "codex"
        assert r.status == "success"
        assert r.output_length > 0

    def test_run_with_failing_adapter(self):
        mock_adapter = MagicMock()
        mock_adapter._binary_name.return_value = "failing"
        mock_adapter.run = AsyncMock(side_effect=RuntimeError("connection failed"))

        with patch("vyane.adapters.get_all_adapters", return_value={"failing": mock_adapter}):
            with patch("vyane.adapters.ADAPTERS", {"failing": type(mock_adapter)}):
                report = run_benchmark(
                    providers=["failing"],
                    task_names=["reasoning"],
                )

        assert len(report.results) == 1
        assert report.results[0].status == "error"
        assert "connection failed" in report.results[0].error


class TestFormatReport:
    def test_format_output(self):
        report = BenchmarkReport(
            timestamp="2026-03-07T12:00:00",
            results=[
                BenchmarkResult(
                    provider="codex",
                    task_name="code_review",
                    category="analysis",
                    status="success",
                    duration_seconds=5.2,
                    output_length=150,
                    keyword_hits=2,
                    keyword_total=3,
                ),
            ],
            summary={
                "by_provider": {
                    "codex": {
                        "success_rate": 100.0,
                        "avg_duration": 5.2,
                        "avg_keyword_score": 0.67,
                    }
                },
                "total_runs": 1,
            },
        )
        text = format_report(report)
        assert "Vyane Benchmark Report" in text
        assert "codex" in text
        assert "5.2s" in text
        assert "code_review" in text


class TestSaveReport:
    def test_save_json(self, tmp_path):
        report = BenchmarkReport(
            timestamp="2026-03-07T12:00:00",
            results=[
                BenchmarkResult(provider="codex", status="success"),
            ],
            summary={"total_runs": 1},
        )
        path = str(tmp_path / "results.json")
        save_report(report, path)

        data = json.loads((tmp_path / "results.json").read_text())
        assert data["timestamp"] == "2026-03-07T12:00:00"
        assert len(data["results"]) == 1
        assert data["summary"]["total_runs"] == 1


class TestBenchmarkTasks:
    def test_all_tasks_have_required_fields(self):
        for name, task in BENCHMARK_TASKS.items():
            assert "category" in task, f"{name} missing category"
            assert "description" in task, f"{name} missing description"
            assert "task" in task, f"{name} missing task"
            assert len(task["task"]) > 20, f"{name} task too short"
