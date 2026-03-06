"""modelmux — model multiplexer for multi-model AI collaboration.

Routes tasks to Codex CLI, Gemini CLI, or Claude Code CLI,
returning results in a canonical schema. Supports user-defined profiles for
third-party model configuration and custom routing rules.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP

from modelmux.adapters import ADAPTERS, BaseAdapter
from modelmux.audit import AuditEntry, count_recent, get_audit_stats, log_dispatch
from modelmux.config import (
    MuxConfig,
    load_config,
    route_by_rules,
)
from modelmux.detect import CallerInfo, detect_caller, get_excluded_providers
from modelmux.policy import check_policy, load_policy

mcp = FastMCP(
    "modelmux",
    instructions=(
        "modelmux — model multiplexer. Use mux_dispatch to send "
        "tasks to different AI models (codex, gemini, claude) and receive "
        "structured results. Use provider='auto' for smart routing. "
        "Supports profiles for third-party model configuration and "
        "session continuity for multi-turn conversations."
    ),
)

# Adapter instances (lazy-initialized)
_adapter_cache: dict[str, BaseAdapter] = {}

# Built-in auto-routing keyword patterns (fallback when no custom rules)
_ROUTE_PATTERNS: dict[str, list[re.Pattern]] = {
    "gemini": [
        re.compile(
            r"\b(frontend|ui|ux|css|html|react|vue|svelte|angular|tailwind|"
            r"component|layout|responsive|style|theme|dashboard|"
            r"page|widget|modal|button|form|animation|figma|"
            r"visual|color|font|icon|image|illustration)\b",
            re.I,
        ),
    ],
    "codex": [
        re.compile(
            r"\b(implement|algorithm|backend|api|endpoint|database|sql|"
            r"debug|fix|bug|optimize|refactor|function|class|test|"
            r"server|middleware|auth|crud|migration|schema|query|"
            r"sort|search|tree|graph|linked.?list|hash|cache)\b",
            re.I,
        ),
    ],
    "claude": [
        re.compile(
            r"\b(architect|design.?pattern|review|analyze|explain|"
            r"trade.?off|compare|evaluate|plan|strategy|"
            r"security|audit|vulnerabilit|threat|"
            r"documentation|spec|rfc|adr|critique)\b",
            re.I,
        ),
    ],
}


def _builtin_auto_route(task: str) -> str:
    """Built-in keyword routing (fallback when no custom rules)."""
    scores: dict[str, int] = {}
    for provider, patterns in _ROUTE_PATTERNS.items():
        score = sum(len(p.findall(task)) for p in patterns)
        scores[provider] = score

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "codex"
    return best


def _auto_route(task: str, config: MuxConfig) -> str:
    """Route using custom rules first, then built-in patterns as fallback."""
    if config.routing_rules:
        result = route_by_rules(task, config.routing_rules, config.default_provider)
        if result:
            return result

    return _builtin_auto_route(task)


def _get_adapter(provider: str) -> BaseAdapter:
    if provider not in _adapter_cache:
        cls = ADAPTERS.get(provider)
        if cls is None:
            raise ValueError(
                f"Unknown provider: {provider}. Available: {', '.join(ADAPTERS.keys())}"
            )
        _adapter_cache[provider] = cls()
    return _adapter_cache[provider]


def _detect_and_build_exclusions(
    ctx: Context,
    config: MuxConfig,
) -> tuple[CallerInfo, list[str]]:
    """Detect caller and build the combined exclusion list."""
    session = ctx.session if ctx._request_context else None
    caller = detect_caller(
        session=session,
        config_override=config.caller_override,
    )

    excluded = list(config.disabled_providers)
    if config.auto_exclude_caller:
        for p in get_excluded_providers(caller):
            if p not in excluded:
                excluded.append(p)

    return caller, excluded


def _build_extra_args(
    actual_provider: str,
    model: str,
    profile: str,
    reasoning_effort: str,
    active_prof: object | None,
) -> tuple[dict, dict[str, str]]:
    """Build extra_args and env_overrides from profile + explicit params."""
    extra_args: dict = {}
    env_overrides: dict[str, str] = {}

    if active_prof:
        provider_conf = active_prof.providers.get(actual_provider)
        if provider_conf:
            if provider_conf.model and not model:
                extra_args["model"] = provider_conf.model
            if provider_conf.wire_api:
                extra_args["wire_api"] = provider_conf.wire_api
            env_overrides = provider_conf.to_env_overrides(actual_provider)

    if model:
        extra_args["model"] = model
    if profile and actual_provider == "codex":
        extra_args["profile"] = profile
    if reasoning_effort:
        extra_args["reasoning_effort"] = reasoning_effort

    return extra_args, env_overrides


def _get_fallback_candidates(
    current: str,
    excluded: list[str],
    priority: list[str] | None = None,
) -> list[str]:
    """Return available provider names to try as fallback, in order."""
    order = priority or ["codex", "gemini", "claude"]
    return [p for p in order if p != current and p not in excluded]


@mcp.tool()
async def mux_dispatch(
    provider: Literal["auto", "codex", "gemini", "claude"],
    task: str,
    ctx: Context,
    workdir: str = ".",
    sandbox: Literal["read-only", "write", "full"] = "read-only",
    session_id: str = "",
    timeout: int = 300,
    model: str = "",
    profile: str = "",
    reasoning_effort: str = "",
    failover: bool = True,
) -> str:
    """Dispatch a task to an AI model CLI and return the result.

    Args:
        provider: Which model to use — "auto" (smart routing based on task
            and user config, auto-excludes the calling platform), "codex"
            (code generation, algorithms, debugging), "gemini" (frontend,
            design, multimodal), or "claude" (architecture, reasoning, review).
        task: The task description / prompt to send to the model.
        workdir: Working directory for the model to operate in.
        sandbox: Security level — "read-only" (default, safe), "write"
            (can modify files), "full" (unrestricted, dangerous).
        session_id: Resume a previous session for multi-turn conversation.
            Pass the session_id from a previous result to continue.
        timeout: Maximum seconds to wait (default 300).
        model: Override the specific model version (e.g., "gpt-5.4",
            "gemini-2.5-pro", "claude-sonnet-4-6"). If empty, uses
            the CLI's default or the active profile's model setting.
        profile: Named profile from user config (e.g., "budget", "china").
            Overrides active_profile from config file. Controls which
            model/provider/base_url to use for each CLI.
        reasoning_effort: Codex reasoning effort level — "low", "medium",
            "high", "xhigh". Only applies to provider="codex".
        failover: Auto-retry with another provider on execution error
            (default True). Disabled when session_id is set (sessions
            are provider-specific).
    """
    # Load user configuration
    resolved_workdir = str(Path(workdir).resolve())
    config = load_config(resolved_workdir)

    # Detect caller and build exclusion list
    caller, excluded = _detect_and_build_exclusions(ctx, config)

    # Determine which profile to use
    profile_name = profile or config.active_profile
    active_prof = config.profiles.get(profile_name)

    # Auto-route if needed
    actual_provider = provider
    if provider == "auto":
        actual_provider = _auto_route(task, config)
        if actual_provider in excluded:
            for alt in _get_fallback_candidates(actual_provider, excluded):
                actual_provider = alt
                break

    # Warn if explicitly dispatching to self
    if provider != "auto" and provider in excluded and caller.provider == provider:
        await ctx.warning(
            f"Dispatching to '{provider}' which appears to be the caller. "
            f"This may cause a self-dispatch loop."
        )

    # Policy check
    policy = load_policy()
    policy_result = check_policy(
        policy,
        provider=actual_provider,
        sandbox=sandbox,
        timeout=timeout,
        calls_last_hour=count_recent(1.0),
        calls_last_day=count_recent(24.0),
    )
    if not policy_result.allowed:
        return json.dumps(
            {
                "run_id": "",
                "provider": actual_provider,
                "status": "blocked",
                "error": f"Policy denied: {policy_result.reason}",
            },
            indent=2,
        )

    adapter = _get_adapter(actual_provider)

    # Check binary availability with fallback
    if not adapter.check_available():
        candidates = _get_fallback_candidates(actual_provider, excluded)
        found = False
        for fb_name in candidates:
            fb_adapter = _get_adapter(fb_name)
            if fb_adapter.check_available():
                await ctx.info(
                    f"{actual_provider} CLI not found, falling back to {fb_name}"
                )
                actual_provider = fb_name
                adapter = fb_adapter
                found = True
                break
        if not found:
            return json.dumps(
                {
                    "run_id": "",
                    "provider": actual_provider,
                    "status": "error",
                    "error": (
                        f"{actual_provider} CLI is not installed or not on PATH."
                        if provider != "auto"
                        else "No model CLIs available on PATH."
                    ),
                },
                indent=2,
            )

    # Build extra_args
    extra_args, env_overrides = _build_extra_args(
        actual_provider, model, profile, reasoning_effort, active_prof
    )

    # Progress callback via MCP context
    progress_messages: list[str] = []

    def on_progress(msg: str) -> None:
        progress_messages.append(msg)

    await ctx.info(f"Dispatching to {actual_provider}...")

    result = await adapter.run(
        prompt=task,
        workdir=resolved_workdir,
        sandbox=sandbox,
        session_id=session_id,
        timeout=timeout,
        extra_args=extra_args if extra_args else None,
        env_overrides=env_overrides if env_overrides else None,
        on_progress=on_progress,
    )

    # Execution failover: if the primary provider errored, try alternatives.
    # Skip failover for: timeouts (already waited), sessions (provider-specific),
    # or when failover is disabled.
    failover_from = ""
    can_failover = failover and result.status == "error" and not session_id
    if can_failover:
        candidates = _get_fallback_candidates(actual_provider, excluded)
        for fb_name in candidates:
            fb_adapter = _get_adapter(fb_name)
            if not fb_adapter.check_available():
                continue

            await ctx.info(
                f"{actual_provider} failed ({result.error}), retrying with {fb_name}..."
            )
            failover_from = actual_provider

            fb_extra, fb_env = _build_extra_args(
                fb_name, model, profile, reasoning_effort, active_prof
            )
            fb_result = await fb_adapter.run(
                prompt=task,
                workdir=resolved_workdir,
                sandbox=sandbox,
                session_id="",
                timeout=timeout,
                extra_args=fb_extra if fb_extra else None,
                env_overrides=fb_env if fb_env else None,
                on_progress=on_progress,
            )
            if fb_result.status != "error":
                actual_provider = fb_name
                adapter = fb_adapter
                result = fb_result
                break

    result_dict = result.to_dict()
    if provider == "auto":
        result_dict["routed_from"] = "auto"
        if caller.provider:
            result_dict["caller_excluded"] = caller.provider
    if failover_from:
        result_dict["failover_from"] = failover_from
    if profile_name != "default" and active_prof:
        result_dict["profile"] = profile_name

    # Audit logging
    log_dispatch(
        AuditEntry(
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            provider=actual_provider,
            task_summary=task[:200],
            status=result.status,
            duration_seconds=result.duration_seconds,
            caller=caller.client_name,
            caller_platform=caller.platform,
            routed_from="auto" if provider == "auto" else "",
            profile=profile_name if profile_name != "default" else "",
            sandbox=sandbox,
            model=extra_args.get("model", ""),
            session_id=result.session_id,
            error=result.error,
        )
    )

    return json.dumps(result_dict, indent=2, ensure_ascii=False)


@mcp.tool()
async def mux_check(ctx: Context) -> str:
    """Check which model CLIs are available and show active configuration.

    Returns availability status for codex, gemini, and claude CLIs,
    the active profile, detected caller platform, and excluded providers.
    """
    config = load_config(".")
    caller, excluded = _detect_and_build_exclusions(ctx, config)

    status: dict = {}
    for name, cls in ADAPTERS.items():
        adapter = cls()
        status[name] = {
            "available": adapter.check_available(),
            "binary": adapter._binary_name(),
            "excluded": name in excluded,
        }

    status["_caller"] = {
        "client_name": caller.client_name,
        "client_version": caller.client_version,
        "provider": caller.provider,
        "platform": caller.platform,
        "detection_method": caller.detection_method,
    }

    status["_config"] = {
        "active_profile": config.active_profile,
        "available_profiles": list(config.profiles.keys()) or ["default (built-in)"],
        "custom_routing_rules": len(config.routing_rules),
        "disabled_providers": config.disabled_providers,
        "auto_exclude_caller": config.auto_exclude_caller,
        "caller_override": config.caller_override,
    }

    # Policy summary
    policy = load_policy()
    status["_policy"] = {
        "allowed_providers": policy.allowed_providers or ["all"],
        "blocked_providers": policy.blocked_providers,
        "blocked_sandboxes": policy.blocked_sandboxes,
        "max_timeout": policy.max_timeout or "unlimited",
        "max_calls_per_hour": policy.max_calls_per_hour or "unlimited",
        "max_calls_per_day": policy.max_calls_per_day or "unlimited",
    }

    # Audit summary
    status["_audit"] = get_audit_stats()

    return json.dumps(status, indent=2)
