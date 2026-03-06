"""Tests for the modelmux web dashboard."""

import json
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from modelmux.dashboard import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestDashboardIndex:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "modelmux Dashboard" in resp.text

    def test_index_contains_api_calls(self, client):
        resp = client.get("/")
        assert "/api/status" in resp.text
        assert "/api/history" in resp.text
        assert "/api/providers" in resp.text


class TestApiStatus:
    def test_empty_status(self, client):
        with patch("modelmux.status.list_active", return_value=[]):
            resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        assert data["count"] == 0

    def test_status_with_active_dispatch(self, client):
        from modelmux.status import DispatchStatus

        mock_dispatch = DispatchStatus(
            run_id="test-123",
            provider="codex",
            task_summary="review code",
            status="running",
            started_at=1000000.0,
        )
        with patch(
            "modelmux.status.list_active", return_value=[mock_dispatch]
        ):
            resp = client.get("/api/status")
        data = resp.json()
        assert data["count"] == 1
        assert data["active"][0]["provider"] == "codex"
        assert data["active"][0]["run_id"] == "test-123"


class TestApiHistory:
    def test_empty_history(self, client):
        with patch("modelmux.history.read_history", return_value=[]):
            resp = client.get("/api/history")
        data = resp.json()
        assert data["count"] == 0
        assert data["entries"] == []

    def test_history_with_entries(self, client):
        mock_entries = [
            {"ts": 1000, "provider": "gemini", "status": "success", "task": "test"},
        ]
        with patch("modelmux.history.read_history", return_value=mock_entries):
            resp = client.get("/api/history?limit=5&provider=gemini")
        data = resp.json()
        assert data["count"] == 1
        assert data["entries"][0]["provider"] == "gemini"

    def test_history_query_params(self, client):
        """Verify query params are passed through."""
        captured = {}

        def mock_read(query):
            captured["limit"] = query.limit
            captured["provider"] = query.provider
            captured["hours"] = query.hours
            return []

        with patch("modelmux.history.read_history", side_effect=mock_read):
            client.get("/api/history?limit=5&provider=codex&hours=24")
        assert captured["limit"] == 5
        assert captured["provider"] == "codex"
        assert captured["hours"] == 24.0


class TestApiStats:
    def test_empty_stats(self, client):
        with patch(
            "modelmux.history.get_history_stats",
            return_value={"total": 0},
        ):
            resp = client.get("/api/stats")
        data = resp.json()
        assert data["total"] == 0

    def test_stats_with_data(self, client):
        mock_stats = {
            "total": 42,
            "by_provider": {
                "codex": {
                    "calls": 20,
                    "success": 18,
                    "error": 2,
                    "success_rate": 90.0,
                    "avg_duration": 15.3,
                }
            },
            "by_source": {"dispatch": 30, "broadcast": 12},
        }
        with patch(
            "modelmux.history.get_history_stats", return_value=mock_stats
        ):
            resp = client.get("/api/stats")
        data = resp.json()
        assert data["total"] == 42
        assert data["by_provider"]["codex"]["calls"] == 20


class TestApiProviders:
    def test_providers_lists_builtins(self, client):
        resp = client.get("/api/providers")
        data = resp.json()
        assert "providers" in data
        # At minimum, built-in providers should be listed
        for name in ["codex", "gemini", "claude", "ollama", "dashscope"]:
            assert name in data["providers"]
            assert data["providers"][name]["builtin"] is True

    def test_provider_availability_check(self, client):
        resp = client.get("/api/providers")
        data = resp.json()
        # Each provider should have an 'available' boolean
        for info in data["providers"].values():
            assert isinstance(info["available"], bool)


class TestApiCosts:
    def test_empty_costs(self, client):
        with patch(
            "modelmux.history.get_history_stats",
            return_value={"total": 0},
        ):
            resp = client.get("/api/costs")
        data = resp.json()
        assert "costs" in data
        assert "pricing" in data

    def test_costs_includes_pricing_table(self, client):
        with patch(
            "modelmux.history.get_history_stats",
            return_value={"total": 0},
        ):
            resp = client.get("/api/costs")
        data = resp.json()
        assert "codex" in data["pricing"]
        assert "gemini" in data["pricing"]
        assert "dashscope" in data["pricing"]


