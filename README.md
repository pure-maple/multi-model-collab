# modelmux

English | [中文](docs/README_CN.md)

Cross-platform multi-model AI collaboration skill. Dispatch tasks to **Codex CLI**, **Gemini CLI**, and **Claude Code CLI** through a unified MCP interface.

## Why

Different AI models have different strengths:

| Model | Strengths |
|-------|-----------|
| **Codex** (GPT) | Code generation, algorithms, debugging |
| **Gemini** | Frontend/UI, multimodal, broad knowledge |
| **Claude** | Architecture, reasoning, code review |

This project lets any MCP-compatible platform orchestrate tasks across all three — getting the best of each.

## Architecture

```
Any MCP Client (Claude Code / Codex CLI / Gemini CLI / IDE)
    │
    └── modelmux (unified MCP server)
        ├── mux_dispatch(provider, task, ...) → Canonical Result
        └── mux_check() → availability status
            │
            ├── CodexAdapter  → codex exec --json
            ├── GeminiAdapter → gemini -p -o stream-json
            └── ClaudeAdapter → claude -p
```

**3-level fallback:**
1. **MCP tool** (recommended) — no Bash permissions needed, cross-platform
2. **Bash scripts** — tmux-based parallel dispatch, needs pre-configured permissions
3. **Pure prompt** — degraded mode, single-model multi-perspective analysis

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- At least one model CLI installed:
  - `codex` — `npm i -g @openai/codex`
  - `gemini` — `npm i -g @anthropic/gemini-cli`
  - `claude` — [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

### Install

```bash
git clone https://github.com/pure-maple/modelmux.git
cd modelmux

# Install for Claude Code (one command)
./install.sh --claude

# Or install for all platforms
./install.sh --all

# Check prerequisites
./install.sh --check
```

### Manual Installation

```bash
# Claude Code
claude mcp add modelmux -s user -- uvx modelmux

# Codex CLI (~/.codex/config.toml)
[mcp_servers.modelmux]
command = "uvx"
args = ["modelmux"]

# Gemini CLI (~/.gemini/settings.json)
{"mcpServers": {"modelmux": {"command": "uvx", "args": ["modelmux"]}}}
```

## Usage

### From Claude Code (or any MCP client)

```
# Check available models
mux_check()

# Dispatch a task to Codex
mux_dispatch(
    provider="codex",
    task="Implement a binary search tree in Python",
    workdir="/path/to/project",
    sandbox="read-only"
)

# Dispatch to Gemini
mux_dispatch(
    provider="gemini",
    task="Design a responsive dashboard layout",
    workdir="/path/to/project"
)

# Multi-turn session
r1 = mux_dispatch(provider="codex", task="Analyze this codebase")
r2 = mux_dispatch(provider="codex", task="Fix the bug you found",
                     session_id=r1.session_id)
```

### As an Agent Skill

Copy `SKILL.md` to your skills directory:

```bash
# Claude Code
cp SKILL.md ~/.claude/skills/modelmux/SKILL.md

# Codex CLI
cp SKILL.md .agents/skills/modelmux/SKILL.md

# Gemini CLI
cp SKILL.md .gemini/skills/modelmux/SKILL.md
```

## Smart Routing & Caller Detection

When using `provider="auto"`, the hub:
1. Detects which platform is calling via MCP `clientInfo`
2. Auto-excludes the caller from routing (prevents self-dispatch loops)
3. Routes to the best model based on task keywords

```
# From Claude Code → auto-routes to Codex or Gemini (never back to Claude)
mux_dispatch(provider="auto", task="Implement a REST API")
```

### User Configuration

Create `.modelmux/profiles.toml` (project-level) or `~/.config/modelmux/profiles.toml` (user-level):

```toml
# Custom routing rules
[routing]
default_provider = "codex"

[[routing.rules]]
provider = "gemini"
[routing.rules.match]
keywords = ["frontend", "react", "css"]

[[routing.rules]]
provider = "claude"
[routing.rules.match]
keywords = ["security", "architecture"]

# Caller detection override (optional)
caller_override = ""          # Force caller identity: "claude"/"codex"/"gemini"
auto_exclude_caller = true    # Auto-exclude detected caller from routing

# Named profiles for third-party models
[profiles.budget]
description = "Use cheaper models"
[profiles.budget.providers.codex]
model = "gpt-4.1-mini"
[profiles.budget.providers.gemini]
model = "gemini-2.0-flash"
```

## Failover

When a provider fails at execution time, modelmux automatically retries with the next available provider:

```
mux_dispatch(provider="codex", task="...", failover=True)  # default
# If codex CLI crashes → auto-retry with gemini or claude
# Result includes "failover_from": "codex" to show what happened
```

Failover is skipped for session-based requests (`session_id` set) since sessions are provider-specific. Disable with `failover=False`.

## Output Schema

All results follow the canonical schema:

```json
{
    "run_id": "a1b2c3d4",
    "provider": "codex",
    "status": "success",
    "summary": "First 200 chars...",
    "output": "Full model response",
    "session_id": "uuid-for-multi-turn",
    "duration_seconds": 12.5,
    "routed_from": "auto",
    "caller_excluded": "claude"
}
```

## Audit Logging & Policy Engine

Every `mux_dispatch` call is logged to `~/.config/modelmux/audit.jsonl` (JSONL format) for debugging, cost tracking, and rate limiting.

### Policy Enforcement

Create `~/.config/modelmux/policy.json` to enforce security constraints:

```json
{
  "allowed_providers": [],
  "blocked_providers": ["gemini"],
  "blocked_sandboxes": ["full"],
  "max_timeout": 600,
  "max_calls_per_hour": 30,
  "max_calls_per_day": 200
}
```

| Policy | Description |
|--------|-------------|
| `allowed_providers` | Whitelist (empty = all allowed) |
| `blocked_providers` | Blacklist specific providers |
| `blocked_sandboxes` | Block sandbox levels (e.g. `"full"`) |
| `max_timeout` | Cap timeout seconds (0 = unlimited) |
| `max_calls_per_hour` | Hourly rate limit (0 = unlimited) |
| `max_calls_per_day` | Daily rate limit (0 = unlimited) |

Blocked requests return `{"status": "blocked", "error": "Policy denied: ..."}`.

`mux_check()` includes policy summary and audit stats in its output.

## Project Structure

```
modelmux/
├── SKILL.md                    # Agent Skill definition (MCP-first)
├── install.sh                  # One-command installer
├── mcp/modelmux/             # Unified MCP server
│   ├── pyproject.toml
│   └── src/modelmux/
│       ├── server.py           # MCP tools: mux_dispatch, mux_check
│       ├── config.py           # User profiles, routing rules, config loading
│       ├── detect.py           # Caller platform detection & auto-exclusion
│       ├── audit.py            # JSONL audit logging & stats
│       ├── policy.py           # Policy engine (rate limits, provider/sandbox rules)
│       ├── cli.py              # Entry point
│       └── adapters/
│           ├── base.py         # Threaded subprocess, canonical schema
│           ├── codex.py        # JSONL parsing, thread_id sessions
│           ├── gemini.py       # stream-json parsing, session_id
│           └── claude.py       # Plain text parsing
├── scripts/                    # Fallback: tmux-based shell scripts
│   ├── session.sh
│   ├── dispatch.sh
│   ├── collect.sh
│   └── adapters/
└── references/                 # Architecture docs and consultation records
```

## Design Decisions

This architecture was jointly designed through consultation with three AI models:
- **Claude Opus 4.6** — original proposal and synthesis
- **GPT-5.3-Codex** — recommended unified hub over separate bridges, OPA policy engine, `--output-schema` utilization
- **Gemini-3.1-Pro-Preview** — recommended A2A protocol backbone, Conductor shared state, dynamic tool exposure

Key consensus points:
1. **One unified MCP hub** instead of 3 separate bridge servers
2. **MCP-first** to bypass subagent Bash permission issues
3. **Canonical output schema** for standardized cross-model results
4. **Session continuity** via native CLI session IDs
5. **Code Sovereignty** — external model outputs are prototypes, reviewed before applying

See `references/consultation/` for full consultation records.

## Acknowledgments

Inspired by and builds upon:
- [GuDaStudio/codexmcp](https://github.com/GuDaStudio/codexmcp) — Codex MCP bridge patterns
- [GuDaStudio/geminimcp](https://github.com/GuDaStudio/geminimcp) — Gemini MCP bridge patterns
- [GuDaStudio/skills](https://github.com/GuDaStudio/skills) — Agent Skills structure
- [GuDaStudio/commands](https://github.com/GuDaStudio/commands) — RPI workflow theory

## License

MIT
