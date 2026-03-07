"""CLI entry point for modelmux.

Usage:
  modelmux              Start the MCP server (stdio transport)
  modelmux a2a-server   Start the A2A HTTP server
  modelmux dispatch     Run a single task via a provider (JSON output)
  modelmux broadcast    Broadcast a task to multiple providers in parallel
  modelmux init         Interactive configuration wizard
  modelmux config       TUI configuration panel (requires modelmux[tui])
  modelmux check        Quick CLI availability check
  modelmux status       Monitor active dispatches in real-time
  modelmux history      View dispatch history and statistics
  modelmux version      Show version
"""

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _cmd_server() -> None:
    """Start the MCP server."""
    from modelmux.server import mcp

    mcp.run(transport="stdio")


def _cmd_init(args: argparse.Namespace) -> None:
    """Run the interactive setup wizard."""
    from modelmux.init_wizard import run_wizard

    scope = getattr(args, "scope", "user")
    run_wizard(scope=scope)


def _cmd_config(args: argparse.Namespace) -> None:
    """Launch the TUI configuration panel."""
    try:
        from modelmux.tui import run_tui
    except ImportError:
        print(
            "TUI requires the 'textual' package.\n"
            "Install with: pip install modelmux[tui]\n"
            "Or run:       uvx --with textual modelmux config"
        )
        sys.exit(1)

    scope = getattr(args, "scope", "user")
    run_tui(scope=scope)


def _cmd_check() -> None:
    """Quick CLI availability check (no MCP server needed)."""
    import shutil

    from modelmux import __version__
    from modelmux.adapters import ADAPTERS

    print(f"modelmux v{__version__}")
    print()
    for name, cls in ADAPTERS.items():
        adapter = cls()
        binary = adapter._binary_name()
        path = shutil.which(binary)
        if path:
            print(f"  \033[0;32m[+]\033[0m {name:8s} {path}")
        else:
            print(f"  \033[1;33m[-]\033[0m {name:8s} not found")
    print()


def _cmd_status(args: argparse.Namespace) -> None:
    """Monitor active dispatches."""
    import time

    from modelmux.status import list_active

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
        print("modelmux — Live Dispatch Monitor (Ctrl+C to stop)")
        print("=" * 60)
        try:
            while True:
                # Clear previous output and re-render
                print("\033[2J\033[H", end="")  # clear screen
                print("modelmux — Live Dispatch Monitor")
                print(f"  {time.strftime('%H:%M:%S')}  (Ctrl+C to stop)")
                print("-" * 60)
                _render()
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print("modelmux — Active Dispatches")
        print("-" * 40)
        _render()
        print()


def _cmd_history(args: argparse.Namespace) -> None:
    """Show dispatch history or stats."""
    import time

    from modelmux.history import HistoryQuery, get_history_stats, read_history

    show_costs = getattr(args, "costs", False)

    if getattr(args, "stats", False):
        hours = getattr(args, "hours", 0)
        stats = get_history_stats(hours=hours, include_costs=show_costs)
        if not stats.get("total"):
            print("  No history data.")
            return

        print("modelmux — History Statistics")
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
                f"  {prov:8s}  "
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
                    f"    {cp:8s}  "
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
    entries = read_history(HistoryQuery(limit=limit, provider=provider, hours=hours))

    if not entries:
        print("  No history entries found.")
        return

    print("modelmux — Recent Dispatches")
    print("-" * 60)
    for entry in entries:
        ts = entry.get("ts", 0)
        ts_str = time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "?"
        prov = entry.get("provider", "?")
        status = entry.get("status", "?")
        dur = entry.get("duration_seconds", 0)
        task = entry.get("task", "")[:50]
        src = entry.get("source", "dispatch")

        icon = "\033[0;32m+\033[0m" if status == "success" else "\033[1;31m!\033[0m"
        tag = "[B]" if src == "broadcast" else ""
        print(f"  {icon} {ts_str}  {prov:8s} {dur:5.1f}s  {tag}{task}")
    print()


