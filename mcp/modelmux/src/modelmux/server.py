"""modelmux — model multiplexer for multi-model AI collaboration.

Routes tasks to Codex CLI, Gemini CLI, or Claude Code CLI,
returning results in a canonical schema. Supports user-defined profiles for
third-party model configuration and custom routing rules.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
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
from modelmux.decompose import (
    DECOMPOSE_SYSTEM_PROMPT,
    build_merge_prompt,
    parse_decomposition,
)
from modelmux.detect import CallerInfo, detect_caller, get_excluded_providers
from modelmux.history import HistoryQuery, get_history_stats, log_result, read_history
from modelmux.log import setup_logging
from modelmux.orchestrate import (
    OrchestratedTask,
    OrchestrateError,
    apply_action,
    available_roles,
    create_task,
    normalize_action,
)
from modelmux.orchestrate_store import OrchestrateStore
from modelmux.policy import check_policy, load_policy
from modelmux.routing import classify_intent, smart_route
from modelmux.status import DispatchStatus, list_active, remove_status, write_status
from modelmux.workflow import (
    BUILTIN_WORKFLOWS,
    Workflow,
    parse_workflows,
    render_task,
)

setup_logging()
logger = logging.getLogger(__name__)

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
_orchestrate_store: OrchestrateStore | None = None


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
                logger.warning(
                    "Failed to load custom providers from %s",
                    cfg_file,
                    exc_info=True,
                )


def _provider_health_summary() -> dict[str, dict]:
    """Get per-provider health stats from recent history.

    Returns {provider: {last_used_ago, avg_latency, success_rate}}
    for providers with history data. Uses routing cache.
    """
    from modelmux.routing import _get_cached, _set_cached

    cached = _get_cached("provider_health")
    if cached is not None:
        return cached

    try:
        entries = read_history(HistoryQuery(limit=200, hours=24))
    except Exception:
        return {}

    now = time.time()
    providers: dict[str, dict] = {}

    for entry in entries:
        prov = entry.get("provider", "")
        if not prov:
            continue
        if prov not in providers:
            providers[prov] = {
                "last_ts": 0.0,
                "durations": [],
                "success": 0,
                "total": 0,
            }
        ps = providers[prov]
        ts = entry.get("ts", 0)
        if ts > ps["last_ts"]:
            ps["last_ts"] = ts
        ps["durations"].append(entry.get("duration_seconds", 0))
        ps["total"] += 1
        if entry.get("status") == "success":
            ps["success"] += 1

    result: dict[str, dict] = {}
    for prov, ps in providers.items():
        ago = round(now - ps["last_ts"]) if ps["last_ts"] else 0
        avg_lat = (
            round(
                sum(ps["durations"]) / len(ps["durations"]),
                1,
            )
            if ps["durations"]
            else 0
        )
        rate = (
            round(
                ps["success"] / ps["total"] * 100,
                1,
            )
            if ps["total"]
            else 0
        )
        result[prov] = {
            "last_used_ago": f"{ago}s ago" if ago < 3600 else f"{ago // 3600}h ago",
            "avg_latency": f"{avg_lat}s",
            "success_rate": f"{rate}%",
        }

    _set_cached("provider_health", result)
    return result


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


def _parse_provider_spec(spec: str) -> tuple[str, str]:
    """Parse 'provider/model' into (provider, model) tuple."""
    if "/" in spec:
        provider, model = spec.split("/", 1)
        return provider, model
    return spec, ""


def _get_fallback_candidates(
    current: str,
    excluded: list[str],
    priority: list[str] | None = None,
) -> list[str]:
    """Return available provider names to try as fallback, in order."""
    order = priority or ["codex", "gemini", "claude", "ollama"]
    return [p for p in order if p != current and p not in excluded]


def _get_orchestrate_store() -> OrchestrateStore:
    global _orchestrate_store
    if _orchestrate_store is None:
        _orchestrate_store = OrchestrateStore()
    return _orchestrate_store


def _resolve_orchestrate_entry(
    store: OrchestrateStore,
    *,
    task_id: str = "",
    branch: str = "",
    require_existing_branch: bool = False,
) -> tuple[OrchestratedTask | None, str, str]:
    normalized_task_id = task_id.strip()
    normalized_branch = branch.strip()

    if normalized_task_id:
        entry = store.get(normalized_task_id)
        if entry is None:
            raise OrchestrateError(f"Unknown task_id '{normalized_task_id}'")
        if normalized_branch:
            branch_entry = store.find_by_branch(normalized_branch)
            if branch_entry is None:
                if require_existing_branch:
                    raise OrchestrateError(
                        f"No task found for branch '{normalized_branch}'"
                    )
            elif branch_entry.task_id != entry.task_id:
                raise OrchestrateError("task_id and branch refer to different tasks")
        return entry, normalized_task_id, normalized_branch

    if normalized_branch:
        return (
            store.find_by_branch(normalized_branch),
            normalized_task_id,
            normalized_branch,
        )

    return None, normalized_task_id, normalized_branch


async def _auto_decompose_task(
    task: str,
    planner_provider: str,
    ctx: Context,
    resolved_workdir: str,
    sandbox: str,
    timeout: int,
    model: str,
    profile: str,
    profile_name: str,
    active_prof: object | None,
    caller: CallerInfo,
    excluded: list[str],
) -> str | None:
    """Attempt to decompose a complex task into subtasks.

    Returns the merged result JSON string if decomposition succeeded,
    or None if the task should not be decomposed (falls through to normal dispatch).
    """
    await ctx.info("Analyzing task for decomposition...")

    # Step 1: Ask planner to decompose
    planner_adapter = _get_adapter(planner_provider)
    planner_extra, planner_env = _build_extra_args(
        planner_provider, model, profile, "", active_prof
    )

    planner_prompt = f"{DECOMPOSE_SYSTEM_PROMPT}\n\nTask: {task}"
    planner_result = await planner_adapter.run(
        prompt=planner_prompt,
        workdir=resolved_workdir,
        sandbox="read-only",
        timeout=min(timeout, 120),
        extra_args=planner_extra if planner_extra else None,
        env_overrides=planner_env if planner_env else None,
    )

    if planner_result.status != "success":
        await ctx.info("Decomposition planner failed, falling back to direct dispatch")
        return None

    plan = parse_decomposition(planner_result.output)
    if not plan.should_decompose:
        await ctx.info("Task is simple enough — dispatching directly")
        return None

    await ctx.info(
        f"Decomposed into {len(plan.subtasks)} subtasks: "
        f"{', '.join(s.name for s in plan.subtasks)}"
    )

    # Step 2: Execute subtasks in dependency waves
    all_known = get_all_adapters()
    subtask_results: dict[str, str] = {}
    step_details: list[dict] = []

    for wave_idx, wave in enumerate(plan.execution_order()):
        if len(wave) > 1:
            await ctx.info(
                f"Wave {wave_idx + 1}: running {len(wave)} subtasks in parallel"
            )
        else:
            await ctx.info(f"Wave {wave_idx + 1}: {wave[0].name}")

        async def _run_subtask(subtask):
            # Resolve provider
            sub_provider = subtask.provider
            if sub_provider == "auto" or sub_provider not in all_known:
                sub_provider = planner_provider
            if sub_provider in excluded:
                sub_provider = planner_provider

            sub_adapter = _get_adapter(sub_provider)
            if not sub_adapter.check_available():
                sub_adapter = _get_adapter(planner_provider)
                sub_provider = planner_provider

            # Inject dependency context into the subtask prompt
            sub_prompt = subtask.task
            for dep_name in subtask.depends_on:
                if dep_name in subtask_results:
                    sub_prompt += (
                        f"\n\n--- Context from '{dep_name}' ---\n"
                        f"{subtask_results[dep_name][:2000]}"
                    )

            sub_extra, sub_env = _build_extra_args(
                sub_provider, "", profile, "", active_prof
            )
            result = await sub_adapter.run(
                prompt=sub_prompt,
                workdir=resolved_workdir,
                sandbox=sandbox,
                timeout=timeout,
                extra_args=sub_extra if sub_extra else None,
                env_overrides=sub_env if sub_env else None,
            )
            return subtask.name, sub_provider, result

        wave_results = await asyncio.gather(*[_run_subtask(s) for s in wave])
        for name, sub_prov, result in wave_results:
            subtask_results[name] = result.output if result.status == "success" else ""
            step_details.append(
                {
                    "name": name,
                    "provider": sub_prov,
                    "status": result.status,
                    "duration_seconds": round(result.duration_seconds, 1),
                    "summary": result.summary,
                }
            )

    # Step 3: Merge results
    await ctx.info("Merging subtask results...")
    merge_prompt = build_merge_prompt(task, subtask_results)
    merge_adapter = _get_adapter(planner_provider)
    merge_extra, merge_env = _build_extra_args(
        planner_provider, model, profile, "", active_prof
    )
    merge_result = await merge_adapter.run(
        prompt=merge_prompt,
        workdir=resolved_workdir,
        sandbox="read-only",
        timeout=timeout,
        extra_args=merge_extra if merge_extra else None,
        env_overrides=merge_env if merge_env else None,
    )

    decompose_result = {
        "run_id": str(uuid.uuid4())[:8],
        "provider": planner_provider,
        "status": merge_result.status,
        "summary": merge_result.summary,
        "output": merge_result.output,
        "decomposed": True,
        "subtasks": step_details,
        "duration_seconds": round(
            sum(s["duration_seconds"] for s in step_details)
            + planner_result.duration_seconds
            + merge_result.duration_seconds,
            1,
        ),
    }

    log_result(decompose_result, task=task, source="decompose")

    return json.dumps(decompose_result, indent=2, ensure_ascii=False)


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
    max_retries: int = 1,
    auto_decompose: bool = False,
) -> str:
    """Dispatch a task to an AI model CLI and return the result.

    Args:
        provider: Which model to use — "auto" (smart routing), "codex",
            "gemini", "claude", "ollama", "dashscope", or "provider/model"
            syntax (e.g. "dashscope/kimi-k2.5", "codex/gpt-4.1-mini").
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
        max_retries: Maximum attempts for the same provider before failover
            (default 1 = single attempt, no retry). Uses exponential
            backoff: 2s, 4s, 8s between retries. Useful for transient
            errors (timeouts, rate limits). Max value: 5.
        auto_decompose: Automatically decompose complex tasks into subtasks,
            route each to the best-suited provider, and merge results.
            Uses the selected provider as planner. Default False.
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

    # Parse "provider/model" syntax (e.g. "dashscope/kimi-k2.5")
    base_provider, spec_model = _parse_provider_spec(provider)
    if spec_model and not model:
        model = spec_model

    # Auto-route if needed
    actual_provider = base_provider
    if base_provider == "auto":
        all_adapters = get_all_adapters()
        available = [
            name
            for name, a in all_adapters.items()
            if (isinstance(a, BaseAdapter) and a.check_available())
            or (not isinstance(a, BaseAdapter) and a().check_available())
        ]
        actual_provider = _auto_route(task, config, available, excluded)

    # Warn if explicitly dispatching to self
    is_self_dispatch = (
        base_provider != "auto"
        and actual_provider in excluded
        and caller.provider == actual_provider
    )
    if is_self_dispatch:
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

    # ── Auto-decompose: complex task splitting ──
    if auto_decompose and not session_id:
        decompose_result = await _auto_decompose_task(
            task=task,
            planner_provider=actual_provider,
            ctx=ctx,
            resolved_workdir=resolved_workdir,
            sandbox=sandbox,
            timeout=timeout,
            model=model,
            profile=profile,
            profile_name=profile_name,
            active_prof=active_prof,
            caller=caller,
            excluded=excluded,
        )
        if decompose_result is not None:
            return decompose_result

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

    # Clamp max_retries to [1, 5]
    effective_retries = max(1, min(max_retries, 5))

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

    # Same-provider retry with exponential backoff
    should_retry = (
        result.status in ("error", "timeout")
        and effective_retries > 1
        and not session_id
    )
    if should_retry:
        for attempt in range(2, effective_retries + 1):
            backoff = 2 ** (attempt - 1)  # 2s, 4s, 8s, 16s
            await ctx.info(
                f"Attempt {attempt}/{effective_retries}: "
                f"retrying {actual_provider} in {backoff}s..."
            )
            await asyncio.sleep(backoff)

            dispatch_status.status = "running"
            dispatch_status.output_preview = f"retry #{attempt}"
            write_status(dispatch_status)

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
            if result.status not in ("error", "timeout"):
                break

    # Execution failover to other providers
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

    # Intent classification for analytics
    intent = classify_intent(task)
    result_dict["intent"] = {
        "category": intent.primary.value,
        "confidence": intent.confidence,
        "signals": intent.signals[:5],
    }

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
            Supports "provider/model" syntax for per-provider model
            overrides, e.g. ["dashscope/kimi-k2.5", "dashscope/MiniMax-M2.5"].
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
    # Supports "provider/model" syntax (e.g. "dashscope/kimi-k2.5")
    all_known = get_all_adapters()
    provider_specs: list[tuple[str, str, str]] = []  # (display, base_provider, model)
    if providers:
        for spec in providers:
            base, spec_model = _parse_provider_spec(spec)
            if base in all_known:
                provider_specs.append((spec, base, spec_model))
    else:
        for name, a in all_known.items():
            if name not in excluded and (
                (isinstance(a, BaseAdapter) and a.check_available())
                or (not isinstance(a, BaseAdapter) and a().check_available())
            ):
                provider_specs.append((name, name, ""))

    target_providers = [display for display, _, _ in provider_specs]

    if not target_providers:
        return json.dumps(
            {"status": "error", "error": "No available providers to broadcast to."},
            indent=2,
        )

    # Policy check — validate all target providers
    policy = load_policy()
    calls_hour = count_recent(1.0)
    calls_day = count_recent(24.0)
    for tp in target_providers:
        base_p = tp.split("/", 1)[0] if "/" in tp else tp
        policy_result = check_policy(
            policy,
            provider=base_p,
            sandbox=sandbox,
            timeout=timeout,
            calls_last_hour=calls_hour,
            calls_last_day=calls_day,
        )
        if not policy_result.allowed:
            return json.dumps(
                {
                    "status": "blocked",
                    "error": f"Policy denied provider '{tp}': {policy_result.reason}",
                },
                indent=2,
            )

    await ctx.info(
        f"Broadcasting to {len(target_providers)} providers: "
        f"{', '.join(target_providers)}..."
    )

    async def _run_one(display_name: str, base_provider: str, spec_model: str) -> dict:
        adapter = _get_adapter(base_provider)
        if not adapter.check_available():
            return {
                "provider": display_name,
                "status": "error",
                "error": f"{base_provider} CLI not available",
            }

        run_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        status_obj = DispatchStatus(
            run_id=run_id,
            provider=display_name,
            task_summary=task[:200],
            status="running",
            started_at=start_time,
        )
        write_status(status_obj)

        # Per-spec model override takes precedence over global model param
        effective_model = model or spec_model
        extra_args, env_overrides = _build_extra_args(
            base_provider, effective_model, profile, "", active_prof
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
                provider=display_name,
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

    results = await asyncio.gather(
        *[_run_one(display, base, sm) for display, base, sm in provider_specs]
    )

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
async def mux_orchestrate(
    action: str,
    ctx: Context,
    task: str = "",
    task_id: str = "",
    role: str = "",
    branch: str = "",
    agent: str = "",
    limit: int = 20,
) -> str:
    """Manage Phase 1 orchestration tasks and lifecycle state.

    Args:
        action: One of "plan", "assign", "status", "review", "merge".
        task: Task description used when action="plan".
        task_id: Stored task id, e.g. "T001". Required for assign unless
            a branch can identify the task during review/merge.
        role: Role template used by action="assign".
        branch: Branch name tracked for review/merge state transitions.
        agent: Assigned agent name used by action="assign".
        limit: Max number of tasks returned by status (default 20).
    """
    store = _get_orchestrate_store()

    try:
        normalized = normalize_action(action)

        if normalized == "plan":
            candidate_id = task_id.strip() if task_id else store.next_task_id()
            if not candidate_id:
                raise OrchestrateError("task_id is required")
            if store.get(candidate_id):
                raise OrchestrateError(f"task_id '{candidate_id}' already exists")
            entry = create_task(task, task_id=candidate_id)
            saved = store.upsert(entry)
            await ctx.info(
                f"Planned {saved.task_id} with suggested role {saved.suggested_role}"
            )
            return json.dumps(
                {
                    "status": "success",
                    "action": normalized,
                    "task": saved.to_dict(),
                    "roles": available_roles(),
                    "next_actions": ["assign", "status"],
                },
                indent=2,
                ensure_ascii=False,
            )

        if normalized == "status":
            entry, normalized_task_id, normalized_branch = _resolve_orchestrate_entry(
                store,
                task_id=task_id,
                branch=branch,
                require_existing_branch=True,
            )
            if normalized_task_id:
                if not entry:
                    raise OrchestrateError(f"Unknown task_id '{normalized_task_id}'")
                payload: dict = {
                    "status": "success",
                    "action": normalized,
                    "task": entry.to_dict(),
                }
            elif normalized_branch:
                if not entry:
                    raise OrchestrateError(
                        f"No task found for branch '{normalized_branch}'"
                    )
                payload = {
                    "status": "success",
                    "action": normalized,
                    "task": entry.to_dict(),
                }
            else:
                counts = store.state_counts()
                tasks = [item.to_dict() for item in store.list(limit=max(limit, 1))]
                payload = {
                    "status": "success",
                    "action": normalized,
                    "summary": {
                        "total": sum(counts.values()),
                        "by_state": counts,
                    },
                    "tasks": tasks,
                    "roles": available_roles(),
                }
            return json.dumps(payload, indent=2, ensure_ascii=False)

        entry, _, normalized_branch = _resolve_orchestrate_entry(
            store,
            task_id=task_id,
            branch=branch,
        )
        if entry is None:
            raise OrchestrateError("task_id or an existing branch is required")

        updated = apply_action(
            entry,
            normalized,
            role=role,
            agent=agent,
            branch=normalized_branch,
        )
        saved = store.upsert(updated)
        await ctx.info(f"{saved.task_id}: {normalized} -> {saved.state.value}")
        return json.dumps(
            {
                "status": "success",
                "action": normalized,
                "task": saved.to_dict(),
            },
            indent=2,
            ensure_ascii=False,
        )
    except OrchestrateError as exc:
        return json.dumps(
            {
                "status": "error",
                "action": action.strip().lower(),
                "error": str(exc),
            },
            indent=2,
            ensure_ascii=False,
        )


@mcp.tool()
async def mux_feedback(
    run_id: str,
    rating: int,
    ctx: Context,
    provider: str = "",
    comment: str = "",
    list_recent: bool = False,
) -> str:
    """Submit feedback on a dispatch result to improve routing quality.

    User ratings are aggregated to automatically adjust provider routing
    preferences. Higher-rated providers get routed to more often.

    Args:
        run_id: The run_id from a dispatch result (from mux_dispatch output).
        rating: Quality rating 1-5 (1=terrible, 3=ok, 5=excellent).
        provider: Provider name (auto-detected from run_id if omitted).
        comment: Optional text feedback.
        list_recent: If True, show recent feedback entries instead of submitting.
    """
    from modelmux.feedback import log_feedback, read_feedback
    from modelmux.routing import classify_task

    if list_recent:
        entries = read_feedback(hours=168)  # last week
        return json.dumps(
            {"count": len(entries), "entries": entries[-20:]},
            indent=2,
            ensure_ascii=False,
        )

    if not 1 <= rating <= 5:
        return json.dumps(
            {"status": "error", "error": "Rating must be 1-5"},
            indent=2,
        )

    # Try to auto-detect provider from history if not provided
    if not provider:
        entries = read_history(HistoryQuery(limit=50))
        for entry in entries:
            if entry.get("run_id") == run_id:
                provider = entry.get("provider", "")
                break

    if not provider:
        return json.dumps(
            {
                "status": "error",
                "error": "Could not determine provider. "
                "Please specify provider explicitly.",
            },
            indent=2,
        )

    # Classify the original task if we can find it
    category = ""
    entries = read_history(HistoryQuery(limit=50))
    for entry in entries:
        if entry.get("run_id") == run_id:
            task_text = entry.get("task", "")
            if task_text:
                category = classify_task(task_text)
            break

    log_feedback(
        run_id=run_id,
        provider=provider,
        rating=rating,
        category=category,
        comment=comment,
    )

    await ctx.info(f"Feedback recorded: {provider} rated {rating}/5")
    return json.dumps(
        {
            "status": "success",
            "run_id": run_id,
            "provider": provider,
            "rating": rating,
            "category": category or "(unclassified)",
        },
        indent=2,
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
                logger.warning(
                    "Failed to load workflows from %s",
                    cfg_file,
                    exc_info=True,
                )

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

    # Policy check — validate all providers used in workflow steps
    policy = load_policy()
    calls_hour = count_recent(1.0)
    calls_day = count_recent(24.0)
    for step in wf.steps:
        step_provider = (
            step.provider.split("/", 1)[0] if "/" in step.provider else step.provider
        )
        policy_result = check_policy(
            policy,
            provider=step_provider,
            sandbox="read-only",
            timeout=600,
            calls_last_hour=calls_hour,
            calls_last_day=calls_day,
        )
        if not policy_result.allowed:
            return json.dumps(
                {
                    "status": "blocked",
                    "error": f"Policy denied provider '{step.provider}' "
                    f"in step '{step.name}': {policy_result.reason}",
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
async def mux_check(ctx: Context, diagnose: str = "") -> str:
    """Check which model CLIs are available and show active configuration.

    Returns availability status for codex, gemini, and claude CLIs,
    the active profile, detected caller platform, and excluded providers.

    Args:
        diagnose: Optional task prompt to diagnose routing. When provided,
                  shows the four-signal score breakdown for each provider.
    """
    _ensure_custom_providers_loaded()

    config = load_config(".")
    caller, excluded = _detect_and_build_exclusions(ctx, config)

    all_adapters = get_all_adapters()
    status: dict = {}
    # Get recent dispatch stats per provider for health info
    recent_stats = _provider_health_summary()

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
        # Add health stats if available
        health = recent_stats.get(name)
        if health:
            info["last_used_ago"] = health["last_used_ago"]
            info["avg_latency"] = health["avg_latency"]
            info["recent_success_rate"] = health["success_rate"]
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

    # Routing v4 diagnostics
    from modelmux.feedback import _feedback_file
    from modelmux.routing import _BENCHMARK_FILE

    available_providers = [
        p
        for p, info in status.items()
        if not p.startswith("_") and isinstance(info, dict) and info.get("available")
    ]
    status["_routing"] = {
        "version": "v4",
        "signals": ["keyword", "history", "benchmark", "feedback"],
        "benchmark_data": _BENCHMARK_FILE.exists(),
        "feedback_data": _feedback_file().exists(),
        "available_for_routing": available_providers,
    }

    # Diagnose mode: show four-signal score breakdown for a given prompt
    if diagnose.strip():
        from modelmux.routing import classify_task, smart_route

        diag_candidates = [p for p in available_providers if p not in excluded]
        if diag_candidates:
            # Check routing rules first (same as _auto_route)
            rule_match = ""
            if config.routing_rules:
                rule_result = route_by_rules(
                    diagnose,
                    config.routing_rules,
                    config.default_provider,
                )
                if rule_result and rule_result not in excluded:
                    rule_match = rule_result

            best, scores = smart_route(
                diagnose,
                available_providers,
                excluded=list(excluded),
            )
            category = classify_task(diagnose)

            # If routing rules matched, that overrides smart_route
            if rule_match:
                best = rule_match

            breakdown = {}
            for prov, ps in scores.items():
                breakdown[prov] = {
                    "keyword": round(ps.keyword_score, 3),
                    "history": round(
                        ps.success_rate * 0.7 + ps.latency_score * 0.3,
                        3,
                    ),
                    "benchmark": round(ps.benchmark_score, 3),
                    "feedback": round(ps.feedback_score, 3),
                    "composite": round(ps.composite, 3),
                    "history_calls": ps.history_calls,
                }
            diag_result: dict = {
                "prompt": diagnose[:200],
                "category": category,
                "best_provider": best,
                "scores": breakdown,
            }
            if rule_match:
                diag_result["routing_rule_match"] = rule_match
            status["_diagnose"] = diag_result
        else:
            status["_diagnose"] = {
                "prompt": diagnose[:200],
                "error": "No available providers for routing",
            }

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

    # Policy check — validate all providers in the collaboration
    policy = load_policy()
    calls_hour = count_recent(1.0)
    calls_day = count_recent(24.0)
    providers_to_check: set[str] = set()
    if provider_map:
        for spec in provider_map.values():
            providers_to_check.add(spec.split("/", 1)[0] if "/" in spec else spec)
    else:
        # Check pattern's default preferred_providers
        from modelmux.a2a.patterns import get_pattern as _get_pattern

        pat = _get_pattern(pattern)
        if pat:
            for role_spec in pat.roles.values():
                if role_spec.preferred_provider:
                    providers_to_check.add(role_spec.preferred_provider)
    for prov in providers_to_check:
        policy_result = check_policy(
            policy,
            provider=prov,
            sandbox=sandbox,
            timeout=timeout,
            calls_last_hour=calls_hour,
            calls_last_day=calls_day,
        )
        if not policy_result.allowed:
            return json.dumps(
                {
                    "status": "blocked",
                    "error": f"Policy denied provider '{prov}': {policy_result.reason}",
                },
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
