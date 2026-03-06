"""CLI entry point for modelmux.

Usage:
  modelmux           Start the MCP server (stdio transport)
  modelmux init      Interactive configuration wizard
  modelmux check     Quick CLI availability check
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


def _cmd_version() -> None:
    from modelmux import __version__

    print(f"modelmux {__version__}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="modelmux",
        description="Model multiplexer — multi-model AI collaboration MCP server",
    )
    subparsers = parser.add_subparsers(dest="command")

    # modelmux init
    init_parser = subparsers.add_parser("init", help="Interactive configuration wizard")
    init_parser.add_argument(
        "--scope",
        choices=["user", "project", "auto"],
        default="auto",
        help="Config scope: user/project/auto",
    )

    # modelmux check
    subparsers.add_parser("check", help="Check which model CLIs are available")

    # modelmux version
    subparsers.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command is None:
        # No subcommand → start MCP server (default behavior)
        _cmd_server()
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "check":
        _cmd_check()
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