def _cmd_benchmark(args: argparse.Namespace) -> None:
    """Run the benchmark suite."""
    from modelmux.benchmark import (
        BENCHMARK_TASKS,
        format_report,
        run_benchmark,
        save_report,
    )

    providers = getattr(args, "providers", None)
    task_names = getattr(args, "tasks", None)
    timeout = getattr(args, "timeout", 120)
    output = getattr(args, "output", "")

    if getattr(args, "list_tasks", False):
        print("Available benchmark tasks:")
        for name, info in BENCHMARK_TASKS.items():
            print(f"  {name:20s} [{info['category']}] {info['description']}")
        return

    print("modelmux Benchmark")
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
    from pathlib import Path

    routing_path = Path.home() / ".config" / "modelmux" / "benchmark.json"
    routing_path.parent.mkdir(parents=True, exist_ok=True)
    save_report(report, str(routing_path))
    print(f"Routing data updated: {routing_path}")


def _cmd_export(args: argparse.Namespace) -> None:
    """Export history to CSV/JSON/Markdown."""
    from modelmux.export import run_export

    fmt = getattr(args, "format", "csv")
    hours = getattr(args, "hours", 0)
    provider = getattr(args, "provider", "")
    limit = getattr(args, "limit", 1000)
    output = getattr(args, "output", "")

    content = run_export(
        fmt=fmt,
        hours=hours,
        provider=provider,
        limit=limit,
        output=output,
    )

    if output:
        print(f"Exported to {output}")
    else:
        print(content)


def _cmd_dashboard(args: argparse.Namespace) -> None:
    """Start the web dashboard."""
    from modelmux.dashboard import run_dashboard

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 41521)
    run_dashboard(host=host, port=port)


def _cmd_a2a_server(args: argparse.Namespace) -> None:
    """Start the A2A HTTP server."""
    # Load custom providers
    from pathlib import Path

    from modelmux.a2a.http_server import A2AServer
    from modelmux.adapters import get_all_adapters, load_custom_providers
    from modelmux.adapters.base import BaseAdapter
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

    from modelmux import __version__

    print(f"modelmux A2A server v{__version__}")
    print(f"  Listening on http://{host}:{port}")
    print(f"  Agent Card: http://{host}:{port}/.well-known/agent.json")
    print(f"  Workdir: {workdir}")
    print(f"  Sandbox: {sandbox}")
    if token or os.environ.get("MODELMUX_A2A_TOKEN"):
        print("  Auth: Bearer token enabled")
    else:
        print("  Auth: disabled (open access)")
    print()

    # Task persistence
    persist_path = ""
    if not getattr(args, "no_persist", False):
        from pathlib import Path

        cfg_dir = Path.home() / ".config" / "modelmux"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        persist_path = str(cfg_dir / "a2a-tasks.jsonl")

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
    from modelmux.adapters import get_all_adapters
    from modelmux.adapters.base import BaseAdapter

    all_adapters = get_all_adapters()
    available: list[str] = []
    for name, cls_or_inst in all_adapters.items():
        adapter = cls_or_inst if isinstance(cls_or_inst, BaseAdapter) else cls_or_inst()
        if adapter.check_available():
            available.append(name)
    return all_adapters, available


def _resolve_adapter(all_adapters, name):
    """Get an adapter instance by name."""
    from modelmux.adapters.base import BaseAdapter

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


