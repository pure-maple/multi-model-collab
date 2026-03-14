"""CLI entry point for vyane.

Usage:
  vyane              Start the MCP server (stdio transport)
  vyane a2a-server   Start the A2A HTTP server
  vyane dispatch     Run a single task via a provider (JSON output)
  vyane broadcast    Broadcast a task to multiple providers in parallel
  vyane feedback     Submit or view user feedback for routing
  vyane init         Interactive configuration wizard
  vyane config       TUI configuration panel (requires vyane[tui])
  vyane check        Quick CLI availability check
  vyane status       Monitor active dispatches in real-time
  vyane history      View dispatch history and statistics
  vyane version      Show version
"""

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _cmd_server() -> None:
    """Start the MCP server."""
    from vyane.server import mcp

    mcp.run(transport="stdio")


def _cmd_init(args: argparse.Namespace) -> None:
    """Run the interactive setup wizard."""
    from vyane.init_wizard import run_wizard

    scope = getattr(args, "scope", "user")
    run_wizard(scope=scope)


def _cmd_config(args: argparse.Namespace) -> None:
    """Launch the TUI configuration panel."""
    try:
        from vyane.tui import run_tui
    except ImportError:
        print(
            "TUI requires the 'textual' package.\n"
            "Install with: pip install vyane[tui]\n"
            "Or run:       uvx --with textual vyane config"
        )
        sys.exit(1)

    scope = getattr(args, "scope", "user")
    run_tui(scope=scope)


def _cmd_check(args: argparse.Namespace) -> None:
    """Quick CLI availability check (no MCP server needed)."""
    import json
    import shutil

    from vyane import __version__
    from vyane.adapters import ADAPTERS

    use_json = getattr(args, "json", False)
    providers_data: dict[str, dict] = {}

    for name, cls in ADAPTERS.items():
        adapter = cls()
        binary = adapter._binary_name()
        path = shutil.which(binary) if binary else None
        is_available = adapter.check_available()
        providers_data[name] = {
            "available": is_available,
            "binary": binary,
            "path": path or "",
        }

    avail_count = sum(1 for p in providers_data.values() if p["available"])

    if use_json:
        output = {
            "version": __version__,
            "providers": providers_data,
            "available_count": avail_count,
        }
        # Add config info to JSON
        try:
            from vyane.config import load_config

            config = load_config()
            output["active_profile"] = config.active_profile
            output["profiles"] = list(config.profiles.keys())
            output["routing_rules"] = len(config.routing_rules)
        except Exception:
            pass
        print(json.dumps(output, indent=2))
    else:
        print(f"Vyane v{__version__}")
        print()
        print("Providers")
        for name, info in providers_data.items():
            if info["available"]:
                detail = info["path"] or "API key set"
                print(f"  \033[0;32m[+]\033[0m {name:10s} {detail}")
            else:
                print(f"  \033[1;33m[-]\033[0m {name:10s} not found")

        # Config summary
        try:
            from vyane.config import load_config

            config = load_config()
            print()
            print("Config")
            if config.profiles:
                names = ", ".join(config.profiles.keys())
                print(f"  Profiles: {names}")
                if config.active_profile != "default":
                    print(f"  Active:   {config.active_profile}")
            if config.routing_rules:
                print(f"  Routing rules: {len(config.routing_rules)}")
        except Exception:
            pass

        # History summary
        try:
            from vyane.history import get_history_stats

            stats = get_history_stats(hours=24)
            if stats.get("total", 0) > 0:
                print()
                print("Last 24h")
                print(f"  Dispatches: {stats['total']}")
                for prov, ps in stats.get("by_provider", {}).items():
                    rate = ps.get("success_rate", 0)
                    print(f"  {prov:8s}  {ps['calls']} calls  {rate:.0f}% ok")
        except Exception:
            pass

        print()


