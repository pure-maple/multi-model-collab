"""Tests for configuration loading and validation."""

import logging

from modelmux.config import (
    MuxConfig,
    RoutingRule,
    _parse_config,
    _parse_provider_config,
    load_config,
    route_by_rules,
)


def test_parse_config_valid_keys():
    """Valid config keys should not produce warnings."""
    data = {
        "active_profile": "default",
        "routing": {"default_provider": "gemini"},
        "profiles": {},
    }
    config = _parse_config(data)
    assert config.active_profile == "default"
    assert config.default_provider == "gemini"


def test_parse_config_unknown_keys_warns(caplog):
    """Unknown keys should produce a warning."""
    data = {
        "active_profile": "default",
        "defualt_provider": "codex",  # typo
        "roouting": {},  # typo
    }
    with caplog.at_level(logging.WARNING, logger="modelmux.config"):
        config = _parse_config(data)

    assert "defualt_provider" in caplog.text
    assert "roouting" in caplog.text
    # Should still parse valid keys
    assert config.active_profile == "default"


def test_parse_config_all_known_keys_no_warning(caplog):
    """All known keys together should not warn."""
    data = {
        "active_profile": "default",
        "routing": {},
        "disabled_providers": [],
        "caller_override": "",
        "auto_exclude_caller": True,
        "profiles": {},
        "providers": {},
        "notifications": {},
        "workflows": {},
    }
    with caplog.at_level(logging.WARNING, logger="modelmux.config"):
        _parse_config(data)

    assert "Unknown config keys" not in caplog.text


def test_parse_provider_config():
    """ProviderConfig should parse all fields."""
    pc = _parse_provider_config({
        "model": "gpt-5",
        "base_url": "https://api.example.com",
        "api_key_env": "MY_KEY",
    })
    assert pc.model == "gpt-5"
    assert pc.base_url == "https://api.example.com"
    assert pc.api_key_env == "MY_KEY"


def test_routing_rules_match():
    """RoutingRule.matches should score by keyword count."""
    rule = RoutingRule(provider="codex", keywords=["api", "backend"])
    assert rule.matches("build an api backend") == 2
    assert rule.matches("design a ui") == 0


def test_route_by_rules_best_match():
    """route_by_rules should pick the highest scoring rule."""
    rules = [
        RoutingRule(provider="gemini", keywords=["frontend", "ui"]),
        RoutingRule(provider="codex", keywords=["api", "backend", "database"]),
    ]
    assert route_by_rules("build api backend database", rules) == "codex"
    assert route_by_rules("create frontend ui", rules) == "gemini"


def test_route_by_rules_no_match_returns_default():
    """No matching rules should return the default provider."""
    rules = [RoutingRule(provider="codex", keywords=["api"])]
    assert route_by_rules("hello world", rules, default="claude") == "claude"


def test_route_by_rules_empty():
    """Empty rules list returns empty string."""
    assert route_by_rules("anything", []) == ""


def test_load_config_defaults():
    """load_config with no files should return defaults."""
    config = load_config("/nonexistent/path")
    assert config.active_profile == "default"
    assert config.default_provider == "codex"
    assert config.auto_exclude_caller is True


# --- ProviderConfig.to_env_overrides ---


