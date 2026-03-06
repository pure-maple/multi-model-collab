"""modelmux — model multiplexer for multi-model AI collaboration.

Routes tasks to Codex CLI, Gemini CLI, or Claude Code CLI,
returning results in a canonical schema. Supports user-defined profiles for
third-party model configuration and custom routing rules.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import re
import time
import uuid
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP

from modelmux.adapters import ADAPTERS, BaseAdapter
from modelmux.audit import AuditEntry, count_recent, get_audit_stats, log_dispatch
from modelmux.compare import compare_results
from modelmux.config import (
    MuxConfig,
    load_config,
    route_by_rules,
)
from modelmux.detect import CallerInfo, detect_caller, get_excluded_providers
from modelmux.history import HistoryQuery, get_history_stats, log_result, read_history
from modelmux.policy import check_policy, load_policy
from modelmux.status import DispatchStatus, list_active, remove_status, write_status
from modelmux.workflow import (
    BUILTIN_WORKFLOWS,
    Workflow,
    parse_workflows,
    render_task,
)

mcp = FastMCP(
    "modelmux",
    instructions=(
        "modelmux — model multiplexer. Use mux_dispatch to send "
        "a task to one AI model, or mux_broadcast to send the same "
        "task to multiple models in parallel for consensus/comparison. "
        "Use provider='auto' for smart routing. "
        "Supports profiles, session continuity, and failover."
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
    order = priority or ["codex", "gemini", "claude", "ollama"]
    return [p for p in order if p != current and p not in excluded]


@mcp.tool()
async def mux_dispatch(
    provider: Literal["auto", "codex", "gemini", "claude", "ollama"],
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
            design, multimodal), "claude" (architecture, reasoning, review),
            or "ollama" (local models via Ollama — use model param to
            specify which, e.g. "deepseek-r1", "llama3.2", "qwen2.5").
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

    # Status tracking for real-time monitoring
    run_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    dispatch_status = DispatchStatus(
        run_id=run_id,
        provider=actual_provider,
        task_summary=task[:200],
        status="running",
        started_at=start_time,
    )
    write_status(dispatch_status)

    # Progress callback via MCP context
    def on_progress(msg: str) -> None:
        dispatch_status.output_preview = msg[:200]
        dispatch_status.elapsed_seconds = round(time.time() - start_time, 1)
        write_status(dispatch_status)

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

    # Execution failover
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

            # Update status for failover
            dispatch_status.provider = fb_name
            dispatch_status.failover_from = actual_provider
            dispatch_status.status = "running"
            write_status(dispatch_status)

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

    # Clean up status file (dispatch complete)
    remove_status(run_id)

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

    # History (full result)
    log_result(result_dict, task=task, source="dispatch")

    return json.dumps(result_dict, indent=2, ensure_ascii=False)


@mcp.tool()
async def mux_broadcast(
    task: str,
    ctx: Context,
    providers: list[str] | None = None,
    workdir: str = ".",
    sandbox: Literal["read-only", "write", "full"] = "read-only",
    timeout: int = 300,
    model: str = "",
    profile: str = "",
    compare: bool = False,
) -> str:
    """Broadcast a task to multiple AI models in parallel and return all results.

    Use this for consensus reviews, multi-perspective analysis, or A/B
    comparisons. All providers run concurrently — much faster than
    sequential mux_dispatch calls.

    Args:
        task: The task description / prompt to send to all models.
        providers: List of providers to use, e.g. ["codex", "gemini"].
            If omitted or empty, auto-selects all available providers
            (excluding the caller platform).
        workdir: Working directory for the models to operate in.
        sandbox: Security level — "read-only" (default), "write", "full".
        timeout: Maximum seconds to wait per provider (default 300).
        model: Override model version for all providers.
        profile: Named profile from user config.
        compare: Add structured comparison analysis (similarity scores,
            speed ranking, unique terms per provider). Default False.
    """
    resolved_workdir = str(Path(workdir).resolve())
    config = load_config(resolved_workdir)
    caller, excluded = _detect_and_build_exclusions(ctx, config)

    profile_name = profile or config.active_profile
    active_prof = config.profiles.get(profile_name)

    # Determine which providers to broadcast to
    if providers:
        target_providers = [p for p in providers if p in ADAPTERS]
    else:
        target_providers = [
            name
            for name in ADAPTERS
            if name not in excluded and _get_adapter(name).check_available()
        ]

    if not target_providers:
        return json.dumps(
            {"status": "error", "error": "No available providers to broadcast to."},
            indent=2,
        )

    # Policy check (use first provider as representative)
    policy = load_policy()
    policy_result = check_policy(
        policy,
        provider=target_providers[0],
        sandbox=sandbox,
        timeout=timeout,
        calls_last_hour=count_recent(1.0),
        calls_last_day=count_recent(24.0),
    )
    if not policy_result.allowed:
        return json.dumps(
            {"status": "blocked", "error": f"Policy denied: {policy_result.reason}"},
            indent=2,
        )

    await ctx.info(
        f"Broadcasting to {len(target_providers)} providers: "
        f"{', '.join(target_providers)}..."
    )

    async def _run_one(provider_name: str) -> dict:
        adapter = _get_adapter(provider_name)
        if not adapter.check_available():
            return {
                "provider": provider_name,
                "status": "error",
                "error": f"{provider_name} CLI not available",
            }

        run_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        status_obj = DispatchStatus(
            run_id=run_id,
            provider=provider_name,
            task_summary=task[:200],
            status="running",
            started_at=start_time,
        )
        write_status(status_obj)

        extra_args, env_overrides = _build_extra_args(
            provider_name, model, profile, "", active_prof
        )

        result = await adapter.run(
            prompt=task,
            workdir=resolved_workdir,
            sandbox=sandbox,
            session_id="",
            timeout=timeout,
            extra_args=extra_args if extra_args else None,
            env_overrides=env_overrides if env_overrides else None,
        )

        remove_status(run_id)

        # Audit
        log_dispatch(
            AuditEntry(
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                provider=provider_name,
                task_summary=task[:200],
                status=result.status,
                duration_seconds=result.duration_seconds,
                caller=caller.client_name,
                caller_platform=caller.platform,
                routed_from="broadcast",
                profile=profile_name if profile_name != "default" else "",
                sandbox=sandbox,
                model=extra_args.get("model", ""),
                session_id=result.session_id,
                error=result.error,
            )
        )

        return result.to_dict()

    results = await asyncio.gather(*[_run_one(p) for p in target_providers])

    broadcast_result: dict = {
        "broadcast": True,
        "providers": target_providers,
        "results": list(results),
        "summary": {
            "total": len(results),
            "success": sum(1 for r in results if r["status"] == "success"),
            "error": sum(1 for r in results if r["status"] != "success"),
        },
    }

    if compare:
        broadcast_result["comparison"] = compare_results(list(results))

    # History (full broadcast result)
    log_result(broadcast_result, task=task, source="broadcast")

    return json.dumps(broadcast_result, indent=2, ensure_ascii=False)


@mcp.tool()
async def mux_history(
    ctx: Context,
    limit: int = 20,
    provider: str = "",
    status: str = "",
    hours: float = 0,
    stats_only: bool = False,
) -> str:
    """Query dispatch history and analytics.

    Returns recent dispatch results with full output, or aggregated
    statistics when stats_only=True.

    Args:
        limit: Max number of entries to return (default 20).
        provider: Filter by provider name (e.g. "codex").
        status: Filter by status ("success" or "error").
        hours: Only include entries from the last N hours (0 = all time).
        stats_only: Return aggregated statistics instead of individual entries.
    """
    if stats_only:
        stats = get_history_stats(hours=hours)
        return json.dumps(stats, indent=2)

    entries = read_history(
        HistoryQuery(
            limit=limit,
            provider=provider,
            status=status,
            hours=hours,
        )
    )

    return json.dumps(
        {"count": len(entries), "entries": entries},
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool()
async def mux_workflow(
    workflow: str,
    task: str,
    ctx: Context,
    workdir: str = ".",
    list_workflows: bool = False,
) -> str:
    """Execute a multi-step workflow pipeline across multiple AI models.

    Workflows chain multiple providers sequentially, where each step
    can reference outputs from previous steps. Use list_workflows=True
    to see available workflows.

    Args:
        workflow: Workflow name (e.g. "review", "consensus").
        task: The input task/prompt that starts the pipeline.
        workdir: Working directory for all steps.
        list_workflows: If True, ignore other params and return
            available workflow definitions.
    """
    resolved_workdir = str(Path(workdir).resolve())

    # Load user-defined workflows + built-ins
    user_file = Path.home() / ".config" / "modelmux"
    from modelmux.config import _find_config_file, _load_file

    user_workflows: dict[str, Workflow] = {}
    for cfg_dir in [user_file, Path(resolved_workdir) / ".modelmux"]:
        cfg_file = _find_config_file(cfg_dir)
        if cfg_file:
            try:
                raw = _load_file(cfg_file)
                user_workflows.update(parse_workflows(raw))
            except Exception:
                pass

    all_workflows = {**BUILTIN_WORKFLOWS, **user_workflows}

    if list_workflows:
        listing = {}
        for name, wf in all_workflows.items():
            listing[name] = {
                "description": wf.description,
                "steps": [{"name": s.name, "provider": s.provider} for s in wf.steps],
            }
        return json.dumps(listing, indent=2, ensure_ascii=False)

    wf = all_workflows.get(workflow)
    if not wf:
        return json.dumps(
            {
                "status": "error",
                "error": f"Unknown workflow: '{workflow}'. "
                f"Available: {', '.join(all_workflows.keys())}",
            },
            indent=2,
        )

    await ctx.info(f"Starting workflow '{workflow}' ({len(wf.steps)} steps)...")

    # Execute steps sequentially
    context: dict[str, str] = {"input": task}
    step_results: list[dict] = []

    for i, step in enumerate(wf.steps, 1):
        rendered_task = render_task(step.task, context)
        provider = step.provider

        await ctx.info(f"Step {i}/{len(wf.steps)}: {step.name} → {provider}...")

        adapter = _get_adapter(provider)
        if not adapter.check_available():
            step_results.append(
                {
                    "step": step.name,
                    "provider": provider,
                    "status": "error",
                    "error": f"{provider} CLI not available",
                }
            )
            context[step.name] = f"[ERROR: {provider} not available]"
            continue

        run_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        status_obj = DispatchStatus(
            run_id=run_id,
            provider=provider,
            task_summary=f"[{workflow}/{step.name}] {rendered_task[:100]}",
            status="running",
            started_at=start_time,
        )
        write_status(status_obj)

        extra_args: dict = {}
        if step.model:
            extra_args["model"] = step.model

        result = await adapter.run(
            prompt=rendered_task,
            workdir=resolved_workdir,
            sandbox=step.sandbox,
            session_id="",
            timeout=step.timeout,
            extra_args=extra_args if extra_args else None,
        )

        remove_status(run_id)

        # Store output for next steps
        context[step.name] = result.output or result.error or ""

        step_result = result.to_dict()
        step_result["step"] = step.name
        step_results.append(step_result)

        # Audit
        log_dispatch(
            AuditEntry(
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                provider=provider,
                task_summary=rendered_task[:200],
                status=result.status,
                duration_seconds=result.duration_seconds,
                routed_from=f"workflow:{workflow}",
                sandbox=step.sandbox,
                model=step.model,
                error=result.error,
            )
        )

    workflow_result = {
        "workflow": workflow,
        "description": wf.description,
        "steps": step_results,
        "summary": {
            "total_steps": len(step_results),
            "success": sum(1 for r in step_results if r.get("status") == "success"),
            "total_duration": round(
                sum(r.get("duration_seconds", 0) for r in step_results), 1
            ),
        },
    }

    log_result(workflow_result, task=task, source="workflow")

    return json.dumps(workflow_result, indent=2, ensure_ascii=False)


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

    # Active dispatches
    active = list_active()
    if active:
        status["_active_dispatches"] = [
            {
                "run_id": s.run_id,
                "provider": s.provider,
                "task_summary": s.task_summary,
                "elapsed_seconds": round(time.time() - s.started_at, 1),
            }
            for s in active
        ]

    # Audit summary
    status["_audit"] = get_audit_stats()

    return json.dumps(status, indent=2)
