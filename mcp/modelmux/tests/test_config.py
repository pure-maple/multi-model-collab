"""Tests for configuration loading and validation."""

import logging

from modelmux.config import (
    MuxConfig,
    _parse_config,
    _parse_provider_config,
    load_config,
    route_by_rules,
    RoutingRule,
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