class TestProviderConfigEnvOverrides:
    def test_codex_base_url(self):
        from modelmux.config import ProviderConfig

        pc = ProviderConfig(base_url="https://api.example.com")
        env = pc.to_env_overrides("codex")
        assert env.get("OPENAI_BASE_URL") == "https://api.example.com"

    def test_codex_api_key(self):
        import os

        from modelmux.config import ProviderConfig

        os.environ["TEST_CODEX_KEY"] = "test-secret"
        try:
            pc = ProviderConfig(api_key_env="TEST_CODEX_KEY")
            env = pc.to_env_overrides("codex")
            assert env.get("OPENAI_API_KEY") == "test-secret"
        finally:
            del os.environ["TEST_CODEX_KEY"]

    def test_claude_env(self):
        from modelmux.config import ProviderConfig

        pc = ProviderConfig(
            base_url="https://claude.example.com",
            model="opus",
        )
        env = pc.to_env_overrides("claude")
        assert env.get("ANTHROPIC_BASE_URL") == "https://claude.example.com"
        assert env.get("ANTHROPIC_MODEL") == "opus"

    def test_gemini_env(self):
        from modelmux.config import ProviderConfig

        pc = ProviderConfig(base_url="https://gemini.example.com")
        env = pc.to_env_overrides("gemini")
        assert env.get("GOOGLE_GEMINI_BASE_URL") == "https://gemini.example.com"

    def test_dashscope_env(self):
        from modelmux.config import ProviderConfig

        pc = ProviderConfig(base_url="https://ds.example.com")
        env = pc.to_env_overrides("dashscope")
        assert env.get("DASHSCOPE_BASE_URL") == "https://ds.example.com"

    def test_extra_env(self):
        from modelmux.config import ProviderConfig

        pc = ProviderConfig(extra_env={"CUSTOM_VAR": "value"})
        env = pc.to_env_overrides("codex")
        assert env.get("CUSTOM_VAR") == "value"

    def test_blocked_env_vars(self):
        from modelmux.config import ProviderConfig

        pc = ProviderConfig(
            extra_env={"PATH": "/evil", "HOME": "/root", "OK_VAR": "fine"}
        )
        env = pc.to_env_overrides("codex")
        assert "PATH" not in env
        assert "HOME" not in env
        assert env.get("OK_VAR") == "fine"

    def test_missing_api_key_env(self):
        from modelmux.config import ProviderConfig

        pc = ProviderConfig(api_key_env="NONEXISTENT_KEY_12345")
        env = pc.to_env_overrides("codex")
        assert "OPENAI_API_KEY" not in env

    def test_empty_config(self):
        from modelmux.config import ProviderConfig

        pc = ProviderConfig()
        env = pc.to_env_overrides("codex")
        assert env == {}


# --- RoutingRule extended ---


class TestRoutingRuleExtended:
    def test_file_ext_match(self):
        rule = RoutingRule(provider="codex", file_ext=[".py", ".rs"])
        assert rule.matches("fix bug in main.py") == 1
        assert rule.matches("no extension here") == 0

    def test_regex_match(self):
        rule = RoutingRule(
            provider="gemini", regex=r"\b(security|vuln)"
        )
        assert rule.matches("check for security issues") > 0
        assert rule.matches("add a feature") == 0

    def test_priority_boost(self):
        rule = RoutingRule(
            provider="codex", keywords=["api"], priority=10
        )
        assert rule.matches("build api") == 11  # 1 keyword + 10 priority

    def test_combined_scoring(self):
        rule = RoutingRule(
            provider="codex",
            keywords=["api"],
            file_ext=[".py"],
            priority=5,
        )
        assert rule.matches("fix api in main.py") == 7  # 1+1+5


# --- _find_config_file ---


class TestFindConfigFile:
    def test_finds_toml(self, tmp_path):
        from modelmux.config import _find_config_file

        (tmp_path / "profiles.toml").write_text("")
        result = _find_config_file(tmp_path)
        assert result is not None
        assert result.name == "profiles.toml"

    def test_finds_json(self, tmp_path):
        from modelmux.config import _find_config_file

        (tmp_path / "profiles.json").write_text("{}")
        result = _find_config_file(tmp_path)
        assert result.name == "profiles.json"

    def test_toml_priority_over_json(self, tmp_path):
        from modelmux.config import _find_config_file

        (tmp_path / "profiles.toml").write_text("")
        (tmp_path / "profiles.json").write_text("{}")
        result = _find_config_file(tmp_path)
        assert result.name == "profiles.toml"

    def test_not_found(self, tmp_path):
        from modelmux.config import _find_config_file

        result = _find_config_file(tmp_path)
        assert result is None


# --- _load_file ---


class TestLoadFile:
    def test_load_json(self, tmp_path):
        from modelmux.config import _load_file

        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}')
        data = _load_file(f)
        assert data["key"] == "value"

    def test_load_toml(self, tmp_path):
        from modelmux.config import _load_file

        f = tmp_path / "test.toml"
        f.write_text('key = "value"')
        data = _load_file(f)
        assert data["key"] == "value"

    def test_unsupported_format(self, tmp_path):
        import pytest

        from modelmux.config import _load_file

        f = tmp_path / "test.xml"
        f.write_text("<root/>")
        with pytest.raises(ValueError, match="Unsupported"):
            _load_file(f)


# --- _merge_configs ---


