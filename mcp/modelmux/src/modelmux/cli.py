"""CLI entry point for modelmux.

Usage:
  modelmux           Start the MCP server (stdio transport)
  modelmux init      Interactive configuration wizard
  modelmux config    TUI configuration panel (requires modelmux[tui])
  modelmux check     Quick CLI availability check
  modelmux status    Monitor active dispatches in real-time
  modelmux version   Show version
"""

import argparse
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


def _cmd_version() -> None:
    from modelmux import __version__

    print(f"modelmux {__version__}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="modelmux",
        description=("Model multiplexer — multi-model AI collaboration MCP server"),
    )
    subparsers = parser.add_subparsers(dest="command")

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

    # modelmux version
    subparsers.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command is None:
        _cmd_server()
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "config":
        _cmd_config(args)
    elif args.command == "check":
        _cmd_check()
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