def _cmd_status(args: argparse.Namespace) -> None:
    """Monitor active dispatches."""
    import time

    from vyane.status import list_active

    watch = getattr(args, "watch", False)

    def _render() -> bool:
        active = list_active()
        if not active:
            print("  No active dispatches.")
            return False

        now = time.time()
        for s in active:
            elapsed = round(now - s.started_at, 1)
            icon = "\033[0;33m●\033[0m"  # yellow dot
            if s.failover_from:
                icon = "\033[0;35m↻\033[0m"  # purple retry
            line = (
                f"  {icon} {s.run_id}  "
                f"{s.provider:8s} "
                f"{elapsed:6.1f}s  "
                f"{s.task_summary[:60]}"
            )
            print(line)
            if s.output_preview:
                print(f"    └─ {s.output_preview[:70]}")
        return True

    if watch:
        print("Vyane — Live Dispatch Monitor (Ctrl+C to stop)")
        print("=" * 60)
        try:
            while True:
                # Clear previous output and re-render
                print("\033[2J\033[H", end="")  # clear screen
                print("Vyane — Live Dispatch Monitor")
                print(f"  {time.strftime('%H:%M:%S')}  (Ctrl+C to stop)")
                print("-" * 60)
                _render()
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print("Vyane — Active Dispatches")
        print("-" * 40)
        _render()
        print()


def _cmd_history(args: argparse.Namespace) -> None:
    """Show dispatch history or stats."""
    import json
    import time

    from vyane.history import HistoryQuery, get_history_stats, read_history

    show_costs = getattr(args, "costs", False)
    use_json = getattr(args, "json", False)

    if getattr(args, "stats", False):
        hours = getattr(args, "hours", 0)
        stats = get_history_stats(hours=hours, include_costs=show_costs)

        if use_json:
            print(json.dumps(stats, indent=2, default=str))
            return

        if not stats.get("total"):
            print("  No history data.")
            return

        print("Vyane — History Statistics")
        print("-" * 50)
        print(f"  Total dispatches: {stats['total']}")
        if stats.get("by_source"):
            for src, cnt in stats["by_source"].items():
                print(f"    {src}: {cnt}")
        print()
        for prov, ps in stats.get("by_provider", {}).items():
            rate = ps.get("success_rate", 0)
            avg = ps.get("avg_duration", 0)
            print(
                f"  {prov:10s}  "
                f"{ps['calls']:3d} calls  "
                f"{rate:5.1f}% success  "
                f"avg {avg:.1f}s"
            )

        if show_costs and stats.get("costs"):
            costs = stats["costs"]
            print()
            print("Cost Estimation")
            print("-" * 50)
            print(f"  Entries with token data: {costs['entries_with_usage']}")
            print(
                f"  Total tokens: "
                f"{costs['total_input_tokens']:,} in / "
                f"{costs['total_output_tokens']:,} out"
            )
            print(f"  Estimated cost: ${costs['total_cost_usd']:.4f} USD")
            for cp, cd in costs.get("by_provider", {}).items():
                print(
                    f"    {cp:10s}  "
                    f"{cd['calls']:3d} calls  "
                    f"{cd['input_tokens']:,} in / "
                    f"{cd['output_tokens']:,} out  "
                    f"${cd['total_cost']:.4f}"
                )

        print()
        return

    limit = getattr(args, "limit", 10)
    provider = getattr(args, "provider", "")
    hours = getattr(args, "hours", 0)
    source = getattr(args, "source", "")
    entries = read_history(
        HistoryQuery(limit=limit, provider=provider, hours=hours, source=source)
    )

    if use_json:
        data = {"entries": entries, "count": len(entries)}
        print(json.dumps(data, indent=2, default=str))
        return

    if not entries:
        print("  No history entries found.")
        return

    print("Vyane — Recent Dispatches")
    print("-" * 60)

    _SOURCE_TAGS = {
        "broadcast": "[B]",
        "cli-dispatch": "[C]",
        "cli-broadcast": "[CB]",
        "collaborate": "[A]",
    }

    for entry in entries:
        ts = entry.get("ts", 0)
        ts_str = time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "?"
        prov = entry.get("provider", "?")
        status = entry.get("status", "?")
        dur = entry.get("duration_seconds", 0)
        task_str = entry.get("task", "")[:50]
        src = entry.get("source", "dispatch")

        icon = "\033[0;32m+\033[0m" if status == "success" else "\033[1;31m!\033[0m"
        tag = _SOURCE_TAGS.get(src, "")
        print(f"  {icon} {ts_str}  {prov:10s} {dur:5.1f}s  {tag}{task_str}")
    print()