class TestMergeConfigs:
    def test_override_wins(self):
        from modelmux.config import _merge_configs

        base = MuxConfig(
            active_profile="base",
            default_provider="codex",
        )
        override = MuxConfig(
            active_profile="override",
            default_provider="gemini",
        )
        merged = _merge_configs(base, override)
        assert merged.active_profile == "override"
        assert merged.default_provider == "gemini"

    def test_profiles_merged(self):
        from modelmux.config import Profile, _merge_configs

        base = MuxConfig(profiles={"a": Profile(description="A")})
        override = MuxConfig(profiles={"b": Profile(description="B")})
        merged = _merge_configs(base, override)
        assert "a" in merged.profiles
        assert "b" in merged.profiles

    def test_override_profile_wins(self):
        from modelmux.config import Profile, _merge_configs

        base = MuxConfig(
            profiles={"x": Profile(description="base")}
        )
        override = MuxConfig(
            profiles={"x": Profile(description="override")}
        )
        merged = _merge_configs(base, override)
        assert merged.profiles["x"].description == "override"

    def test_routing_rules_override(self):
        from modelmux.config import _merge_configs

        base = MuxConfig(
            routing_rules=[RoutingRule(provider="codex")]
        )
        override = MuxConfig(
            routing_rules=[RoutingRule(provider="gemini")]
        )
        merged = _merge_configs(base, override)
        assert len(merged.routing_rules) == 1
        assert merged.routing_rules[0].provider == "gemini"

    def test_base_rules_when_no_override(self):
        from modelmux.config import _merge_configs

        base = MuxConfig(
            routing_rules=[RoutingRule(provider="codex")]
        )
        override = MuxConfig()
        merged = _merge_configs(base, override)
        assert merged.routing_rules[0].provider == "codex"


# --- get_active_profile ---


class TestGetActiveProfile:
    def test_found(self):
        from modelmux.config import Profile, get_active_profile

        config = MuxConfig(
            active_profile="fast",
            profiles={"fast": Profile(description="Fast mode")},
        )
        prof = get_active_profile(config)
        assert prof is not None
        assert prof.description == "Fast mode"

    def test_not_found(self):
        from modelmux.config import get_active_profile

        config = MuxConfig(active_profile="missing")
        assert get_active_profile(config) is None


# --- _parse_profile ---


class TestParseProfile:
    def test_with_providers(self):
        from modelmux.config import _parse_profile

        data = {
            "description": "Test profile",
            "providers": {
                "codex": {"model": "gpt-5"},
                "gemini": {"model": "gemini-2"},
            },
        }
        prof = _parse_profile(data)
        assert prof.description == "Test profile"
        assert "codex" in prof.providers
        assert prof.providers["codex"].model == "gpt-5"

    def test_skips_non_dict_providers(self):
        from modelmux.config import _parse_profile

        data = {
            "providers": {
                "good": {"model": "x"},
                "bad": "not a dict",
            },
        }
        prof = _parse_profile(data)
        assert "good" in prof.providers
        assert "bad" not in prof.providers

    def test_empty_profile(self):
        from modelmux.config import _parse_profile

        prof = _parse_profile({})
        assert prof.description == ""
        assert prof.providers == {}


# --- _parse_config with profiles and rules ---


class TestParseConfigExtended:
    def test_profiles_parsed(self):
        data = {
            "profiles": {
                "fast": {
                    "description": "Fast mode",
                    "providers": {
                        "codex": {"model": "gpt-4o-mini"},
                    },
                },
            },
        }
        config = _parse_config(data)
        assert "fast" in config.profiles
        prov = config.profiles["fast"].providers["codex"]
        assert prov.model == "gpt-4o-mini"

    def test_routing_rules_parsed(self):
        data = {
            "routing": {
                "rules": [
                    {
                        "provider": "codex",
                        "match": {"keywords": ["api"]},
                    }
                ],
            },
        }
        config = _parse_config(data)
        assert len(config.routing_rules) == 1
        assert config.routing_rules[0].provider == "codex"

    def test_disabled_providers(self):
        data = {"disabled_providers": ["ollama"]}
        config = _parse_config(data)
        assert "ollama" in config.disabled_providers

    def test_caller_override(self):
        data = {"caller_override": "claude"}
        config = _parse_config(data)
        assert config.caller_override == "claude"

    def test_auto_exclude_false(self):
        data = {"auto_exclude_caller": False}
        config = _parse_config(data)
        assert config.auto_exclude_caller is False


# --- load_config with file ---


class TestLoadConfigWithFile:
    def test_loads_project_config(self, tmp_path):
        import json as json_mod

        project = tmp_path / ".modelmux"
        project.mkdir()
        config_file = project / "profiles.json"
        config_file.write_text(
            json_mod.dumps({
                "active_profile": "custom",
                "routing": {"default_provider": "gemini"},
            })
        )
        config = load_config(str(tmp_path))
        assert config.active_profile == "custom"
        assert config.default_provider == "gemini"
