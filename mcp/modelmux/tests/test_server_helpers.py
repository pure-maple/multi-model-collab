"""Tests for server.py helper functions (routing, adapter cache, config helpers)."""

from unittest.mock import MagicMock, patch

from modelmux.adapters.base import BaseAdapter
from modelmux.server import (
    _adapter_cache,
    _auto_route,
    _build_extra_args,
    _get_adapter,
    _get_fallback_candidates,
    _parse_provider_spec,
    _provider_health_summary,
)


class TestAutoRoute:
    def test_rule_match(self):
        config = MagicMock()
        config.routing_rules = [{"pattern": "test", "provider": "gemini"}]
        config.default_provider = "codex"

        with patch(
            "modelmux.server.route_by_rules", return_value="gemini"
        ):
            result = _auto_route(
                "test task", config, ["codex", "gemini"], []
            )
        assert result == "gemini"

    def test_rule_match_excluded(self):
        config = MagicMock()
        config.routing_rules = [{"pattern": "test", "provider": "gemini"}]
        config.default_provider = "codex"

        with patch(
            "modelmux.server.route_by_rules", return_value="gemini"
        ), patch(
            "modelmux.server.smart_route", return_value=("codex", {})
        ):
            result = _auto_route(
                "test task", config, ["codex", "gemini"], ["gemini"]
            )
        assert result == "codex"

    def test_no_rules(self):
        config = MagicMock()
        config.routing_rules = []
        config.default_provider = "codex"

        with patch(
            "modelmux.server.smart_route", return_value=("gemini", {})
        ):
            result = _auto_route(
                "test task", config, ["codex", "gemini"], []
            )
        assert result == "gemini"

    def test_rule_returns_none(self):
        config = MagicMock()
        config.routing_rules = [{"pattern": "x"}]
        config.default_provider = "codex"

        with patch(
            "modelmux.server.route_by_rules", return_value=None
        ), patch(
            "modelmux.server.smart_route", return_value=("codex", {})
        ):
            result = _auto_route(
                "test task", config, ["codex"], []
            )
        assert result == "codex"


class TestGetAdapter:
    def setup_method(self):
        _adapter_cache.clear()

    def teardown_method(self):
        _adapter_cache.clear()

    def test_builtin_class(self):
        adapter = _get_adapter("codex")
        assert isinstance(adapter, BaseAdapter)
        assert adapter.provider_name == "codex"

    def test_caches_adapter(self):
        a1 = _get_adapter("codex")
        a2 = _get_adapter("codex")
        assert a1 is a2

    def test_unknown_raises(self):
        try:
            _get_adapter("nonexistent_provider_xyz")
            assert False, "Should raise"
        except ValueError as e:
            assert "Unknown provider" in str(e)

    def test_custom_instance(self):
        mock_adapter = MagicMock(spec=BaseAdapter)
        with patch(
            "modelmux.server.get_all_adapters",
            return_value={"custom": mock_adapter},
        ):
            result = _get_adapter("custom")
        assert result is mock_adapter