def _cmd_benchmark(args: argparse.Namespace) -> None:
    """Run the benchmark suite."""
    from vyane.benchmark import (
        BENCHMARK_TASKS,
        format_report,
        run_benchmark,
        save_report,
    )
    from vyane.paths import resolve_user_write_path

    providers = getattr(args, "providers", None)
    task_names = getattr(args, "tasks", None)
    timeout = getattr(args, "timeout", 120)
    output = getattr(args, "output", "")

    if getattr(args, "list_tasks", False):
        print("Available benchmark tasks:")
        for name, info in BENCHMARK_TASKS.items():
            print(f"  {name:20s} [{info['category']}] {info['description']}")
        return

    print("Vyane Benchmark")
    print(f"  Providers: {', '.join(providers) if providers else 'auto-detect'}")
    print(f"  Tasks: {', '.join(task_names) if task_names else 'all'}")
    print(f"  Timeout: {timeout}s")
    print()

    report = run_benchmark(
        providers=providers,
        task_names=task_names,
        timeout=timeout,
    )

    print(format_report(report))

    if output:
        save_report(report, output)
        print(f"\nResults saved to {output}")

    # Always save to routing-readable location for smart routing v3
    routing_path = resolve_user_write_path("benchmark.json")
    routing_path.parent.mkdir(parents=True, exist_ok=True)
    save_report(report, str(routing_path))
    print(f"Routing data updated: {routing_path}")


def _cmd_export(args: argparse.Namespace) -> None:
    """Export history to CSV/JSON/Markdown."""
    from vyane.export import run_export

    fmt = getattr(args, "format", "csv")
    hours = getattr(args, "hours", 0)
    provider = getattr(args, "provider", "")
    limit = getattr(args, "limit", 1000)
    output = getattr(args, "output", "")
    source = getattr(args, "source", "")

    content = run_export(
        fmt=fmt,
        hours=hours,
        provider=provider,
        limit=limit,
        output=output,
        source=source,
    )

    if output:
        print(f"Exported to {output}")
    else:
        print(content)


def _cmd_dashboard(args: argparse.Namespace) -> None:
    """Start the web dashboard."""
    from vyane.dashboard import run_dashboard

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 41521)
    run_dashboard(host=host, port=port)


def _cmd_a2a_server(args: argparse.Namespace) -> None:
    """Start the A2A HTTP server."""
    # Load custom providers
    from pathlib import Path

    from vyane.a2a.http_server import A2AServer
    from vyane.adapters import get_all_adapters, load_custom_providers
    from vyane.adapters.base import BaseAdapter
    from vyane.config import _find_config_file, _load_file, find_user_config_file
    from vyane.paths import resolve_user_write_path

    for cfg_file in [
        find_user_config_file(),
        _find_config_file(Path.cwd() / ".modelmux"),
    ]:
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

    # Adapter resolver
    adapter_cache: dict[str, BaseAdapter] = {}

    def get_adapter(provider: str) -> BaseAdapter:
        if provider not in adapter_cache:
            all_adapters = get_all_adapters()
            adapter_or_cls = all_adapters.get(provider)
            if adapter_or_cls is None:
                raise ValueError(f"Unknown provider: {provider}")
            if isinstance(adapter_or_cls, BaseAdapter):
                adapter_cache[provider] = adapter_or_cls
            else:
                adapter_cache[provider] = adapter_or_cls()
        return adapter_cache[provider]

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 41520)
    workdir = getattr(args, "workdir", ".")
    sandbox = getattr(args, "sandbox", "read-only")
    token = getattr(args, "token", "")

    from vyane import __version__

    print(f"Vyane A2A server v{__version__}")
    print(f"  Listening on http://{host}:{port}")
    print(f"  Agent Card: http://{host}:{port}/.well-known/agent.json")
    print(f"  Workdir: {workdir}")
    print(f"  Sandbox: {sandbox}")
    if (
        token
        or os.environ.get("VYANE_A2A_TOKEN")
        or os.environ.get("MODELMUX_A2A_TOKEN")
    ):
        print("  Auth: Bearer token enabled")
    else:
        print("  Auth: disabled (open access)")
    print()

    # Task persistence
    persist_path = ""
    if not getattr(args, "no_persist", False):
        persist_file = resolve_user_write_path("a2a-tasks.jsonl")
        persist_file.parent.mkdir(parents=True, exist_ok=True)
        persist_path = str(persist_file)

    server = A2AServer(
        get_adapter=get_adapter,
        host=host,
        port=port,
        workdir=workdir,
        sandbox=sandbox,
        auth_token=token,
        persist_path=persist_path,
    )
    server.run()


