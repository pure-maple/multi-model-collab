# modelmux

<!-- mcp-name: io.github.pure-maple/modelmux -->

Model multiplexer — unified MCP server for cross-platform multi-model AI collaboration.

Route tasks to **Codex CLI**, **Gemini CLI**, and **Claude Code CLI** through a single MCP interface with smart routing and caller auto-detection.

## Install

```bash
# One-command install for Claude Code
claude mcp add modelmux -s user -- uvx modelmux

# Codex CLI (~/.codex/config.toml)
# [mcp_servers.modelmux]
# command = "uvx"
# args = ["modelmux"]
# tool_timeout_sec = 600
# startup_timeout_sec = 30
# Leave enabled_tools unset to expose the full tool surface.

# Gemini CLI (~/.gemini/settings.json)
# {"mcpServers": {"modelmux": {"command": "uvx", "args": ["modelmux"]}}}
```

## Tools

- **`mux_dispatch`** — Send a task to a model and get structured results
  - `provider`: `"auto"` / `"codex"` / `"gemini"` / `"claude"` / `"ollama"`
  - `task`: The prompt to send
  - `workdir`, `sandbox`, `session_id`, `timeout`, `model`, `profile`, `reasoning_effort`, `failover`
- **`mux_broadcast`** — Send the same task to multiple providers in parallel
- **`mux_history`** — Query past runs and aggregated analytics
- **`mux_orchestrate`** — Manage orchestration task state and lifecycle
- **`mux_feedback`** — Submit user ratings to improve routing
- **`mux_workflow`** — Run built-in multi-step provider pipelines
- **`mux_check`** — Check which CLIs are available, show detected caller and config
- **`mux_collaborate`** — Run iterative multi-agent collaboration patterns

## Smart Routing

`provider="auto"` routes tasks by keyword analysis and auto-excludes the calling platform:

```
From Claude Code → routes to Codex or Gemini (never back to Claude)
From Codex CLI → routes to Claude or Gemini (never back to Codex)
```

## Failover

When a provider fails at execution time, modelmux automatically retries with the next available provider (enabled by default, `failover=True`). Failover is skipped for session-based requests since sessions are provider-specific.

## Audit & Policy

Every dispatch call is logged to `~/.config/modelmux/audit.jsonl` for debugging and cost tracking.

Policy enforcement via `~/.config/modelmux/policy.json`:

```json
{
  "blocked_providers": ["gemini"],
  "blocked_sandboxes": ["full"],
  "max_timeout": 600,
  "max_calls_per_hour": 30,
  "max_calls_per_day": 200
}
```

`mux_check()` now shows policy summary and audit stats.

## User Configuration

Create `.modelmux/profiles.toml` or `~/.config/modelmux/profiles.toml`:

```toml
[routing]
default_provider = "codex"

[[routing.rules]]
provider = "gemini"
[routing.rules.match]
keywords = ["frontend", "react", "css"]

[profiles.budget]
[profiles.budget.providers.codex]
model = "gpt-4.1-mini"
```

## Links

- [Full Documentation](https://github.com/pure-maple/modelmux)
- [中文文档](https://github.com/pure-maple/modelmux/blob/main/docs/README_CN.md)

## License

MIT