class TestApiTrends:
    def test_empty_trends(self, client):
        with patch(
            "modelmux.history.get_trends",
            return_value={"buckets": [], "hours": 24, "bucket_minutes": 60},
        ):
            resp = client.get("/api/trends")
        data = resp.json()
        assert data["buckets"] == []

    def test_trends_with_data(self, client):
        mock_trends = {
            "buckets": [
                {
                    "ts": 1000.0,
                    "count": 5,
                    "success": 4,
                    "error": 1,
                    "success_rate": 80.0,
                    "avg_duration": 12.3,
                    "cost": 0.001,
                    "cumulative_cost": 0.001,
                    "by_provider": {"codex": 3, "gemini": 2},
                }
            ],
            "hours": 24,
            "bucket_minutes": 60,
            "total_entries": 5,
        }
        with patch("modelmux.history.get_trends", return_value=mock_trends):
            resp = client.get("/api/trends?hours=24&bucket=60")
        data = resp.json()
        assert len(data["buckets"]) == 1
        assert data["buckets"][0]["count"] == 5
        assert data["buckets"][0]["success_rate"] == 80.0

    def test_trends_query_params(self, client):
        captured = {}

        def mock_trends(hours, bucket_minutes):
            captured["hours"] = hours
            captured["bucket_minutes"] = bucket_minutes
            return {"buckets": [], "hours": hours, "bucket_minutes": bucket_minutes}

        with patch("modelmux.history.get_trends", side_effect=mock_trends):
            client.get("/api/trends?hours=48&bucket=30")
        assert captured["hours"] == 48.0
        assert captured["bucket_minutes"] == 30


class TestApiCollaborations:
    def test_empty_collaborations(self, client):
        with patch("modelmux.history.read_history", return_value=[]):
            resp = client.get("/api/collaborations")
        data = resp.json()
        assert data["count"] == 0
        assert data["collaborations"] == []

    def test_collaborations_with_data(self, client):
        mock_entries = [
            {
                "ts": 1700000000,
                "task_id": "collab-1",
                "pattern": "review",
                "state": "completed",
                "rounds": 2,
                "duration_seconds": 45.0,
                "providers_used": ["codex", "claude"],
                "task": "Implement a rate limiter",
                "turns": [
                    {
                        "turn_id": "t1",
                        "role": "implementer",
                        "provider": "codex",
                        "status": "success",
                        "duration": 15.0,
                        "output_summary": "Implemented sliding window...",
                    },
                    {
                        "turn_id": "t2",
                        "role": "reviewer",
                        "provider": "claude",
                        "status": "success",
                        "duration": 10.0,
                        "output_summary": "CONVERGED: looks good",
                    },
                ],
            }
        ]
        with patch("modelmux.history.read_history", return_value=mock_entries):
            resp = client.get("/api/collaborations")
        data = resp.json()
        assert data["count"] == 1
        c = data["collaborations"][0]
        assert c["pattern"] == "review"
        assert c["state"] == "completed"
        assert len(c["turns"]) == 2
        assert c["turns"][0]["role"] == "implementer"

    def test_collaborations_query_params(self, client):
        captured = {}

        def mock_read(query):
            captured["source"] = query.source
            captured["limit"] = query.limit
            return []

        with patch("modelmux.history.read_history", side_effect=mock_read):
            client.get("/api/collaborations?limit=3")
        assert captured["source"] == "collaborate"
        assert captured["limit"] == 3


class TestParamClamping:
    def test_clamp_int_normal(self):
        from modelmux.dashboard import _clamp_int

        assert _clamp_int("50", 20) == 50

    def test_clamp_int_negative(self):
        from modelmux.dashboard import _clamp_int

        assert _clamp_int("-1", 20) == 1

    def test_clamp_int_overflow(self):
        from modelmux.dashboard import _clamp_int

        assert _clamp_int("999999", 20) == 10000

    def test_clamp_int_invalid(self):
        from modelmux.dashboard import _clamp_int

        assert _clamp_int("abc", 20) == 20

    def test_clamp_float_normal(self):
        from modelmux.dashboard import _clamp_float

        assert _clamp_float("12.5", 0.0) == 12.5

    def test_clamp_float_negative(self):
        from modelmux.dashboard import _clamp_float

        assert _clamp_float("-5", 0.0) == 0.0

    def test_clamp_float_overflow(self):
        from modelmux.dashboard import _clamp_float

        assert _clamp_float("99999", 24.0) == 8760.0

    def test_clamp_float_invalid(self):
        from modelmux.dashboard import _clamp_float

        assert _clamp_float("nan-value", 24.0) == 24.0


class TestCreateApp:
    def test_app_has_all_routes(self):
        app = create_app()
        paths = {r.path for r in app.routes}
        assert "/" in paths
        assert "/api/status" in paths
        assert "/api/history" in paths
        assert "/api/stats" in paths
        assert "/api/providers" in paths
        assert "/api/costs" in paths
        assert "/api/trends" in paths
        assert "/api/collaborations" in paths