def _get_available_adapters():
    """Return (all_adapters, available_names) for CLI commands."""
    from vyane.adapters import get_all_adapters
    from vyane.adapters.base import BaseAdapter

    all_adapters = get_all_adapters()
    available: list[str] = []
    for name, cls_or_inst in all_adapters.items():
        adapter = cls_or_inst if isinstance(cls_or_inst, BaseAdapter) else cls_or_inst()
        if adapter.check_available():
            available.append(name)
    return all_adapters, available


def _resolve_adapter(all_adapters, name):
    """Get an adapter instance by name."""
    from vyane.adapters.base import BaseAdapter

    cls_or_inst = all_adapters[name]
    return cls_or_inst if isinstance(cls_or_inst, BaseAdapter) else cls_or_inst()


def _read_task(args) -> str:
    """Read task from positional args or stdin."""
    import json

    task_parts = getattr(args, "task", [])
    if task_parts:
        return " ".join(task_parts)
    task = sys.stdin.read().strip()
    if not task:
        print(
            json.dumps({"status": "error", "error": "No task provided"}),
            file=sys.stderr,
        )
        sys.exit(1)
    return task


def _apply_profile(
    provider: str, model: str, profile_name: str
) -> tuple[dict, dict[str, str]]:
    """Load profile and build extra_args + env_overrides."""
    extra: dict = {}
    env_overrides: dict[str, str] = {}

    if model:
        extra["model"] = model

    if profile_name:
        from vyane.config import load_config

        config = load_config()
        prof = config.profiles.get(profile_name)
        if prof:
            pc = prof.providers.get(provider)
            if pc:
                if pc.model and not model:
                    extra["model"] = pc.model
                if pc.wire_api:
                    extra["wire_api"] = pc.wire_api
                env_overrides = pc.to_env_overrides(provider)

    return extra, env_overrides


def _cmd_dispatch(args: argparse.Namespace) -> None:
    """Run a single dispatch from the CLI and print JSON result."""
    import asyncio
    import json
    import time

    from vyane.routing import smart_route

    task = _read_task(args)
    provider = getattr(args, "provider", "auto")
    model = getattr(args, "model", "")
    sandbox = getattr(args, "sandbox", "read-only")
    timeout = getattr(args, "timeout", 300)
    workdir = getattr(args, "workdir", ".")
    max_retries = max(1, min(getattr(args, "max_retries", 1), 5))
    failover = getattr(args, "failover", False)
    profile_name = getattr(args, "profile", "")

    all_adapters, available = _get_available_adapters()

    if not available:
        print(
            json.dumps({"status": "error", "error": "No providers available"}),
        )
        sys.exit(1)

    # Resolve provider
    if provider == "auto":
        provider, _ = smart_route(task, available)
    if provider not in available:
        provider = available[0]

    adapter = _resolve_adapter(all_adapters, provider)

    # Build extra_args + env from profile
    extra, env_overrides = _apply_profile(provider, model, profile_name)

    run_kwargs = {
        "prompt": task,
        "workdir": workdir,
        "sandbox": sandbox,
        "timeout": timeout,
        "extra_args": extra if extra else None,
    }
    if env_overrides:
        run_kwargs["env_overrides"] = env_overrides

    result = asyncio.run(adapter.run(**run_kwargs))

    # Same-provider retry with exponential backoff
    if result.status in ("error", "timeout") and max_retries > 1:
        for attempt in range(2, max_retries + 1):
            backoff = 2 ** (attempt - 1)
            print(
                f"Retry {attempt}/{max_retries} in {backoff}s...",
                file=sys.stderr,
            )
            time.sleep(backoff)
            result = asyncio.run(adapter.run(**run_kwargs))
            if result.status not in ("error", "timeout"):
                break

    # Failover to other providers
    failover_from = ""
    if failover and result.status in ("error", "timeout"):
        for fb_name in available:
            if fb_name == provider:
                continue
            fb_adapter = _resolve_adapter(all_adapters, fb_name)
            if not fb_adapter.check_available():
                continue
            print(
                f"Failover: {provider} failed, trying {fb_name}...",
                file=sys.stderr,
            )
            failover_from = provider
            result = asyncio.run(
                fb_adapter.run(
                    prompt=task,
                    workdir=workdir,
                    sandbox=sandbox,
                    timeout=timeout,
                    extra_args=extra if extra else None,
                )
            )
            if result.status not in ("error", "timeout"):
                break

    result_dict = result.to_dict()
    if failover_from:
        result_dict["failover_from"] = failover_from

    # Log to history (same as MCP tool dispatch)
    try:
        from vyane.history import log_result

        log_result(result_dict, task=task, source="cli-dispatch")
    except Exception:
        pass

    output = json.dumps(result_dict, ensure_ascii=False)
    print(output)

    if result.status != "success":
        sys.exit(1)


