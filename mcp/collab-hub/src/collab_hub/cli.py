"""Entry point for the collab-hub MCP server."""

from collab_hub.server import mcp


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
