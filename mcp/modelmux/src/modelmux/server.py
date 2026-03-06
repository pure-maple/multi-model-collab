"""modelmux — model multiplexer for multi-model AI collaboration.

Routes tasks to Codex CLI, Gemini CLI, or Claude Code CLI,
returning results in a canonical schema. Supports user-defined profiles for
third-party model configuration and custom routing rules.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
import uuid
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP

from modelmux.a2a import list_patterns as a2a_list_patterns
from modelmux.a2a.engine import CollaborationEngine, EngineConfig
from modelmux.adapters import (
    ADAPTERS,
    BaseAdapter,
    get_all_adapters,
    load_custom_providers,
)
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
from modelmux.routing import smart_route
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


def _auto_route(
    task: str,
    config: MuxConfig,
    available: list[str],
    excluded: list[str],
) -> str:
    """Smart route: custom rules → keyword + history scoring."""
    if config.routing_rules:
        result = route_by_rules(task, config.routing_rules, config.default_provider)
        if result and result not in excluded:
            return result

    best, _ = smart_route(
        task,
        available_providers=available,
        excluded=excluded,
        default=config.default_provider,
    )
    return best


def _get_adapter(provider: str) -> BaseAdapter:
    if provider not in _adapter_cache:
        all_adapters = get_all_adapters()
        adapter_or_cls = all_adapters.get(provider)
        if adapter_or_cls is None:
            raise ValueError(
                f"Unknown provider: {provider}. "
                f"Available: {', '.join(all_adapters.keys())}"
            )
        # Generic instances returned directly; built-in classes instantiated
        if isinstance(adapter_or_cls, BaseAdapter):
            _adapter_cache[provider] = adapter_or_cls
        else:
            _adapter_cache[provider] = adapter_or_cls()
    return _adapter_cache[provider]


def _ensure_custom_providers_loaded() -> None:
    """Load custom providers from user/project config (once)."""
    if getattr(_ensure_custom_providers_loaded, "_done", False):
        return
    _ensure_custom_providers_loaded._done = True  # type: ignore[attr-defined]

    from modelmux.config import _find_config_file, _load_file

    for cfg_dir in [
        Path.home() / ".config" / "modelmux",
        Path.cwd() / ".modelmux",
    ]:
        cfg_file = _find_config_file(cfg_dir)
        if cfg_file:
            try:
                raw = _load_file(cfg_file)
                load_custom_providers(raw)
            except Exception:
                pass


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
    provider: str,
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
            "ollama" (local models via Ollama — use model param to
            specify which, e.g. "deepseek-r1", "llama3.2", "qwen2.5"),
            or "dashscope" (Alibaba Cloud Coding Plan models — use model
            param to specify which, e.g. "qwen3.5-plus", "kimi-k2.5",
            "glm-5", "MiniMax-M2.5", "qwen3-coder-plus").
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
    _ensure_custom_providers_loaded()

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
        all_adapters = get_all_adapters()
        available = [
            name
            for name, a in all_adapters.items()
            if (isinstance(a, BaseAdapter) and a.check_available())
            or (not isinstance(a, BaseAdapter) and a().check_available())
        ]
        actual_provider = _auto_route(task, config, available, excluded)

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

    # Throttled progress callback — writes status at most every 0.5s
    _last_status_write = [0.0]
    _line_count = [0]
    STATUS_WRITE_INTERVAL = 0.5

    def on_progress(msg: str) -> None:
        _line_count[0] += 1
        dispatch_status.output_preview = msg[:200]
        dispatch_status.output_lines = _line_count[0]
        dispatch_status.elapsed_seconds = round(time.time() - start_time, 1)
        now = time.time()
        if now - _last_status_write[0] >= STATUS_WRITE_INTERVAL:
            _last_status_write[0] = now
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
    _ensure_custom_providers_loaded()

    resolved_workdir = str(Path(workdir).resolve())
    config = load_config(resolved_workdir)
    caller, excluded = _detect_and_build_exclusions(ctx, config)

    profile_name = profile or config.active_profile
    active_prof = config.profiles.get(profile_name)

    # Determine which providers to broadcast to
    all_known = get_all_adapters()
    if providers:
        target_providers = [p for p in providers if p in all_known]
    else:
        target_providers = [
            name
            for name, a in all_known.items()
            if name not in excluded
            and (
                (isinstance(a, BaseAdapter) and a.check_available())
                or (not isinstance(a, BaseAdapter) and a().check_available())
            )
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

        # Throttled progress for broadcast
        last_write = [0.0]
        line_count = [0]

        def on_prog(msg: str) -> None:
            line_count[0] += 1
            status_obj.output_preview = msg[:200]
            status_obj.output_lines = line_count[0]
            status_obj.elapsed_seconds = round(time.time() - start_time, 1)
            now = time.time()
            if now - last_write[0] >= 0.5:
                last_write[0] = now
                write_status(status_obj)

        result = await adapter.run(
            prompt=task,
            workdir=resolved_workdir,
            sandbox=sandbox,
            session_id="",
            timeout=timeout,
            extra_args=extra_args if extra_args else None,
            env_overrides=env_overrides if env_overrides else None,
            on_progress=on_prog,
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
    costs: bool = False,
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
        costs: Include cost estimation breakdown (token usage + estimated USD).
    """
    if stats_only:
        stats = get_history_stats(hours=hours, include_costs=costs)
        return json.dumps(stats, indent=2)

    entries = read_history(
        HistoryQuery(
            limit=limit,
            provider=provider,
            status=status,
            hours=hours,
        )
    )

    result: dict = {"count": len(entries), "entries": entries}

    if costs:
        from modelmux.costs import aggregate_costs

        result["costs"] = aggregate_costs(entries)

    return json.dumps(result, indent=2, ensure_ascii=False)


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

        # Throttled progress for workflow steps
        wf_last_write = [0.0]
        wf_line_count = [0]

        def wf_on_prog(msg: str) -> None:
            wf_line_count[0] += 1
            status_obj.output_preview = msg[:200]
            status_obj.output_lines = wf_line_count[0]
            status_obj.elapsed_seconds = round(time.time() - start_time, 1)
            now = time.time()
            if now - wf_last_write[0] >= 0.5:
                wf_last_write[0] = now
                write_status(status_obj)

        result = await adapter.run(
            prompt=rendered_task,
            workdir=resolved_workdir,
            sandbox=step.sandbox,
            session_id="",
            timeout=step.timeout,
            extra_args=extra_args if extra_args else None,
            on_progress=wf_on_prog,
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
    _ensure_custom_providers_loaded()

    config = load_config(".")
    caller, excluded = _detect_and_build_exclusions(ctx, config)

    all_adapters = get_all_adapters()
    status: dict = {}
    for name, adapter_or_cls in all_adapters.items():
        if isinstance(adapter_or_cls, BaseAdapter):
            adapter = adapter_or_cls
        else:
            adapter = adapter_or_cls()
        info: dict = {
            "available": adapter.check_available(),
            "binary": adapter._binary_name(),
            "excluded": name in excluded,
        }
        if name not in ADAPTERS:
            info["custom"] = True
        status[name] = info

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


@mcp.tool()
async def mux_collaborate(
    task: str,
    pattern: str,
    ctx: Context,
    providers: str = "",
    workdir: str = ".",
    sandbox: Literal["read-only", "write", "full"] = "read-only",
    max_rounds: int = 0,
    timeout: int = 1800,
    list_patterns: bool = False,
) -> str:
    """Run a multi-agent collaboration with iterative feedback loops.

    Unlike mux_dispatch (single prompt) or mux_workflow (linear pipeline),
    mux_collaborate enables TRUE agent-to-agent collaboration where agents
    review each other's work, provide feedback, and iterate until convergence.

    This implements the A2A (Agent-to-Agent) protocol concepts:
    task lifecycle, context continuity, and convergence detection.

    Args:
        task: The goal/task for the collaboration session.
        pattern: Collaboration pattern to use:
            - "review": Implement → Review → Revise loop (codex builds,
              claude reviews, iterate until approved)
            - "consensus": Multi-perspective parallel analysis + synthesis
              (codex/gemini/claude each analyze, then synthesize)
            - "debate": Adversarial debate (advocate vs critic + arbiter verdict)
        providers: Optional role→provider mapping as JSON string, e.g.
            '{"implementer": "codex", "reviewer": "gemini"}'.
            If empty, uses pattern defaults.
        workdir: Working directory for all agents.
        sandbox: Security level for all agent operations.
        max_rounds: Override max collaboration rounds (0 = pattern default).
        timeout: Max wall-clock seconds for entire collaboration (default 1800).
        list_patterns: If True, return available patterns instead of running.
    """
    if list_patterns:
        return json.dumps(a2a_list_patterns(), indent=2, ensure_ascii=False)

    _ensure_custom_providers_loaded()
    resolved_workdir = str(Path(workdir).resolve())

    # Parse provider overrides
    provider_map: dict[str, str] | None = None
    if providers:
        try:
            provider_map = json.loads(providers)
        except json.JSONDecodeError:
            return json.dumps(
                {"status": "error", "error": f"Invalid providers JSON: {providers}"},
                indent=2,
            )

    # Progress reporting via MCP context
    async def on_progress(msg: str) -> None:
        await ctx.info(msg)

    # Sync wrapper for the engine's progress callback
    def sync_progress(msg: str) -> None:
        # Engine calls this synchronously; we log it
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(on_progress(msg))
        except RuntimeError:
            pass

    engine = CollaborationEngine(
        get_adapter=_get_adapter,
        config=EngineConfig(
            workdir=resolved_workdir,
            sandbox=sandbox,
            timeout_per_turn=min(timeout // 3, 600),
            on_progress=sync_progress,
        ),
    )

    await ctx.info(f"Starting '{pattern}' collaboration...")

    collab = await engine.run(
        task=task,
        pattern_name=pattern,
        providers=provider_map,
        max_rounds=max_rounds,
        max_wall_time=timeout,
    )

    # Build result
    result: dict = {
        "task_id": collab.task_id,
        "context_id": collab.context_id,
        "pattern": collab.pattern,
        "state": collab.state.value,
        "rounds": collab.round_count,
        "duration_seconds": round(collab.elapsed_seconds, 1),
        "providers_used": collab.providers,
        "turns": [
            {
                "turn_id": t.turn_id,
                "role": t.role,
                "provider": t.provider,
                "status": t.status,
                "duration": round(t.duration_seconds, 1),
                "output_summary": t.output_summary or t.output[:300],
            }
            for t in collab.turns
        ],
    }

    # Include final output (last successful turn's full output)
    final_turns = [t for t in reversed(collab.turns) if t.status == "success"]
    if final_turns:
        result["final_output"] = final_turns[0].output

    # Include artifacts
    if collab.artifacts:
        result["artifacts"] = [
            {
                "id": a.artifact_id,
                "name": a.name,
                "content": "".join(p.text for p in a.parts)[:2000],
            }
            for a in collab.artifacts
            if a.metadata.get("type") != "trace"
        ]

    # Log to history
    log_result(result, task=task, source="collaborate")

    return json.dumps(result, indent=2, ensure_ascii=False)
