# Cross-Platform Configuration Guide

## Claude Code

### MCP Server Registration

```bash
claude mcp add collab-hub -s user --transport stdio -- \
  uvx --from /path/to/mcp/collab-hub collab-hub
```

### Auto-Approve Tool Calls (optional)

Add to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "mcp__collab-hub__collab_dispatch",
      "mcp__collab-hub__collab_check"
    ]
  }
}
```

### Skill Installation

```bash
mkdir -p ~/.claude/skills/multi-model-collab
cp SKILL.md ~/.claude/skills/multi-model-collab/SKILL.md
```

---

## Codex CLI

### MCP Server Configuration

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.collab-hub]
command = "uvx"
args = ["--from", "/path/to/mcp/collab-hub", "collab-hub"]
required = false
enabled_tools = ["collab_dispatch", "collab_check"]
tool_timeout_sec = 600
startup_timeout_sec = 30
```

### Skill Installation

```bash
mkdir -p .agents/skills/multi-model-collab
cp SKILL.md .agents/skills/multi-model-collab/SKILL.md
```

---

## Gemini CLI

### MCP Server Configuration

Add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "collab-hub": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp/collab-hub", "collab-hub"],
      "timeout": 30000
    }
  }
}
```

### Skill Installation

```bash
mkdir -p .gemini/skills/multi-model-collab
cp SKILL.md .gemini/skills/multi-model-collab/SKILL.md
```

---

## IDE Integration

### VS Code (Cline / Continue)

Add to MCP settings (`.vscode/mcp.json` or extension settings):

```json
{
  "servers": {
    "collab-hub": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp/collab-hub", "collab-hub"],
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
    "collab-hub": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp/collab-hub", "collab-hub"]
    }
  }
}
```

### Windsurf

Add to Windsurf MCP configuration:

```json
{
  "mcpServers": {
    "collab-hub": {
      "command": "uvx",
      "args": ["--from", "/path/to/mcp/collab-hub", "collab-hub"]
    }
  }
}
```

---

## Troubleshooting

### collab-hub not connecting

1. Check uvx is installed: `uvx --version`
2. Check the package builds: `cd mcp/collab-hub && uvx --from . collab-hub --help`
3. Check MCP registration: `claude mcp list` / check config files

### Model CLI not found

1. Check CLI is on PATH: `which codex`, `which gemini`, `which claude`
2. Use `collab_check()` to verify availability
3. If installed via npm, ensure npm global bin is in PATH

### Timeout issues

- Default timeout is 300 seconds
- Increase via `timeout` parameter: `collab_dispatch(..., timeout=600)`
- Complex tasks may need longer timeouts
