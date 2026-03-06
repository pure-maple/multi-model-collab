# modelmux

English | [中文](docs/README_CN.md)

Cross-platform multi-model AI collaboration server. Dispatch, broadcast, and orchestrate tasks across **Codex CLI**, **Gemini CLI**, **Claude Code CLI**, **Ollama**, and external **A2A agents** through a unified MCP interface — with built-in smart routing, failover, cost tracking, and multi-agent collaboration.

[![PyPI](https://img.shields.io/pypi/v/modelmux)](https://pypi.org/project/modelmux/)

## Why

Different AI models have different strengths:

| Model | Strengths |
|-------|-----------|
| **Codex** (GPT) | Code generation, algorithms, debugging |
| **Gemini** | Frontend/UI, multimodal, broad knowledge |
| **Claude** | Architecture, reasoning, code review |
| **Ollama** | Free local inference (DeepSeek, Llama, Qwen, etc.) |

modelmux lets any MCP-compatible platform orchestrate tasks across all of them — getting the best of each, with automatic failover, cost tracking, and true multi-agent collaboration.

## Architecture

```
MCP Client (Claude Code / Codex CLI / Gemini CLI / IDE)
    │
    └── modelmux (MCP server, stdio)
        ├── mux_dispatch     → single provider (auto-route, failover)
        ├── mux_broadcast    → parallel multi-provider + comparison
        ├── mux_collaborate  → iterative multi-agent collaboration (A2A)
        ├── mux_workflow     → multi-step pipeline chains
        ├── mux_history      → analytics, cost tracking
        └── mux_check        → availability & config status
            │
            ├── CodexAdapter      → codex exec --json
            ├── GeminiAdapter     → gemini -p -o stream-json
            ├── ClaudeAdapter     → claude -p
            ├── OllamaAdapter     → ollama run <model>
            ├── A2ARemoteAdapter  → external A2A agents (httpx)
            └── Custom Adapters   → user-defined plugins

A2A HTTP Server (modelmux a2a-server)
    ├── GET  /.well-known/agent.json   → Agent Card
    ├── POST / (JSON-RPC 2.0)
    │   ├── tasks/send                 → synchronous task
    │   ├── tasks/get                  → query task state
    │   ├── tasks/cancel               → cancel running task
    │   └── tasks/sendSubscribe        → SSE streaming
    └── TaskStore (in-memory + JSONL persistence)
```

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- At least one model CLI installed:
  - `codex` — `npm i -g @openai/codex`
  - `gemini` — `npm i -g @google/gemini-cli`
  - `claude` — [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  - `ollama` — [Ollama](https://ollama.com)

### Install

```bash
# Recommended: install as MCP server for Claude Code
claude mcp add modelmux -s user -- uvx modelmux

# Or install for all platforms
git clone https://github.com/pure-maple/modelmux.git
cd modelmux && ./install.sh --all

# Quick availability check
modelmux check
```

<details>
<summary>Manual installation for other platforms</summary>

```bash
# Codex CLI (~/.codex/config.toml)
[mcp_servers.modelmux]
command = "uvx"
args = ["modelmux"]

# Gemini CLI (~/.gemini/settings.json)
{"mcpServers": {"modelmux": {"command": "uvx", "args": ["modelmux"]}}}
```

</details>

## Usage

### Dispatch — single provider

```python
# Smart routing (auto-excludes caller, picks best model for the task)
mux_dispatch(provider="auto", task="Implement a binary search tree")

# Explicit provider
mux_dispatch(provider="codex", task="Fix the memory leak in pool.py",
             workdir="/path/to/project", sandbox="write")

# Specific model + multi-turn session
r1 = mux_dispatch(provider="codex", model="gpt-5.4", task="Analyze this codebase")
r2 = mux_dispatch(provider="codex", task="Fix the bug you found",
                   session_id=r1.session_id)

# Local model via Ollama
mux_dispatch(provider="ollama", model="deepseek-r1", task="Explain this algorithm")
```

### Broadcast — parallel multi-provider

```python
# Send to all available providers simultaneously
mux_broadcast(task="Review this API design for security issues")

# Specific providers with structured comparison
mux_broadcast(
    task="Suggest the best data structure for this use case",
    providers=["codex", "gemini", "claude"],
    compare=True  # adds similarity scores, speed ranking
)
```

### Collaborate — multi-agent iteration (A2A)

```python
# Review loop: implement → review → revise until approved
mux_collaborate(
    task="Implement a rate limiter with sliding window",
    pattern="review"  # codex builds, claude reviews, iterate
)

# Consensus: parallel analysis + synthesis
mux_collaborate(task="Evaluate our migration strategy", pattern="consensus")

# Debate: advocate vs critic + arbiter verdict
mux_collaborate(task="Should we use microservices?", pattern="debate")
```

### Workflow — multi-step pipelines

```python
# List available workflows
mux_workflow(workflow="", task="", list_workflows=True)

# Run a built-in or custom workflow
mux_workflow(workflow="review", task="Optimize the database queries")
```

### History & Cost Tracking

```python
# Recent dispatches
mux_history(limit=20)

# Statistics with cost breakdown
mux_history(stats_only=True, costs=True)

# Filter by provider and time range
mux_history(provider="codex", hours=24, costs=True)
```

Token usage is automatically extracted from Codex and Gemini responses. Cost estimation uses configurable per-model pricing.

### Check — availability & config

```python
mux_check()
# Returns: provider availability, caller detection, active profile,
#          policy summary, audit stats, active dispatches
```

## A2A HTTP Server

Expose modelmux as an [A2A protocol](https://google.github.io/A2A/) agent over HTTP:

```bash
# Start with default settings
modelmux a2a-server

# Custom port + authentication
modelmux a2a-server --port 8080 --token my-secret --sandbox write
```

Other A2A-compatible agents can discover and interact with modelmux via:
- `GET /.well-known/agent.json` — Agent Card (capabilities, skills)
- `POST /` — JSON-RPC 2.0 (`tasks/send`, `tasks/get`, `tasks/cancel`, `tasks/sendSubscribe`)

### Connecting to External A2A Agents

Register external agents in your config to use them as providers:

```toml
# ~/.config/modelmux/profiles.toml
[a2a_agents.my-agent]
url = "http://localhost:8080"
token = "secret"
pattern = "code-review"
```

Then dispatch to them like any other provider:

```python
mux_dispatch(provider="my-agent", task="Review this PR")
```

## CLI Commands

```bash
modelmux              # Start MCP server (stdio)
modelmux a2a-server   # Start A2A HTTP server
modelmux dashboard    # Web monitoring dashboard (http://127.0.0.1:41521)
modelmux benchmark    # Run provider benchmark suite
modelmux init         # Interactive configuration wizard
modelmux config       # TUI configuration panel (requires modelmux[tui])
modelmux check        # Check CLI availability
modelmux status       # Monitor active dispatches
modelmux status -w    # Live watch mode (updates every second)
modelmux history      # View recent dispatches
modelmux history --stats --costs   # Statistics with cost breakdown
modelmux export --format csv       # Export history to CSV/JSON/Markdown
modelmux version      # Show version
```

## Configuration

Create `.modelmux/profiles.toml` (project) or `~/.config/modelmux/profiles.toml` (user):

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

# Caller detection
caller_override = ""
auto_exclude_caller = true

# Named profiles
[profiles.budget]
description = "Use cheaper models"
[profiles.budget.providers.codex]
model = "gpt-4.1-mini"
[profiles.budget.providers.gemini]
model = "gemini-2.5-flash"
```

### Policy Engine

Create `~/.config/modelmux/policy.json`:

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
    "token_usage": {
        "input_tokens": 1200,
        "output_tokens": 340,
        "total_tokens": 1540
    },
    "routed_from": "auto",
    "caller_excluded": "claude"
}
```

`token_usage` is included when the provider returns token data (Codex, Gemini). Cost estimation is available via `mux_history(costs=True)`.

## Features

| Feature | Description |
|---------|-------------|
| **Smart Routing** | Auto-route by task keywords + history scoring, auto-exclude caller |
| **Failover** | Auto-retry with next available provider on failure |
| **Profiles** | Named configs for model/API overrides (budget, china, etc.) |
| **Multi-turn** | Session continuity via native CLI session IDs |
| **Broadcast** | Parallel dispatch to multiple providers with comparison |
| **Collaboration** | Iterative multi-agent patterns (review, consensus, debate) |
| **Workflows** | Multi-step pipeline chains with variable substitution |
| **Cost Tracking** | Token usage extraction + per-model cost estimation |
| **A2A Protocol** | HTTP server + client for agent-to-agent interop |
| **Policy Engine** | Rate limits, provider/sandbox blocking |
| **Audit Logging** | Full JSONL audit trail for every dispatch |
| **Real-time Status** | Live dispatch monitoring via CLI or status files |
| **Custom Plugins** | User-defined adapters via config |

## Design Decisions

Architecture jointly designed through multi-model consultation:
- **Claude Opus 4.6** — original proposal and synthesis
- **GPT-5.3-Codex** — recommended unified hub, OPA policy engine
- **Gemini-3.1-Pro-Preview** — recommended A2A protocol backbone

Key consensus: one unified MCP hub (not 3 bridges), MCP-first (no Bash permissions needed), canonical output schema, session continuity, code sovereignty.

See `references/consultation/` for full records.

## License

MIT
