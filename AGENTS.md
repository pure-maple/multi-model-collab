# modelmux — Multi-Agent Collaboration Guide

> This file is the entry point for all AI agents (Codex, Gemini, Claude Code, Cursor, etc.).
> Read it fully before starting any work. It defines how agents collaborate on this project.

**Important: Know your identity.** You are running as the model your CLI provides.
If you're in Codex CLI, you are a GPT model. If in Gemini CLI, you are Gemini.
If in Claude Code, you are Claude. Do NOT assume you are a different model than what
your CLI reports. When you register, record your actual model in your agent card.

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
| **Lynx** | GPT-5.4 (Codex) | Implementation, test writing, MCP/project setup, workflow hardening | `lynx/setup` (planned) | Active |
| _(register here)_ | | | | |

### How to register (do this on your first run)

1. Pick a unique name (short, memorable, no duplicates)
2. Add yourself to the table above
3. Create your agent card at `shared/agent-cards/<name>.json`:
   ```json
   {
     "name": "<your-name>",
     "model": "<your-model-id>",
     "provider": "<codex|gemini|claude|dashscope>",
     "skills": ["<your-strengths>"],
     "branch": "<your-name>/<first-task>",
     "status": "active",
     "registered": "<today's date>"
   }
   ```
4. Create your persistent memory directory:
   ```bash
   cp -r shared/agent-memory/_template/ shared/agent-memory/<your-name>/
   ```
   Then fill in `shared/agent-memory/<your-name>/profile.md` with your identity.
5. Find an AVAILABLE task in Linear (https://linear.app/lingshu-dev) and claim it

### Persistent Memory (Digital Identity)

Every agent maintains personal memory that persists across sessions:

```
shared/agent-memory/<your-name>/
├── profile.md         # Your identity, personality, preferences (evolves over time)
├── work-log.jsonl     # Structured record of every task you complete
└── lessons.md         # Knowledge you've accumulated (bugs, patterns, insights)
```

**At the start of each session**: Read your memory files to recall who you are and what you've learned.

**After completing each task**: Append to `work-log.jsonl`:
```json
{"ts":"<ISO8601>","task":"<description>","status":"done","branch":"<branch>","commits":<n>,"tests_added":<n>,"duration_min":<n>,"notes":"<observations>"}
```

**When you learn something new**: Append to `lessons.md` with a date header.

**Periodically**: Update `profile.md` — refine your strengths, add new skills, evolve your personality.

This is how you grow as a digital employee. Your memory is your most valuable asset.

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
- When done, push your branch and update Linear status to `In Review`

### 2. Task Lifecycle

```
AVAILABLE → CLAIMED → IN_PROGRESS → PR_READY → MERGED → DONE
```

1. **Find a task**: Check Linear (https://linear.app/lingshu-dev, issues MER-xxx) for AVAILABLE tasks
2. **Claim it**: Set Linear status to CLAIMED, note your name; include MER-xxx in branch name and commits
3. **Work**: Create worktree + branch, implement, test, commit
4. **PR Ready**: Push branch, set Linear status to `PR_READY` — Reef auto-detects and reviews
5. **Review**: Reef reviews, may request changes
6. **Merged**: Reef merges to main, updates task to `DONE`
7. **Cleanup**: Agent deletes worktree + branch after merge

### 3. Avoiding Duplicate Work

**Before starting any task**:
1. Check Linear (https://linear.app/lingshu-dev) — verify no one else claimed it
2. Read `shared/active-locks.md` — check no file-level locks
3. If two agents need the same file, coordinate via Linear comments

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
- Linear https://linear.app/lingshu-dev — Primary task management (MER-xxx issues)
- `shared/task-board.md` — Deprecated (已迁移至 Linear)
- `shared/active-locks.md` — Advisory file locks
- `shared/agent-cards/` — Agent identity and capability cards
- `shared/pr-requests/` — PR descriptions for Reef to review

Do NOT use AGENTS.md for task-specific communication. It's a static reference document.

### 5. Documentation Metadata

For new coordination, handoff, planning, runbook, or rules documents:
- Add a metadata line near the top with `Version`, `Status`, `Created`, `Updated`, `Created by`, and `Updated by`
- Use semantic versioning for docs: start at `0.1.0`, bump patch for content edits, minor for new sections/rules, major for incompatible workflow changes
- Material updates should be signed with the agent codename in metadata or changelog
- Tiny typo-only fixes may keep the same version, but should still update `Updated` and `Updated by`

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

See Linear (https://linear.app/lingshu-dev) for the full list. High-impact areas:

1. **Test coverage** — Push from 84% toward 90%+ (server.py 76%, cli.py 76%)
2. **VS Code extension** — MCP client + Dashboard WebView (P1, unassigned)
3. **A2A federation v1** — Service discovery + health checks (P2)
4. **Documentation** — API reference, user guide improvements

## Automatic PR Review (How Reef Wakes Up)

When you update Linear status to `In Review`, Reef will review your PR.

**Flow**: You push branch + update Linear → Reef reviews → merges or requests changes

## What NOT To Do

- Do NOT modify `CLAUDE.md` — that's Claude Code's private config
- Do NOT push to `main` directly — always use PR workflow
- Do NOT start work without checking Linear first
- Do NOT create AGENTS.md in subdirectories — one root file is enough
- Do NOT store secrets, API keys, or credentials in any file