def _cmd_dispatch(args: argparse.Namespace) -> None:
    """Run a single dispatch from the CLI and print JSON result."""
    import asyncio
    import json
    import time

    from modelmux.routing import smart_route

    task = _read_task(args)
    provider = getattr(args, "provider", "auto")
    model = getattr(args, "model", "")
    sandbox = getattr(args, "sandbox", "read-only")
    timeout = getattr(args, "timeout", 300)
    workdir = getattr(args, "workdir", ".")
    max_retries = max(1, min(getattr(args, "max_retries", 1), 5))

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

    extra: dict = {}
    if model:
        extra["model"] = model

    result = asyncio.run(
        adapter.run(
            prompt=task,
            workdir=workdir,
            sandbox=sandbox,
            timeout=timeout,
            extra_args=extra if extra else None,
        )
    )

    # Same-provider retry with exponential backoff
    if result.status in ("error", "timeout") and max_retries > 1:
        for attempt in range(2, max_retries + 1):
            backoff = 2 ** (attempt - 1)
            print(
                f"Retry {attempt}/{max_retries} in {backoff}s...",
                file=sys.stderr,
            )
            time.sleep(backoff)
            result = asyncio.run(
                adapter.run(
                    prompt=task,
                    workdir=workdir,
                    sandbox=sandbox,
                    timeout=timeout,
                    extra_args=extra if extra else None,
                )
            )
            if result.status not in ("error", "timeout"):
                break

    output = json.dumps(result.to_dict(), ensure_ascii=False)
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

    extra: dict = {}
    if model:
        extra["model"] = model

    async def run_all():
        tasks = []
        for name in targets:
            adapter = _resolve_adapter(all_adapters, name)
            tasks.append(
                adapter.run(
                    prompt=task,
                    workdir=workdir,
                    sandbox=sandbox,
                    timeout=timeout,
                    extra_args=extra if extra else None,
                )
            )
        return await asyncio.gather(*tasks, return_exceptions=True)

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

    output = json.dumps(
        {"results": results, "providers": targets},
        ensure_ascii=False,
        indent=2,
    )
    print(output)

    # Exit 1 if all failed
    if all(r.get("status") != "success" for r in results):
        sys.exit(1)


def _cmd_version() -> None:
    from modelmux import __version__

    print(f"modelmux {__version__}")


def main() -> None:
    from modelmux.log import setup_logging

    setup_logging()

    parser = argparse.ArgumentParser(
        prog="modelmux",
        description=("Model multiplexer — multi-model AI collaboration MCP server"),
    )
    subparsers = parser.add_subparsers(dest="command")

    # modelmux a2a-server
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
        help="Bearer token for authentication (or set MODELMUX_A2A_TOKEN env var)",
    )
    a2a_p.add_argument(
        "--no-persist",
        action="store_true",
        help="Disable task persistence (in-memory only)",
    )

    # modelmux init
    init_p = subparsers.add_parser("init", help="Interactive configuration wizard")
    init_p.add_argument(
        "--scope",
        choices=["user", "project", "auto"],
        default="auto",
        help="Config scope: user/project/auto",
    )

    # modelmux config
    config_p = subparsers.add_parser("config", help="TUI configuration panel")
    config_p.add_argument(
        "--scope",
        choices=["user", "project"],
        default="user",
        help="Config scope: user (~/.config/modelmux) or project (.modelmux/)",
    )

    # modelmux check
    subparsers.add_parser("check", help="Check which model CLIs are available")

    # modelmux status
    status_p = subparsers.add_parser("status", help="Monitor active dispatches")
    status_p.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Live-refresh mode (updates every second)",
    )

    # modelmux history
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

    # modelmux benchmark
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

    # modelmux export
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

    # modelmux dashboard
    dash_p = subparsers.add_parser(
        "dashboard", help="Start the web monitoring dashboard"
    )
    dash_p.add_argument(
        "--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)"
    )
    dash_p.add_argument("--port", type=int, default=41521, help="Port (default: 41521)")

    # modelmux dispatch
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
        "task",
        nargs="*",
        help="Task prompt (reads from stdin if omitted)",
    )

    # modelmux broadcast
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
        "task",
        nargs="*",
        help="Task prompt (reads from stdin if omitted)",
    )

    # modelmux version
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
        _cmd_check()
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
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
