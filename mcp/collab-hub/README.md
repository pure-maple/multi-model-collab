# collab-hub

Unified MCP server for cross-platform multi-model AI collaboration.

Routes tasks to Codex CLI, Gemini CLI, and Claude Code CLI through a single MCP interface.

## Install

```bash
# For Claude Code
claude mcp add collab-hub -s user -- uvx --from ./mcp/collab-hub collab-hub

# Or use the installer
./install.sh --claude
```

## Tools

- `collab_dispatch` — Send a task to a model and get structured results
- `collab_check` — Check which model CLIs are available
