---
name: multi-model-collab
description: >
  Cross-platform multi-model AI collaboration. Dispatches tasks to Codex CLI,
  Gemini CLI, or Claude Code CLI and returns structured results. Use this skill
  when the user wants multi-model collaboration, cross-model code review, a
  second opinion from another AI, comparing outputs from different models,
  mentions "ask Codex/Gemini", or when a task would benefit from leveraging
  multiple AI models' complementary strengths.
---

# Multi-Model AI Collaboration

Orchestrate tasks across Codex, Gemini, and Claude, combining each model's
strengths for better results.

## Execution Method (by priority)

### Priority 1: MCP Tool (recommended)

If the `collab_dispatch` MCP tool is available, use it directly.
No tmux, no Bash permissions needed.

```
collab_dispatch(
  provider="codex",           # "codex" | "gemini" | "claude"
  task="Review this code for security issues",
  workdir="/path/to/project",
  sandbox="read-only",        # "read-only" | "write" | "full"
  timeout=300
)
```

Use `collab_check()` to see which model CLIs are available.

### Priority 2: Bash Scripts (fallback)

If MCP tools are not available, use tmux-based shell scripts in `scripts/`.
Requires Bash permissions and tmux installed.

```bash
# Start session → dispatch → collect → stop
bash <skill-dir>/scripts/session.sh start
bash <skill-dir>/scripts/dispatch.sh --session <id> --model codex --prompt "..."
bash <skill-dir>/scripts/collect.sh --session <id> --wait-all
bash <skill-dir>/scripts/session.sh stop <id>
```

### Priority 3: Pure Analysis (degraded)

If neither MCP nor Bash is available (e.g., in a restricted subagent),
simulate multi-perspective analysis by reasoning from each model's known
strengths. Clearly state this is single-model analysis, not actual
multi-model collaboration.

## Model Strengths & Routing

| Task Type | Best Model | Reason |
|-----------|-----------|--------|
| Backend / algorithms / debugging | **Codex** | Strong code generation and logical reasoning |
| Frontend / UI / CSS / React | **Gemini** | Design sense and multimodal capability |
| Architecture / review / synthesis | **Claude** | Deep reasoning and quality control |
| Analysis / audit | **Both simultaneously** | Cross-validation eliminates blind spots |

## Workflow Modes

### Parallel Fan-Out

Send tasks to multiple models simultaneously, then synthesize.

```
# Dispatch to both models in parallel
result_codex = collab_dispatch(provider="codex", task="Implement the API endpoint")
result_gemini = collab_dispatch(provider="gemini", task="Build the React component")
# Then synthesize both results
```

### Sequential Pipeline

Chain models: output of one feeds into the next.

```
# Step 1: Codex generates code
code = collab_dispatch(provider="codex", task="Implement binary search")
# Step 2: Gemini reviews it
review = collab_dispatch(provider="gemini", task=f"Review this code:\n{code}")
```

### Consensus / Dual-LGTM

Send same task to multiple models, compare results. Both must approve.

```
review_a = collab_dispatch(provider="codex", task=f"Review:\n{code}")
review_b = collab_dispatch(provider="gemini", task=f"Review:\n{code}")
# Compare and merge findings
```

## Multi-Turn Sessions

Pass `session_id` from a previous result to continue the conversation:

```
r1 = collab_dispatch(provider="codex", task="Analyze this codebase")
# Continue the same session
r2 = collab_dispatch(provider="codex", task="Now fix the bug you found",
                     session_id=r1.session_id)
```

## Code Sovereignty

When receiving code from external models:
1. External models return **prototypes only** — treat as suggestions
2. Always use **sandbox="read-only"** unless the user explicitly requests write access
3. **Review and rewrite** external code before applying to the project
4. Never blindly execute commands suggested by external models

## Output Schema

All results follow the canonical schema:

```json
{
  "run_id": "a1b2c3d4",
  "provider": "codex",
  "status": "success",
  "summary": "First 200 chars of response...",
  "output": "Full model response text",
  "session_id": "uuid-for-multi-turn",
  "duration_seconds": 12.5
}
```

## Error Handling

- If a model CLI is not installed, `collab_check()` will show it as unavailable
- If a task times out, the result status will be "timeout" with partial output
- If a model returns an error, the result will include the error message
- Always report which models were used and their results to the user
