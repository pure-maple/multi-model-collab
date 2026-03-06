# Cross-Platform Configuration Guide

## Claude Code

### MCP Server Registration

```bash
claude mcp add modelmux -s user --transport stdio -- \
  uvx --from /path/to/mcp/modelmux modelmux
```

### Auto-Approve Tool Calls (optional)

Add to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "mcp__modelmux__mux_dispatch",
      "mcp__modelmux__mux_check"
    ]
  }
}
```

### Skill Installation

```bash
mkdir -p ~/.claude/skills/modelmux
cp SKILL.md ~/.claude/skills/modelmux/SKILL.md
```

---

## Codex CLI

### MCP Server Configuration

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.modelmux]
command = "uvx"
args = ["--from", "/path/to/mcp/modelmux", "modelmux"]
required = false
enabled_tools = ["mux_dispatch", "mux_check"]
tool_timeout_sec = 600
startup_timeout_sec = 30
```

### Skill Installation

```bash
mkdir -p .agents/skills/modelmux
cp SKILL.md .agents/skills/modelmux/SKILL.md
```

---

## Gemini CLI

### MCP Server Configuration

Add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "modelmux": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp/modelmux", "modelmux"],
      "timeout": 30000
    }
  }
}
```

### Skill Installation

```bash
mkdir -p .gemini/skills/modelmux
cp SKILL.md .gemini/skills/modelmux/SKILL.md
```

---

## IDE Integration

### VS Code (Cline / Continue)

Add to MCP settings (`.vscode/mcp.json` or extension settings):

```json
{
  "servers": {
    "modelmux": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp/modelmux", "modelmux"],
      "transport": "stdio"
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "modelmux": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp/modelmux", "modelmux"]
    }
  }
}
```

### Windsurf

Add to Windsurf MCP configuration:

```json
{
  "mcpServers": {
    "modelmux": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp/modelmux", "modelmux"]
    }
  }
}
```

---

## Troubleshooting

### modelmux not connecting

1. Check uvx is installed: `uvx --version`
2. Check the package builds: `cd mcp/modelmux && uvx --from . modelmux --help`
3. Check MCP registration: `claude mcp list` / check config files

### Model CLI not found

1. Check CLI is on PATH: `which codex`, `which gemini`, `which claude`
2. Use `mux_check()` to verify availability
3. If installed via npm, ensure npm global bin is in PATH

### Timeout issues

- Default timeout is 300 seconds
- Increase via `timeout` parameter: `mux_dispatch(..., timeout=600)`
- Complex tasks may need longer timeouts
