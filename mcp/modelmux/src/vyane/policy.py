"""Lightweight policy engine for vyane.

Enforces security and usage constraints before dispatch:
  - Provider allowlist/blocklist
  - Sandbox level restrictions
  - Timeout caps
  - Rate limiting (calls per hour/day)

Policy is loaded from ~/.config/vyane/policy.json, with a fallback to
~/.config/modelmux/policy.json during the rename window.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vyane.paths import resolve_user_write_path

logger = logging.getLogger(__name__)


def _policy_file() -> Path:
    return resolve_user_write_path("policy.json")


@dataclass
class Policy:
    """Security and usage policy."""

    # Provider constraints
    allowed_providers: list[str] = field(default_factory=list)  # empty = all
    blocked_providers: list[str] = field(default_factory=list)

    # Sandbox constraints
    blocked_sandboxes: list[str] = field(default_factory=list)  # e.g. ["full"]

    # Timeout cap (0 = no limit)
    max_timeout: int = 0

    # Rate limits (0 = unlimited)
    max_calls_per_hour: int = 0
    max_calls_per_day: int = 0

    # Security scanning config (raw dict from policy.json "security" section)
    security: dict | None = field(default=None, repr=False)


@dataclass
class PolicyResult:
    """Result of a policy check."""

    allowed: bool = True
    reason: str = ""


def load_policy() -> Policy:
    """Load policy from config file. Returns default (permissive) if not found."""
    path = _policy_file()
    if not path.exists():
        return Policy()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _parse_policy(data)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "Failed to parse policy file %s: %s — using permissive default",
            path,
            exc,
        )
        return Policy()


def _parse_policy(data: dict[str, Any]) -> Policy:
    return Policy(
        allowed_providers=data.get("allowed_providers", []),
        blocked_providers=data.get("blocked_providers", []),
        blocked_sandboxes=data.get("blocked_sandboxes", []),
        max_timeout=data.get("max_timeout", 0),
        max_calls_per_hour=data.get("max_calls_per_hour", 0),
        max_calls_per_day=data.get("max_calls_per_day", 0),
        security=data.get("security"),
    )


def check_policy(
    policy: Policy,
    provider: str,
    sandbox: str = "read-only",
    timeout: int = 300,
    calls_last_hour: int = 0,
    calls_last_day: int = 0,
) -> PolicyResult:
    """Check if a dispatch request is allowed by policy.

    Args:
        policy: The loaded policy.
        provider: Target provider name.
        sandbox: Requested sandbox level.
        timeout: Requested timeout seconds.
        calls_last_hour: Number of calls in the last hour (from audit).
        calls_last_day: Number of calls in the last 24 hours (from audit).
    """
    # Provider allowlist
    if policy.allowed_providers and provider not in policy.allowed_providers:
        return PolicyResult(
            allowed=False,
            reason=(
                f"Provider '{provider}' is not in the allowlist. "
                f"Allowed: {', '.join(policy.allowed_providers)}"
            ),
        )

    # Provider blocklist
    if provider in policy.blocked_providers:
        return PolicyResult(
            allowed=False,
            reason=f"Provider '{provider}' is blocked by policy.",
        )

    # Sandbox restriction
    if sandbox in policy.blocked_sandboxes:
        return PolicyResult(
            allowed=False,
            reason=(
                f"Sandbox level '{sandbox}' is blocked by policy. "
                f"Blocked: {', '.join(policy.blocked_sandboxes)}"
            ),
        )

    # Timeout cap
    if policy.max_timeout > 0 and timeout > policy.max_timeout:
        return PolicyResult(
            allowed=False,
            reason=(
                f"Timeout {timeout}s exceeds policy maximum of {policy.max_timeout}s."
            ),
        )

    # Rate limit: per hour
    if policy.max_calls_per_hour > 0 and calls_last_hour >= policy.max_calls_per_hour:
        return PolicyResult(
            allowed=False,
            reason=(
                f"Rate limit exceeded: {calls_last_hour} calls in the last "
                f"hour (limit: {policy.max_calls_per_hour})."
            ),
        )

    # Rate limit: per day
    if policy.max_calls_per_day > 0 and calls_last_day >= policy.max_calls_per_day:
        return PolicyResult(
            allowed=False,
            reason=(
                f"Rate limit exceeded: {calls_last_day} calls in the last "
                f"24 hours (limit: {policy.max_calls_per_day})."
            ),
        )

    return PolicyResult(allowed=True)
