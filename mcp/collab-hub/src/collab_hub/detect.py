"""Caller platform detection for auto-exclusion.

Detects which CLI/IDE is calling collab-hub so the hub can automatically
exclude the caller from auto-routing (prevents self-dispatch loops).

Detection priority:
  1. MCP clientInfo.name from initialize handshake (most reliable)
  2. Environment variables (CLAUDE_CODE, TERM_PROGRAM, etc.)
  3. User config override (caller_override in config)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Mapping from MCP clientInfo.name patterns to our provider names.
# Keys are lowercase substrings to match against clientInfo.name.
_CLIENT_NAME_MAP: dict[str, str] = {
    "claude-code": "claude",
    "claude code": "claude",
    "anthropic": "claude",
    "codex": "codex",
    "openai": "codex",
    "gemini": "gemini",
    "google": "gemini",
}

# IDE clients — detected but not excluded from routing since
# they aren't CLI providers (they're the orchestration layer).
_IDE_CLIENT_NAMES: dict[str, str] = {
    "cursor": "cursor",
    "windsurf": "windsurf",
    "cline": "cline",
    "continue": "continue",
    "vscode": "vscode",
    "zed": "zed",
}

# Environment variable hints for fallback detection.
_ENV_HINTS: list[tuple[str, str]] = [
    # (env_var, provider)
    ("CLAUDE_CODE", "claude"),
    ("ANTHROPIC_AUTH_TOKEN", "claude"),
    ("CODEX_CLI", "codex"),
    ("GEMINI_CLI", "gemini"),
]


@dataclass
class CallerInfo:
    """Detected caller information."""

    client_name: str = ""       # Raw clientInfo.name from MCP
    client_version: str = ""    # clientInfo.version from MCP
    provider: str = ""          # Mapped provider name (claude/codex/gemini)
    platform: str = ""          # Platform type (cli/ide/unknown)
    detection_method: str = ""  # How it was detected


def detect_caller_from_session(session) -> CallerInfo:
    """Detect caller from MCP session's clientInfo.

    Args:
        session: The MCP ServerSession object (ctx.session).
    """
    try:
        client_params = session.client_params
        if client_params is None:
            return CallerInfo(detection_method="none")

        client_info = client_params.clientInfo
        name = client_info.name or ""
        version = getattr(client_info, "version", "")

        info = CallerInfo(
            client_name=name,
            client_version=version,
        )

        name_lower = name.lower()

        # Check CLI providers first
        for pattern, provider in _CLIENT_NAME_MAP.items():
            if pattern in name_lower:
                info.provider = provider
                info.platform = "cli"
                info.detection_method = "mcp_client_info"
                return info

        # Check IDE clients
        for pattern, ide_name in _IDE_CLIENT_NAMES.items():
            if pattern in name_lower:
                info.platform = "ide"
                info.detection_method = "mcp_client_info"
                return info

        info.platform = "unknown"
        info.detection_method = "mcp_client_info"
        return info

    except (AttributeError, TypeError):
        return CallerInfo(detection_method="error")


def detect_caller_from_env() -> CallerInfo:
    """Fallback: detect caller from environment variables."""
    for env_var, provider in _ENV_HINTS:
        if os.environ.get(env_var):
            return CallerInfo(
                provider=provider,
                platform="cli",
                detection_method="env_var",
            )
    return CallerInfo(detection_method="none")


def detect_caller(session=None, config_override: str = "") -> CallerInfo:
    """Detect the calling platform with priority chain.

    Args:
        session: MCP ServerSession (if available).
        config_override: User config override for caller identity.
    """
    # Priority 1: User config override
    if config_override:
        provider = config_override.lower()
        if provider in ("claude", "codex", "gemini"):
            return CallerInfo(
                provider=provider,
                platform="cli",
                detection_method="config_override",
            )

    # Priority 2: MCP clientInfo
    if session is not None:
        info = detect_caller_from_session(session)
        if info.provider or info.platform != "":
            return info

    # Priority 3: Environment variables
    return detect_caller_from_env()


def get_excluded_providers(caller: CallerInfo) -> list[str]:
    """Determine which providers to exclude based on caller identity.

    Only CLI providers are excluded (to prevent self-dispatch).
    IDE callers don't need exclusion since they aren't dispatch targets.
    """
    if caller.platform == "cli" and caller.provider:
        return [caller.provider]
    return []
