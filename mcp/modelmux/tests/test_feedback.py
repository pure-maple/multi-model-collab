"""Tests for user feedback collection and routing integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from modelmux.routing import invalidate_routing_cache


@pytest.fixture(autouse=True)
def _clear_routing_cache():
    """Clear routing cache before each test to avoid cross-test contamination."""
    invalidate_routing_cache()
    yield
    invalidate_routing_cache()


class TestLogFeedback:
    """Test feedback persistence."""

    def test_basic_log(self, tmp_path):
        from modelmux.feedback import log_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            log_feedback("run-123", "codex", 5)

        entries = [json.loads(l) for l in fb_file.read_text().strip().split("\n")]
        assert len(entries) == 1
        assert entries[0]["run_id"] == "run-123"
        assert entries[0]["provider"] == "codex"
        assert entries[0]["rating"] == 5

    def test_with_category_and_comment(self, tmp_path):
        from modelmux.feedback import log_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            log_feedback("run-456", "gemini", 3, category="analysis", comment="decent")

        entries = [json.loads(l) for l in fb_file.read_text().strip().split("\n")]
        assert entries[0]["category"] == "analysis"
        assert entries[0]["comment"] == "decent"

    def test_invalid_rating_rejected(self, tmp_path):
        from modelmux.feedback import log_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            with pytest.raises(ValueError):
                log_feedback("run-789", "codex", 0)
            with pytest.raises(ValueError):
                log_feedback("run-789", "codex", 6)

    def test_multiple_entries(self, tmp_path):
        from modelmux.feedback import log_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            log_feedback("run-1", "codex", 5)
            log_feedback("run-2", "gemini", 2)
            log_feedback("run-3", "codex", 4)

        entries = [json.loads(l) for l in fb_file.read_text().strip().split("\n")]
        assert len(entries) == 3


class TestReadFeedback:
    """Test feedback querying."""

    def test_read_all(self, tmp_path):
        from modelmux.feedback import log_feedback, read_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            log_feedback("run-1", "codex", 5)
            log_feedback("run-2", "gemini", 3)
            entries = read_feedback()

        assert len(entries) == 2

    def test_filter_by_provider(self, tmp_path):
        from modelmux.feedback import log_feedback, read_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            log_feedback("run-1", "codex", 5)
            log_feedback("run-2", "gemini", 3)
            log_feedback("run-3", "codex", 4)
            entries = read_feedback(provider="codex")

        assert len(entries) == 2
        assert all(e["provider"] == "codex" for e in entries)

    def test_empty_file(self, tmp_path):
        from modelmux.feedback import read_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            entries = read_feedback()

        assert entries == []


class TestFeedbackScores:
    """Test feedback score computation for routing."""

    def test_basic_scores(self, tmp_path):
        from modelmux.feedback import feedback_scores, log_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            # codex gets high ratings
            log_feedback("r1", "codex", 5)
            log_feedback("r2", "codex", 4)
            # gemini gets low ratings
            log_feedback("r3", "gemini", 2)
            log_feedback("r4", "gemini", 1)

            scores = feedback_scores(["codex", "gemini"])

        assert scores["codex"] > scores["gemini"]
        # codex avg: 4.5/5 = 0.9
        assert abs(scores["codex"] - 0.9) < 0.01
        # gemini avg: 1.5/5 = 0.3
        assert abs(scores["gemini"] - 0.3) < 0.01

    def test_neutral_for_no_feedback(self, tmp_path):
        from modelmux.feedback import feedback_scores

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            scores = feedback_scores(["codex", "gemini"])

        assert scores["codex"] == 0.5
        assert scores["gemini"] == 0.5

    def test_neutral_for_insufficient_data(self, tmp_path):
        from modelmux.feedback import feedback_scores, log_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            log_feedback("r1", "codex", 5)  # only 1 rating
            scores = feedback_scores(["codex", "gemini"])

        # 1 rating is not enough (need >=2)
        assert scores["codex"] == 0.5
        assert scores["gemini"] == 0.5

    def test_category_filter(self, tmp_path):
        from modelmux.feedback import feedback_scores, log_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            log_feedback("r1", "codex", 5, category="generation")
            log_feedback("r2", "codex", 5, category="generation")
            log_feedback("r3", "codex", 1, category="analysis")
            log_feedback("r4", "codex", 1, category="analysis")

            gen_scores = feedback_scores(["codex"], category="generation")
            ana_scores = feedback_scores(["codex"], category="analysis")

        assert gen_scores["codex"] > ana_scores["codex"]

    def test_perfect_score(self, tmp_path):
        from modelmux.feedback import feedback_scores, log_feedback

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            log_feedback("r1", "codex", 5)
            log_feedback("r2", "codex", 5)
            log_feedback("r3", "codex", 5)

            scores = feedback_scores(["codex"])

        assert abs(scores["codex"] - 1.0) < 0.01


class TestRoutingWithFeedback:
    """Test that feedback integrates into smart_route."""

    def test_feedback_influences_routing(self, tmp_path):
        from modelmux.feedback import log_feedback
        from modelmux.routing import smart_route

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            # Give gemini consistently high feedback for frontend tasks
            for i in range(5):
                log_feedback(f"r{i}", "gemini", 5, category="generation")
                log_feedback(f"r{i+10}", "codex", 2, category="generation")

            best, scores = smart_route(
                "create a React component",
                ["codex", "gemini"],
            )

        # gemini should rank higher due to both keyword match and feedback
        assert scores["gemini"].feedback_score > scores["codex"].feedback_score

    def test_no_feedback_neutral(self, tmp_path):
        from modelmux.routing import smart_route

        fb_file = tmp_path / "feedback.jsonl"
        with patch("modelmux.feedback._feedback_file", return_value=fb_file):
            _, scores = smart_route(
                "implement an algorithm",
                ["codex", "gemini"],
            )

        # Both should have neutral feedback scores
        assert scores["codex"].feedback_score == 0.5
        assert scores["gemini"].feedback_score == 0.5