class TestBuildExtraArgs:
    def test_no_profile_no_model(self):
        extra, env = _build_extra_args("codex", "", "", "", None)
        assert extra == {}
        assert env == {}

    def test_model_override(self):
        extra, env = _build_extra_args("codex", "gpt-5", "", "", None)
        assert extra["model"] == "gpt-5"

    def test_profile_for_codex(self):
        extra, env = _build_extra_args("codex", "", "fast", "", None)
        assert extra["profile"] == "fast"

    def test_profile_ignored_for_non_codex(self):
        extra, env = _build_extra_args("gemini", "", "fast", "", None)
        assert "profile" not in extra

    def test_reasoning_effort(self):
        extra, env = _build_extra_args(
            "codex", "", "", "xhigh", None
        )
        assert extra["reasoning_effort"] == "xhigh"

    def test_with_active_profile(self):
        prof = MagicMock()
        provider_conf = MagicMock()
        provider_conf.model = "custom-model"
        provider_conf.wire_api = ""
        provider_conf.to_env_overrides.return_value = {"API_KEY": "xxx"}
        prof.providers = {"codex": provider_conf}

        extra, env = _build_extra_args("codex", "", "", "", prof)
        assert extra["model"] == "custom-model"
        assert env["API_KEY"] == "xxx"

    def test_explicit_model_overrides_profile(self):
        prof = MagicMock()
        provider_conf = MagicMock()
        provider_conf.model = "profile-model"
        provider_conf.wire_api = ""
        provider_conf.to_env_overrides.return_value = {}
        prof.providers = {"codex": provider_conf}

        extra, env = _build_extra_args("codex", "explicit", "", "", prof)
        assert extra["model"] == "explicit"

    def test_profile_with_wire_api(self):
        prof = MagicMock()
        provider_conf = MagicMock()
        provider_conf.model = ""
        provider_conf.wire_api = "openai"
        provider_conf.to_env_overrides.return_value = {}
        prof.providers = {"gemini": provider_conf}

        extra, env = _build_extra_args("gemini", "", "", "", prof)
        assert extra["wire_api"] == "openai"


class TestParseProviderSpec:
    def test_simple_provider(self):
        prov, model = _parse_provider_spec("codex")
        assert prov == "codex"
        assert model == ""

    def test_provider_with_model(self):
        prov, model = _parse_provider_spec("codex/gpt-5")
        assert prov == "codex"
        assert model == "gpt-5"

    def test_provider_with_complex_model(self):
        prov, model = _parse_provider_spec(
            "dashscope/kimi-k2.5-0305"
        )
        assert prov == "dashscope"
        assert model == "kimi-k2.5-0305"

    def test_auto_provider(self):
        prov, model = _parse_provider_spec("auto")
        assert prov == "auto"
        assert model == ""


class TestGetFallbackCandidates:
    def test_default_order(self):
        result = _get_fallback_candidates("codex", [])
        assert result == ["gemini", "claude", "ollama"]

    def test_excludes_current(self):
        result = _get_fallback_candidates("gemini", [])
        assert "gemini" not in result
        assert "codex" in result

    def test_excludes_disabled(self):
        result = _get_fallback_candidates("codex", ["gemini"])
        assert "gemini" not in result
        assert "claude" in result

    def test_custom_priority(self):
        result = _get_fallback_candidates(
            "codex", [], priority=["gemini", "dashscope"]
        )
        assert result == ["gemini", "dashscope"]

    def test_all_excluded(self):
        result = _get_fallback_candidates(
            "codex", ["gemini", "claude", "ollama"]
        )
        assert result == []


class TestProviderHealthSummary:
    def test_no_history(self):
        with patch(
            "modelmux.server.read_history", return_value=[]
        ), patch(
            "modelmux.routing._get_cached", return_value=None
        ), patch("modelmux.routing._set_cached"):
            result = _provider_health_summary()
        assert result == {}

    def test_with_history(self):
        import time

        now = time.time()
        entries = [
            {
                "provider": "codex",
                "status": "success",
                "duration_seconds": 10,
                "ts": now - 60,
            },
            {
                "provider": "codex",
                "status": "error",
                "duration_seconds": 5,
                "ts": now - 30,
            },
        ]
        with patch(
            "modelmux.server.read_history", return_value=entries
        ), patch(
            "modelmux.routing._get_cached", return_value=None
        ), patch("modelmux.routing._set_cached"):
            result = _provider_health_summary()
        assert "codex" in result
        assert "success_rate" in result["codex"]
        assert "avg_latency" in result["codex"]
        assert "last_used_ago" in result["codex"]

    def test_uses_cache(self):
        cached = {"codex": {"last_used_ago": "5s ago"}}
        with patch(
            "modelmux.routing._get_cached", return_value=cached
        ):
            result = _provider_health_summary()
        assert result == cached