def _cmd_broadcast(args: argparse.Namespace) -> None:
    """Broadcast a task to multiple providers in parallel."""
    import asyncio
    import json

    task = _read_task(args)
    providers_arg = getattr(args, "providers", None)
    model = getattr(args, "model", "")
    sandbox = getattr(args, "sandbox", "read-only")
    timeout = getattr(args, "timeout", 300)
    workdir = getattr(args, "workdir", ".")
    do_compare = getattr(args, "compare", False)
    profile_name = getattr(args, "profile", "")

    all_adapters, available = _get_available_adapters()

    if not available:
        print(
            json.dumps({"status": "error", "error": "No providers available"}),
        )
        sys.exit(1)

    # Resolve target providers
    if providers_arg:
        targets = [p for p in providers_arg if p in available]
        if not targets:
            targets = available
    else:
        targets = available

    async def run_all():
        coros = []
        for name in targets:
            adapter = _resolve_adapter(all_adapters, name)
            extra, env_ov = _apply_profile(name, model, profile_name)
            kwargs: dict = {
                "prompt": task,
                "workdir": workdir,
                "sandbox": sandbox,
                "timeout": timeout,
                "extra_args": extra if extra else None,
            }
            if env_ov:
                kwargs["env_overrides"] = env_ov
            coros.append(adapter.run(**kwargs))
        return await asyncio.gather(*coros, return_exceptions=True)

    results_raw = asyncio.run(run_all())

    results = []
    for i, r in enumerate(results_raw):
        if isinstance(r, Exception):
            results.append(
                {
                    "provider": targets[i],
                    "status": "error",
                    "error": str(r),
                }
            )
        else:
            results.append(r.to_dict())

    # Log each result to history
    try:
        from vyane.history import log_result

        for rd in results:
            log_result(rd, task=task, source="cli-broadcast")
    except Exception:
        pass

    broadcast_data: dict = {"results": results, "providers": targets}

    if do_compare:
        from vyane.compare import compare_results

        broadcast_data["comparison"] = compare_results(results)

    output = json.dumps(broadcast_data, ensure_ascii=False, indent=2)
    print(output)

    # Exit 1 if all failed
    if all(r.get("status") != "success" for r in results):
        sys.exit(1)


def _cmd_profile(args: argparse.Namespace) -> None:
    """List or show configuration profiles."""
    import json as json_mod

    from vyane.config import load_config

    config = load_config()
    use_json = getattr(args, "json", False)
    profile_name = getattr(args, "name", "")

    if profile_name:
        # Show specific profile
        prof = config.profiles.get(profile_name)
        if not prof:
            msg = f"Profile '{profile_name}' not found"
            if use_json:
                print(json_mod.dumps({"error": msg}))
            else:
                print(f"  {msg}")
            sys.exit(1)

        if use_json:
            data = {
                "name": profile_name,
                "description": prof.description,
                "providers": {},
            }
            for pname, pc in prof.providers.items():
                data["providers"][pname] = {
                    "model": pc.model,
                    "base_url": pc.base_url,
                    "api_key_env": pc.api_key_env,
                }
            print(json_mod.dumps(data, indent=2))
        else:
            print(f"Profile: {profile_name}")
            if prof.description:
                print(f"  {prof.description}")
            print()
            for pname, pc in prof.providers.items():
                parts = [pname]
                if pc.model:
                    parts.append(f"model={pc.model}")
                if pc.base_url:
                    parts.append(f"url={pc.base_url}")
                print(f"  {' | '.join(parts)}")
            if not prof.providers:
                print("  (no provider overrides)")
        return

    # List all profiles
    profiles = config.profiles
    active = config.active_profile

    if use_json:
        data = {
            "active": active,
            "profiles": {},
        }
        for name, prof in profiles.items():
            data["profiles"][name] = {
                "description": prof.description,
                "providers": list(prof.providers.keys()),
            }
        print(json_mod.dumps(data, indent=2))
    else:
        print("Vyane — Profiles")
        print("-" * 40)
        if not profiles:
            print("  No profiles configured.")
            print(
                "  Create one in ~/.config/vyane/profiles.toml "
                "(legacy fallback: ~/.config/modelmux/profiles.toml)"
            )
        for name, prof in profiles.items():
            marker = " *" if name == active else ""
            desc = f" — {prof.description}" if prof.description else ""
            provs = ", ".join(prof.providers.keys())
            prov_str = f" [{provs}]" if provs else ""
            print(f"  {name}{marker}{desc}{prov_str}")
        print()


