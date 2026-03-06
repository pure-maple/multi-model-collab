"""User preference and routing configuration.

Loads profiles and routing rules from:
  1. Project-level: .modelmux/profiles.{json,toml,yaml}  (highest priority)
  2. User-level:    ~/.config/modelmux/profiles.{json,toml,yaml}
  3. Built-in defaults                                      (lowest priority)

Config format is auto-detected by file extension.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Supported config file names (checked in order)
_CONFIG_NAMES = [
    "profiles.toml",
    "profiles.json",
    "profiles.yaml",
    "profiles.yml",
]


@dataclass
class ProviderConfig:
    """Per-provider settings within a profile."""

    model: str = ""
    base_url: str = ""
    api_key_env: str = ""  # Env var name holding the API key
    wire_api: str = ""  # Codex: "responses" or "chat"
    extra_env: dict[str, str] = field(default_factory=dict)

    def to_env_overrides(self, provider: str) -> dict[str, str]:
        """Generate environment variable overrides for subprocess."""
        env: dict[str, str] = {}

        if provider == "codex":
            if self.base_url:
                env["OPENAI_BASE_URL"] = self.base_url
            if self.api_key_env:
                val = os.environ.get(self.api_key_env, "")
                if val:
                    env["OPENAI_API_KEY"] = val
        elif provider == "claude":
            if self.base_url:
                env["ANTHROPIC_BASE_URL"] = self.base_url
            if self.api_key_env:
                val = os.environ.get(self.api_key_env, "")
                if val:
                    env["ANTHROPIC_AUTH_TOKEN"] = val
            if self.model:
                env["ANTHROPIC_MODEL"] = self.model
        elif provider == "gemini":
            if self.base_url:
                env["GOOGLE_GEMINI_BASE_URL"] = self.base_url
            if self.api_key_env:
                val = os.environ.get(self.api_key_env, "")
                if val:
                    env["GEMINI_API_KEY"] = val
        elif provider == "dashscope":
            if self.base_url:
                env["DASHSCOPE_BASE_URL"] = self.base_url
            if self.api_key_env:
                val = os.environ.get(self.api_key_env, "")
                if val:
                    env["DASHSCOPE_CODING_API_KEY"] = val

        env.update(self.extra_env)
        return env


@dataclass
class Profile:
    """A named configuration profile."""

    description: str = ""
    providers: dict[str, ProviderConfig] = field(default_factory=dict)


@dataclass
class RoutingRule:
    """A single routing rule."""

    provider: str = ""
    keywords: list[str] = field(default_factory=list)
    file_ext: list[str] = field(default_factory=list)
    regex: str = ""
    priority: int = 0
    _compiled_regex: re.Pattern | None = field(default=None, repr=False)

    def matches(self, task: str) -> int:
        """Return match score for a task string. 0 = no match."""
        score = 0

        if self.keywords:
            task_lower = task.lower()
            score += sum(1 for kw in self.keywords if kw.lower() in task_lower)

        if self.file_ext:
            score += sum(1 for ext in self.file_ext if ext in task)

        if self.regex:
            if self._compiled_regex is None:
                self._compiled_regex = re.compile(self.regex, re.I)
            score += len(self._compiled_regex.findall(task))

        return score + self.priority


@dataclass
class MuxConfig:
    """Complete configuration state."""

    active_profile: str = "default"
    profiles: dict[str, Profile] = field(default_factory=dict)
    routing_rules: list[RoutingRule] = field(default_factory=list)
    default_provider: str = "codex"
    disabled_providers: list[str] = field(default_factory=list)
    caller_override: str = ""  # Force caller identity (claude/codex/gemini)
    auto_exclude_caller: bool = True  # Auto-exclude detected caller from routing


def _find_config_file(directory: str | Path) -> Path | None:
    """Find the first matching config file in a directory."""
    d = Path(directory)
    for name in _CONFIG_NAMES:
        p = d / name
        if p.exists():
            return p
    return None


def _load_file(path: Path) -> dict[str, Any]:
    """Load a config file (auto-detect format by extension)."""
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")

    if suffix == ".json":
        return json.loads(text)

    if suffix == ".toml":
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        return tomllib.loads(text)

    if suffix in (".yaml", ".yml"):
        try:
            import yaml

            return yaml.safe_load(text) or {}
        except ImportError:
            raise ImportError(
                "PyYAML is required for YAML config files. "
                "Install with: pip install pyyaml"
            )

    raise ValueError(f"Unsupported config format: {suffix}")


def _parse_provider_config(data: dict[str, Any]) -> ProviderConfig:
    return ProviderConfig(
        model=data.get("model", ""),
        base_url=data.get("base_url", ""),
        api_key_env=data.get("api_key_env", ""),
        wire_api=data.get("wire_api", ""),
        extra_env=data.get("extra_env", {}),
    )


def _parse_profile(data: dict[str, Any]) -> Profile:
    providers = {}
    for name, pdata in data.get("providers", {}).items():
        if isinstance(pdata, dict):
            providers[name] = _parse_provider_config(pdata)
    return Profile(
        description=data.get("description", ""),
        providers=providers,
    )


def _parse_routing_rule(data: dict[str, Any]) -> RoutingRule:
    match = data.get("match", {})
    return RoutingRule(
        provider=data.get("provider", ""),
        keywords=match.get("keywords", []),
        file_ext=match.get("file_ext", []),
        regex=match.get("regex", ""),
        priority=data.get("priority", 0),
    )


def _parse_config(data: dict[str, Any]) -> MuxConfig:
    """Parse raw config dict into structured MuxConfig."""
    config = MuxConfig()
    config.active_profile = data.get("active_profile", "default")
    config.default_provider = data.get("routing", {}).get("default_provider", "codex")
    config.disabled_providers = data.get("disabled_providers", [])
    config.caller_override = data.get("caller_override", "")
    config.auto_exclude_caller = data.get("auto_exclude_caller", True)

    for name, pdata in data.get("profiles", {}).items():
        if isinstance(pdata, dict):
            config.profiles[name] = _parse_profile(pdata)

    for rdata in data.get("routing", {}).get("rules", []):
        if isinstance(rdata, dict):
            config.routing_rules.append(_parse_routing_rule(rdata))

    return config


def _merge_configs(base: MuxConfig, override: MuxConfig) -> MuxConfig:
    """Merge override config on top of base (override wins)."""
    merged = MuxConfig()

    # Override wins for scalar fields
    merged.active_profile = override.active_profile or base.active_profile
    merged.default_provider = override.default_provider or base.default_provider
    merged.disabled_providers = (
        override.disabled_providers
        if override.disabled_providers
        else base.disabled_providers
    )

    # Merge profiles (override wins per profile name)
    merged.profiles = {**base.profiles, **override.profiles}

    # Override routing rules if any defined, otherwise use base
    merged.routing_rules = (
        override.routing_rules if override.routing_rules else base.routing_rules
    )

    # Caller detection settings
    merged.caller_override = override.caller_override or base.caller_override
    merged.auto_exclude_caller = (
        override.auto_exclude_caller
        if override.caller_override
        else base.auto_exclude_caller
    )

    return merged


def load_config(workdir: str = ".") -> MuxConfig:
    """Load configuration with priority: project > user > defaults.

    Args:
        workdir: Current working directory (for project-level config).
    """
    config = MuxConfig()

    # User-level config
    user_dir = Path.home() / ".config" / "modelmux"
    user_file = _find_config_file(user_dir)
    if user_file:
        try:
            user_data = _load_file(user_file)
            config = _merge_configs(config, _parse_config(user_data))
        except Exception:
            pass  # Silently skip invalid user config

    # Project-level config
    project_dir = Path(workdir).resolve() / ".modelmux"
    project_file = _find_config_file(project_dir)
    if project_file:
        try:
            project_data = _load_file(project_file)
            config = _merge_configs(config, _parse_config(project_data))
        except Exception:
            pass  # Silently skip invalid project config

    return config


def get_active_profile(config: MuxConfig) -> Profile | None:
    """Get the currently active profile, or None if default."""
    return config.profiles.get(config.active_profile)


def route_by_rules(task: str, rules: list[RoutingRule], default: str = "codex") -> str:
    """Route a task using custom routing rules.

    Returns provider name, or default if no rules match.
    """
    if not rules:
        return ""  # No custom rules, caller should use built-in routing

    best_provider = ""
    best_score = 0

    for rule in rules:
        score = rule.matches(task)
        if score > best_score:
            best_score = score
            best_provider = rule.provider

    return best_provider if best_score > 0 else default
