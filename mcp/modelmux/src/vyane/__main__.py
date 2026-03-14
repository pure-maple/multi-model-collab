"""Allow `python -m vyane` to start the MCP server."""

from vyane.server import mcp

mcp.run(transport="stdio")
