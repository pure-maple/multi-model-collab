"""Allow `python -m modelmux` to start the MCP server."""

from modelmux.server import mcp

mcp.run(transport="stdio")
