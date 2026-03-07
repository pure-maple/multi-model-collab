# modelmux — Multi-Agent Collaboration Guide

> This file is the entry point for all AI agents (Codex, Gemini, Claude Code, Cursor, etc.).
> Read it fully before starting any work. It defines how agents collaborate on this project.

## Project Overview

**modelmux** is a cross-platform multi-model AI collaboration MCP server.

- **Source**: `mcp/modelmux/src/modelmux/`
- **Tests**: `mcp/modelmux/tests/`
- **Docs**: `docs/`, `CLAUDE.md`
- **Python**: Use `uv`, not system python. Requires 3.10+
- **Run tests**: `cd mcp/modelmux && uv run --with pytest --with pytest-asyncio python -m pytest tests/ --ignore=tests/test_e2e.py`
- **Lint**: `cd mcp/modelmux && uv run ruff check src/ && uv run ruff format src/`
- **Current version**: v0.29.0 (986 tests, 84% coverage)

## Agent Registry

Every agent MUST register itself by editing the table below and the `shared/agent-cards/` directory.

| Name | Model | Strengths | Current Branch | Status |
|------|-------|-----------|----------------|--------|
| **Reef** | Claude Opus | Architecture, release management, integration, PR review | `main` (coordinator) | Active |
| _(register here)_ | | | | |

### How to register

1. Pick a unique name (short, memorable, no duplicates)
2. Add yourself to the table above
3. Create your agent card at `shared/agent-cards/<name>.json` (see format below)
4. Update `shared/task-board.md` to claim a task

### Agent Card Format

```json
{
  "name": "reef",
  "model": "claude-opus-4-6",
  "provider": "claude",
  "skills": ["architecture", "testing", "release", "pr-review", "a2a-protocol"],
  "branch": "main",
  "status": "active",
  "registered": "2026-03-07",
  "contact": "shared/task-board.md"
}
```

## Collaboration Protocol

### 1. Branch & Worktree Strategy

```
main (protected — only Reef merges)
  |
  +-- reef/<topic>       — Reef's feature branches
  +-- <agent>/<topic>    — Each agent's feature branches
```

**Rules**:
- Each agent works in its own worktree on its own branch
- Branch naming: `<agent-name>/<issue-description>` (e.g., `bolt/vscode-extension`)
- NEVER push directly to `main`
- When done, push your branch and notify Reef via `shared/task-board.md`

### 2. Task Lifecycle

```
AVAILABLE → CLAIMED → IN_PROGRESS → PR_READY → MERGED → DONE
```

1. **Find a task**: Read `shared/task-board.md`, pick an `AVAILABLE` task matching your strengths
2. **Claim it**: Change status to `CLAIMED`, set Owner to your name, commit + push
3. **Work**: Create worktree + branch, implement, test, commit
4. **PR Ready**: Push branch, change task status to `PR_READY` in task-board, describe what you did
5. **Review**: Reef reviews, may request changes
6. **Merged**: Reef merges to main, updates task to `DONE`
7. **Cleanup**: Agent deletes worktree + branch after merge

### 3. Avoiding Duplicate Work

**Before starting any task**:
1. Read `shared/task-board.md` — check no one else claimed it
2. Read `shared/active-locks.md` — check no file-level locks
3. If two agents need the same file, coordinate via task-board comments

**File locking** (advisory):
```markdown
<!-- In shared/active-locks.md -->
| File | Agent | Since | Reason |
|------|-------|-------|--------|
| src/modelmux/server.py | reef | 2026-03-07T12:00 | Adding new MCP tool |
```

Release locks when your PR is submitted. Locks expire after 24h automatically.

### 4. Communication

All communication happens through `shared/` directory files:
- `shared/task-board.md` — Task assignments and status updates
- `shared/active-locks.md` — Advisory file locks
- `shared/agent-cards/` — Agent identity and capability cards
- `shared/pr-requests/` — PR descriptions for Reef to review

Do NOT use AGENTS.md for task-specific communication. It's a static reference document.

## Model Strengths Guide

Based on evaluation data (95 API calls across 5 dimensions, 5 models):

### Task-Model Matching

| Task Type | Best Models | Why |
|-----------|------------|-----|
| **Code Review / Bug Finding** | Claude Opus, kimi-k2.5 | Logic flow tracing, subtle bug detection |
| **Architecture Design** | Claude Opus, MiniMax-M2.5 | Systemic thinking, boundary analysis |
| **Code Generation** | GPT (Codex), qwen3-coder-plus | Fast, accurate implementation |
| **Test Writing** | Claude Opus, GPT (Codex) | Coverage-aware, edge case thinking |
| **Documentation** | Claude Opus, qwen3.5-plus | Clear structure, bilingual |
| **Quick Tasks (< 1 min)** | qwen3-coder-plus (15s) | Fastest response |
| **Deep Analysis** | qwen3.5-plus (90s) | Most thorough |
| **Cross-Review** | kimi + MiniMax pair | 60% overlap + 20% unique each = high coverage |

### For Agents Using modelmux

You can leverage modelmux itself for multi-model collaboration:

```bash
# Quick dispatch to a specific model
modelmux dispatch --provider codex --task "implement feature X"

# Cross-model review
modelmux broadcast --providers codex,gemini --task "review this code" --compare

# Deep collaboration
modelmux dispatch --provider dashscope --model kimi-k2.5 --task "find bugs in server.py"
```

## Git Conventions

- **Commit messages**: `<type>: <description>` (types: feat, fix, test, docs, refactor, release)
- **Git identity**: Use your own or project default `pure-maple <hzlhu@qq.com>`
- **Test before commit**: Always run tests and ensure they pass
- **No force push**: Never force-push to any shared branch

## Priority Tasks (Current Sprint)

See `shared/task-board.md` for the full list. High-impact areas:

1. **Test coverage** — Push from 84% toward 90%+ (server.py 76%, cli.py 76%)
2. **VS Code extension** — MCP client + Dashboard WebView (P1, unassigned)
3. **A2A federation v1** — Service discovery + health checks (P2)
4. **Documentation** — API reference, user guide improvements

## What NOT To Do

- Do NOT modify `CLAUDE.md` — that's Claude Code's private config
- Do NOT push to `main` directly — always use PR workflow via task-board
- Do NOT start work without checking task-board first
- Do NOT create AGENTS.md in subdirectories — one root file is enough
- Do NOT store secrets, API keys, or credentials in any file
