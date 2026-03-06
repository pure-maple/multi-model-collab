"""Tests for smart routing v2 (keyword + history scoring)."""

import json
import tempfile
import time
from pathlib import Path
from unittest import mock

from modelmux.routing import (
    ProviderScore,
    keyword_scores,
    history_scores,
    smart_route,
)


def test_keyword_scores_backend_task():
    """Backend-heavy task should score codex highest."""
    scores = keyword_scores("implement a REST API endpoint with database query")
    assert scores["codex"] > scores["gemini"]
    assert scores["codex"] > scores["claude"]


def test_keyword_scores_frontend_task():
    """Frontend-heavy task should score gemini highest."""
    scores = keyword_scores("build a responsive dashboard with React components")
    assert scores["gemini"] > scores["codex"]
    assert scores["gemini"] > scores["claude"]


def test_keyword_scores_review_task():
    """Architecture/review task should score claude highest."""
    scores = keyword_scores("review the security architecture and evaluate trade-offs")
    assert scores["claude"] > scores["codex"]
    assert scores["claude"] > scores["gemini"]


def test_keyword_scores_no_match():
    """No keyword matches should return neutral 0.5 for all."""
    scores = keyword_scores("hello world")
    assert all(v == 0.5 for v in scores.values())


def test_keyword_scores_filter_providers():
    """Should only return scores for requested providers."""
    scores = keyword_scores("implement API", providers=["codex", "gemini"])
    assert "codex" in scores
    assert "gemini" in scores
    assert "claude" not in scores


def test_history_scores_no_history():
    """With no history file, all scores should be neutral."""
    with mock.patch("modelmux.routing._read_history_stats", return_value={}):
        scores = history_scores(["codex", "gemini", "claude"])
        for prov, score in scores.items():
            assert score.success_rate == 0.5
            assert score.latency_score == 0.5
            assert score.history_calls == 0


def test_history_scores_with_data():
    """Providers with history should get data-driven scores."""
    mock_stats = {
        "codex": {"calls": 10, "success": 9, "total_duration": 50.0},
        "gemini": {"calls": 10, "success": 5, "total_duration": 100.0},
    }
    with mock.patch("modelmux.routing._read_history_stats", return_value=mock_stats):
        scores = history_scores(["codex", "gemini", "claude"])
        assert scores["codex"].success_rate == 0.9
        assert scores["gemini"].success_rate == 0.5
        # codex is faster → higher latency score
        assert scores["codex"].latency_score > scores["gemini"].latency_score
        # claude has no history → neutral
        assert scores["claude"].success_rate == 0.5


def test_smart_route_keyword_only():
    """With no history, routing should be keyword-driven."""
    with mock.patch("modelmux.routing._read_history_stats", return_value={}):
        best, scores = smart_route(
            "implement a database migration",
            available_providers=["codex", "gemini", "claude"],
        )
        assert best == "codex"


def test_smart_route_history_boosts():
    """History data should boost a provider over a keyword-neutral task."""
    mock_stats = {
        # gemini has great history
        "gemini": {"calls": 20, "success": 19, "total_duration": 40.0},
        # codex has poor history
        "codex": {"calls": 20, "success": 5, "total_duration": 200.0},
    }
    with mock.patch("modelmux.routing._read_history_stats", return_value=mock_stats):
        # Neutral task (no keyword matches) — history should decide
        best, scores = smart_route(
            "do something interesting",
            available_providers=["codex", "gemini"],
        )
        assert best == "gemini"


def test_smart_route_excludes():
    """Excluded providers should not be candidates."""
    with mock.patch("modelmux.routing._read_history_stats", return_value={}):
        best, scores = smart_route(
            "implement API",
            available_providers=["codex", "gemini", "claude"],
            excluded=["codex"],
        )
        assert best != "codex"


def test_smart_route_single_candidate():
    """Single candidate should always be returned."""
    best, scores = smart_route(
        "anything",
        available_providers=["gemini"],
    )
    assert best == "gemini"
    assert scores["gemini"].composite == 1.0


def test_smart_route_default_on_tie():
    """When all scores are equal, default provider should win."""
    with mock.patch("modelmux.routing._read_history_stats", return_value={}):
        best, _ = smart_route(
            "hello world",
            available_providers=["codex", "gemini", "claude"],
            default="claude",
        )
        assert best == "claude"


def test_provider_score_dataclass():
    """ProviderScore should have all expected fields."""
    score = ProviderScore(
        provider="codex",
        keyword_score=0.8,
        success_rate=0.95,
        latency_score=0.7,
        history_calls=42,
        composite=0.85,
    )
    assert score.provider == "codex"
    assert score.composite == 0.85