def _cmd_feedback(args: argparse.Namespace) -> None:
    """Submit or view user feedback."""
    import json

    if getattr(args, "list", False):
        from vyane.feedback import read_feedback

        hours = getattr(args, "hours", 0)
        provider = getattr(args, "provider", "")
        entries = read_feedback(hours=hours, provider=provider)
        if not entries:
            print("  No feedback entries found.")
            return
        print("Vyane — User Feedback")
        print("-" * 50)
        for e in entries[-20:]:
            stars = "*" * e.get("rating", 0) + "." * (5 - e.get("rating", 0))
            prov = e.get("provider", "?")
            comment = e.get("comment", "")
            rid = e.get("run_id", "?")[:8]
            print(f"  [{stars}] {prov:8s} {rid}  {comment[:60]}")
        print()
        return

    # Submit feedback
    run_id = getattr(args, "run_id", "")
    provider = getattr(args, "provider", "")
    rating = getattr(args, "rating", 0)
    comment = getattr(args, "comment", "")
    category = getattr(args, "category", "")

    if not run_id or not provider or not rating:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": "Required: --run-id, --provider, --rating",
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    from vyane.feedback import log_feedback

    try:
        log_feedback(
            run_id=run_id,
            provider=provider,
            rating=rating,
            category=category,
            comment=comment,
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "run_id": run_id,
                    "provider": provider,
                    "rating": rating,
                }
            )
        )
    except ValueError as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _cmd_clean(args: argparse.Namespace) -> None:
    """Clean up data files (history, audit, feedback, status)."""
    from vyane.paths import resolve_user_write_path

    config_dir = resolve_user_write_path()

    targets = {
        "history": config_dir / "history.jsonl",
        "audit": config_dir / "audit.jsonl",
        "feedback": config_dir / "feedback.jsonl",
        "status": config_dir / "status",
        "benchmark": config_dir / "benchmark.json",
    }

    what = getattr(args, "what", "all")
    dry_run = getattr(args, "dry_run", False)

    if what == "all":
        to_clean = list(targets.items())
    else:
        to_clean = [(what, targets[what])]

    cleaned = 0
    for name, path in to_clean:
        if path.is_dir():
            files = list(path.glob("*.json"))
            if files:
                size = sum(f.stat().st_size for f in files)
                if dry_run:
                    print(
                        f"  Would remove {len(files)} files "
                        f"from {name}/ ({size:,} bytes)"
                    )
                else:
                    for f in files:
                        f.unlink()
                    print(f"  Cleaned {name}/ ({len(files)} files, {size:,} bytes)")
                cleaned += 1
        elif path.exists():
            size = path.stat().st_size
            if dry_run:
                print(f"  Would remove {name} ({size:,} bytes)")
            else:
                path.unlink()
                print(f"  Cleaned {name} ({size:,} bytes)")
            cleaned += 1
        else:
            if dry_run:
                print(f"  {name}: not found (skip)")

    if cleaned == 0:
        print("  Nothing to clean.")
    elif dry_run:
        print("\n  (dry run — no files removed)")


def _cmd_version() -> None:
    from vyane import __version__

    print(f"Vyane {__version__}")


