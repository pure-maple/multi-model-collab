"""CLI entry point for modelmux.

Usage:
  modelmux              Start the MCP server (stdio transport)
  modelmux a2a-server   Start the A2A HTTP server
  modelmux init         Interactive configuration wizard
  modelmux config       TUI configuration panel (requires modelmux[tui])
  modelmux check        Quick CLI availability check
  modelmux status       Monitor active dispatches in real-time
  modelmux history      View dispatch history and statistics
  modelmux version      Show version
"""

import argparse
import os
import sys


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
                pass

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

    host = getattr(args, "host", "0.0.0.0")
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


def _cmd_version() -> None:
    from modelmux import __version__

    print(f"modelmux {__version__}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="modelmux",
        description=("Model multiplexer — multi-model AI collaboration MCP server"),
    )
    subparsers = parser.add_subparsers(dest="command")

    # modelmux a2a-server
    a2a_p = subparsers.add_parser("a2a-server", help="Start the A2A HTTP server")
    a2a_p.add_argument(
        "--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)"
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

    # modelmux dashboard
    dash_p = subparsers.add_parser(
        "dashboard", help="Start the web monitoring dashboard"
    )
    dash_p.add_argument(
        "--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)"
    )
    dash_p.add_argument(
        "--port", type=int, default=41521, help="Port (default: 41521)"
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
    elif args.command == "dashboard":
        _cmd_dashboard(args)
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