def main() -> None:
    from vyane.log import setup_logging

    setup_logging()

    parser = argparse.ArgumentParser(
        prog="vyane",
        description=("Vyane — multi-model AI collaboration MCP server"),
    )
    subparsers = parser.add_subparsers(dest="command")

    # vyane a2a-server
    a2a_p = subparsers.add_parser("a2a-server", help="Start the A2A HTTP server")
    a2a_p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1, use 0.0.0.0 for network access)",
    )
    a2a_p.add_argument("--port", type=int, default=41520, help="Port (default: 41520)")
    a2a_p.add_argument("--workdir", default=".", help="Working directory for agents")
    a2a_p.add_argument(
        "--sandbox",
        choices=["read-only", "write", "full"],
        default="read-only",
        help="Sandbox level (default: read-only)",
    )
    a2a_p.add_argument(
        "--token",
        default="",
        help=(
            "Bearer token for authentication "
            "(or set VYANE_A2A_TOKEN / MODELMUX_A2A_TOKEN)"
        ),
    )
    a2a_p.add_argument(
        "--no-persist",
        action="store_true",
        help="Disable task persistence (in-memory only)",
    )

    # vyane init
    init_p = subparsers.add_parser("init", help="Interactive configuration wizard")
    init_p.add_argument(
        "--scope",
        choices=["user", "project", "auto"],
        default="auto",
        help="Config scope: user/project/auto",
    )

    # vyane config
    config_p = subparsers.add_parser("config", help="TUI configuration panel")
    config_p.add_argument(
        "--scope",
        choices=["user", "project"],
        default="user",
        help=(
            "Config scope: user (~/.config/vyane, "
            "legacy ~/.config/modelmux) or project (.modelmux/)"
        ),
    )

    # vyane check
    check_p = subparsers.add_parser(
        "check", help="Check which model CLIs are available"
    )
    check_p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON (for scripts and CI)",
    )

    # vyane status
    status_p = subparsers.add_parser("status", help="Monitor active dispatches")
    status_p.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Live-refresh mode (updates every second)",
    )

    # vyane history
    hist_p = subparsers.add_parser("history", help="View dispatch history and stats")
    hist_p.add_argument(
        "--stats", action="store_true", help="Show aggregated statistics"
    )
    hist_p.add_argument(
        "-n", "--limit", type=int, default=10, help="Number of entries (default 10)"
    )
    hist_p.add_argument("--provider", default="", help="Filter by provider")
    hist_p.add_argument(
        "--hours", type=float, default=0, help="Only last N hours (0 = all)"
    )
    hist_p.add_argument(
        "--costs", action="store_true", help="Include cost estimation breakdown"
    )
    hist_p.add_argument(
        "--source",
        default="",
        help="Filter by source (dispatch, broadcast, cli-dispatch, cli-broadcast)",
    )
    hist_p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON (for scripts and CI)",
    )

    # vyane benchmark
    bench_p = subparsers.add_parser("benchmark", help="Run provider benchmark suite")
    bench_p.add_argument(
        "--providers", nargs="+", help="Providers to test (default: auto-detect)"
    )
    bench_p.add_argument("--tasks", nargs="+", help="Task names to run (default: all)")
    bench_p.add_argument(
        "--timeout", type=int, default=120, help="Per-task timeout (default: 120s)"
    )
    bench_p.add_argument("--output", "-o", default="", help="Save results to JSON file")
    bench_p.add_argument(
        "--list-tasks", action="store_true", help="List available benchmark tasks"
    )

    # vyane export
    exp_p = subparsers.add_parser(
        "export", help="Export history to CSV, JSON, or Markdown"
    )
    exp_p.add_argument(
        "--format",
        "-f",
        choices=["csv", "json", "md"],
        default="csv",
        help="Output format (default: csv)",
    )
    exp_p.add_argument("--hours", type=float, default=0, help="Only last N hours")
    exp_p.add_argument("--provider", default="", help="Filter by provider")
    exp_p.add_argument(
        "-n", "--limit", type=int, default=1000, help="Max entries (default: 1000)"
    )
    exp_p.add_argument(
        "--output", "-o", default="", help="Write to file instead of stdout"
    )
    exp_p.add_argument(
        "--source", default="", help="Filter by source (dispatch, cli-dispatch, etc.)"
    )

    # vyane dashboard
    dash_p = subparsers.add_parser(
        "dashboard", help="Start the web monitoring dashboard"
    )
    dash_p.add_argument(
        "--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)"
    )
    dash_p.add_argument("--port", type=int, default=41521, help="Port (default: 41521)")

    # vyane dispatch
    disp_p = subparsers.add_parser(
        "dispatch", help="Run a single task via a provider (JSON output)"
    )
    disp_p.add_argument(
        "--provider",
        "-p",
        default="auto",
        help="Provider to use (default: auto = smart routing)",
    )
    disp_p.add_argument("--model", "-m", default="", help="Specific model override")
    disp_p.add_argument(
        "--sandbox",
        choices=["read-only", "write", "full"],
        default="read-only",
        help="Sandbox level (default: read-only)",
    )
    disp_p.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=300,
        help="Timeout in seconds (default: 300)",
    )
    disp_p.add_argument(
        "--workdir",
        "-w",
        default=".",
        help="Working directory (default: current dir)",
    )
    disp_p.add_argument(
        "--max-retries",
        "-r",
        type=int,
        default=1,
        dest="max_retries",
        help="Max attempts for same provider (default: 1, max: 5)",
    )
    disp_p.add_argument(
        "--profile",
        default="",
        help="Named profile (e.g., 'budget', 'china')",
    )
    disp_p.add_argument(
        "--failover",
        action="store_true",
        help="Try other providers if the primary one fails",
    )
    disp_p.add_argument(
        "task",
        nargs="*",
        help="Task prompt (reads from stdin if omitted)",
    )

    # vyane broadcast
    bcast_p = subparsers.add_parser(
        "broadcast",
        help="Broadcast a task to multiple providers in parallel",
    )
    bcast_p.add_argument(
        "--providers",
        nargs="+",
        help="Providers to use (default: all available)",
    )
    bcast_p.add_argument("--model", "-m", default="", help="Model override for all")
    bcast_p.add_argument(
        "--sandbox",
        choices=["read-only", "write", "full"],
        default="read-only",
        help="Sandbox level (default: read-only)",
    )
    bcast_p.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=300,
        help="Timeout per provider in seconds (default: 300)",
    )
    bcast_p.add_argument(
        "--workdir",
        "-w",
        default=".",
        help="Working directory (default: current dir)",
    )
    bcast_p.add_argument(
        "--profile",
        default="",
        help="Named profile (e.g., 'budget', 'china')",
    )
    bcast_p.add_argument(
        "--compare",
        action="store_true",
        help="Add structured comparison analysis (similarity, speed ranking)",
    )
    bcast_p.add_argument(
        "task",
        nargs="*",
        help="Task prompt (reads from stdin if omitted)",
    )

    # vyane profile
    prof_p = subparsers.add_parser(
        "profile", help="List or show configuration profiles"
    )
    prof_p.add_argument(
        "name", nargs="?", default="", help="Profile name to show details"
    )
    prof_p.add_argument("--json", action="store_true", help="Output as JSON")

    # vyane feedback
    fb_p = subparsers.add_parser(
        "feedback", help="Submit or view user feedback for routing"
    )
    fb_p.add_argument("--run-id", default="", help="Run ID to rate", dest="run_id")
    fb_p.add_argument(
        "--provider", default="", help="Provider that produced the result"
    )
    fb_p.add_argument(
        "--rating", type=int, default=0, help="Rating 1-5 (1=terrible, 5=excellent)"
    )
    fb_p.add_argument("--comment", default="", help="Optional comment")
    fb_p.add_argument(
        "--category",
        default="",
        help="Task category (analysis/generation/reasoning/language)",
    )
    fb_p.add_argument(
        "--list", action="store_true", help="List recent feedback entries"
    )
    fb_p.add_argument(
        "--hours", type=float, default=0, help="Filter by time window (for --list)"
    )

    # vyane clean
    clean_p = subparsers.add_parser(
        "clean", help="Clean up data files (history, audit, feedback)"
    )
    clean_p.add_argument(
        "what",
        nargs="?",
        default="all",
        choices=["all", "history", "audit", "feedback", "status", "benchmark"],
        help="What to clean (default: all)",
    )
    clean_p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would be removed without actually deleting",
    )

    # vyane version
    subparsers.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command is None:
        _cmd_server()
    elif args.command == "a2a-server":
        _cmd_a2a_server(args)
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "config":
        _cmd_config(args)
    elif args.command == "check":
        _cmd_check(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "history":
        _cmd_history(args)
    elif args.command == "benchmark":
        _cmd_benchmark(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "dashboard":
        _cmd_dashboard(args)
    elif args.command == "dispatch":
        _cmd_dispatch(args)
    elif args.command == "broadcast":
        _cmd_broadcast(args)
    elif args.command == "profile":
        _cmd_profile(args)
    elif args.command == "feedback":
        _cmd_feedback(args)
    elif args.command == "clean":
        _cmd_clean(args)
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
