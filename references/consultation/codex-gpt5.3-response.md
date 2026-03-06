OpenAI Codex v0.110.0 (research preview)
--------
workdir: ~/dev/multi-model-collab
model: gpt-5.3-codex
provider: openai
approval: never
sandbox: read-only
reasoning effort: xhigh
reasoning summaries: none
session id: 019cbd6a-d7d9-7e21-b154-85c20e029d98
--------
user
Context from file /tmp/ai-collab/consultation-prompt.md:
---
## Architecture Consultation: Cross-Platform Multi-Model AI Collaboration Skill

We (Claude Code / Anthropic Claude Opus 4.6) are designing an open-source Agent Skill that enables **cross-platform multi-model AI collaboration** among Claude Code, Codex CLI, and Gemini CLI. We'd like your expert input on the architecture.

---

### Background & Motivation

The three major coding CLI agents (Claude Code, Codex CLI, Gemini CLI) each have unique strengths:
- **Claude Code**: Strong at architecture, reasoning, synthesis, code review
- **Codex CLI**: Strong at code generation, algorithm implementation, bug fixes
- **Gemini CLI**: Good at frontend design, multimodal tasks, broad knowledge

We want to build a **single Agent Skill** (following the Agent Skills open standard) that allows ANY of these platforms—or any IDE (VS Code, Cursor, Windsurf, Cline)—to orchestrate tasks across all three models.

### What We've Built So Far

**Phase 1 (tmux prototype)**: Shell scripts that manage tmux sessions, dispatch tasks to codex/gemini CLIs in parallel, and collect structured JSON output. This works when called directly from the main agent, but **fails in subagent contexts** due to:

- Claude Code subagents cannot get Bash permissions (known bugs #26479, #24307, #11380)
- `mode: "bypassPermissions"` doesn't propagate to child agents
- Every Bash call triggers a user-facing permission prompt, creating "approval storms" (30+ manual approvals per session)
- The permission system is fragmented: subagents don't inherit parent's `settings.local.json`

### Proposed New Architecture: MCP-First with 3-Level Fallback

```
Priority 1: MCP Bridge Servers (no Bash permission needed, cross-platform)
  ┌─────────────────────────────────────────────────┐
  │  Any MCP Client (Claude Code / Codex / Gemini / IDE)  │
  │                                                        │
  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
  │  │ codex-bridge  │  │gemini-bridge │  │claude-bridge │ │
  │  │ (MCP Server)  │  │(MCP Server)  │  │(MCP Server)  │ │
  │  │              │  │              │  │              │ │
  │  │ tool:        │  │ tool:        │  │ tool:        │ │
  │  │ codex_exec() │  │ gemini_exec()│  │ claude_exec()│ │
  │  │   ↓          │  │   ↓          │  │   ↓          │ │
  │  │ subprocess:  │  │ subprocess:  │  │ subprocess:  │ │
  │  │ codex exec   │  │ gemini -p    │  │ claude -p    │ │
  │  └──────────────┘  └──────────────┘  └──────────────┘ │
  └─────────────────────────────────────────────────────────┘

Priority 2: Bash + pre-configured global permissions (simpler setup)
  - tmux-based parallel dispatch via shell scripts
  - User adds Bash(codex:*), Bash(gemini:*) to ~/.claude/settings.json

Priority 3: Pure prompt-based multi-perspective analysis (degraded mode)
  - No external calls; the agent simulates multiple viewpoints
```

### Sub-Agent Spawning (Tree-Shaped Collaboration)

Each CLI has internal sub-agent capabilities:
- **Claude Code**: Team Mode (TeamCreate/SendMessage/TaskCreate), git worktree isolation
- **Codex CLI**: Multi-agent workflows, /fork, forked/fresh spawning, batch via CSV
- **Gemini CLI**: Subagents (experimental, sequential only), /agents, Conductor extension, A2A protocol

The skill would instruct each CLI to use its native sub-agent features for complex tasks:
```
Top-level orchestrator (any platform)
  ├── codex_exec("Implement backend API")
  │     └── Codex internally spawns 3 sub-agents for different endpoints
  ├── gemini_exec("Build React frontend")
  │     └── Gemini internally delegates to specialized agents
  └── claude_exec("Write integration tests")
        └── Claude uses Team Mode to parallelize test writing
```

### Specific Questions

1. **Architecture**: Is MCP-first the right approach? Should we use Codex's native `codex mcp server` directly instead of a custom bridge? What about Gemini's native MCP support?

2. **Permission model**: Any better solutions for the subagent Bash permission problem? Are there upcoming platform features we should wait for?

3. **Cross-platform portability**: The Agent Skills standard (.claude/skills/, .agents/skills/, .gemini/skills/) provides the entry point. But each platform discovers and loads skills differently. How do we handle platform-specific differences in one skill?

4. **Output format standardization**: Codex uses `--json` (JSONL events), Gemini uses `-o json` (single JSON), Claude uses `-p` (text). How should we standardize the output parsing?

5. **Context efficiency**: MCP tool descriptions consume ~500 tokens permanently. Any techniques to minimize this? Should we use a single unified MCP server with multiple tools instead of 3 separate servers?

6. **Sub-agent orchestration**: How should we handle the tree-shaped multi-level spawning when each CLI has completely different sub-agent APIs? Is there a unified abstraction layer?

7. **Existing community solutions**: Do you know of any open-source projects that already solve multi-model CLI orchestration? We found:
   - GuDaStudio's codexmcp/geminimcp (basic MCP wrappers)
   - Maestro-Gemini (Node.js parallel dispatch for Gemini)
   - Various prompt engineering approaches
   Are there better ones?

8. **Your platform's unique capabilities**: What features of YOUR platform (Codex/Gemini) are we potentially underutilizing? What would YOU recommend as the ideal integration point for cross-model collaboration?

9. **Security considerations**: The skill essentially gives one AI agent the ability to invoke other AI agents. What security boundaries should we enforce? How do we prevent prompt injection chains across models?

10. **Practical recommendation**: If you were building this from scratch today, what would your architecture look like? Please be specific with code examples or configuration snippets.

---

Please be thorough and technical. We value depth over brevity. Include code examples, configuration snippets, and specific tool/flag references where helpful.
---

Task: You are being consulted as an architecture expert. Please read the following consultation document carefully and provide thorough, detailed answers to ALL 10 questions. Be specific with code examples, configuration snippets, and concrete recommendations. Pay special attention to Question 8 (your platform's unique capabilities) - tell us what Codex CLI features we might be underutilizing. Also focus on Question 10 (practical recommendation) - give us your ideal architecture with code. Do not be brief - we want depth and detail.
mcp startup: no servers
codex
I’ll treat this as a skill-architecture design review and answer all 10 questions with concrete implementation guidance. First I’m loading the `skill-creator` instructions from your AGENTS config, then I’ll verify current Codex/Gemini/Claude CLI and MCP details before drafting the recommendation.
exec
/bin/zsh -lc "cat '~/.codex/skills/.system/skill-creator/SKILL.md'" in ~/dev/multi-model-collab succeeded in 51ms:
---
name: skill-creator
description: Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Codex's capabilities with specialized knowledge, workflows, or tool integrations.
metadata:
  short-description: Create or update a skill
---

# Skill Creator

This skill provides guidance for creating effective skills.

## About Skills

Skills are modular, self-contained folders that extend Codex's capabilities by providing
specialized knowledge, workflows, and tools. Think of them as "onboarding guides" for specific
domains or tasks—they transform Codex from a general-purpose agent into a specialized agent
equipped with procedural knowledge that no model can fully possess.

### What Skills Provide

codex
I’ve loaded the skill-creator guidance and will use it as a design lens (progressive disclosure, minimal context, reusable scripts). Next I’m verifying current MCP/CLI capabilities and concrete flags across Codex, Gemini, and Claude so the recommendations are grounded in current behavior.
🌐 Searching the web...
🌐 Searched: OpenAI Codex CLI MCP server command codex mcp server official docs
🌐 Searching the web...
🌐 Searched: site:github.com/openai/codex README mcp add codex mcp
codex
I’m now collecting primary docs for exact CLI/MCP flags so the examples are reproducible, then I’ll map those capabilities to your 10 questions. I’ll also pull a few community repos to benchmark what’s already solved versus what’s still missing.
🌐 Searching the web...
🌐 Searched: github openai codex cli repository
🌐 Searching the web...
🌐 Searched: https://github.com/openai/codex
🌐 Searching the web...
🌐 Searched: https://developers.openai.com/codex
🌐 Searching the web...
🌐 Searched: https://developers.openai.com/codex/cli/reference
🌐 Searching the web...
🌐 Searched: https://github.com/openai/codex/tree/main/docs
🌐 Searching the web...
🌐 Searched: https://raw.githubusercontent.com/openai/codex/main/docs/exec.md
codex
I confirmed the open-source Codex repo and docs entry points. I’m now extracting specific flags/options from those docs pages (and equivalent Gemini/Claude references) so the orchestration examples use real commands instead of assumptions.
🌐 Searching the web...
🌐 Searched: '--json' in https://developers.openai.com/codex/cli/reference
🌐 Searching the web...
🌐 Searched: https://developers.openai.com/codex/cli/reference
🌐 Searching the web...
🌐 Searched: https://developers.openai.com/codex/multi-agent
🌐 Searching the web...
🌐 Searched: '#  Multi-agents' in https://developers.openai.com/codex/multi-agent
🌐 Searching the web...
🌐 Searched: https://developers.openai.com/codex/guides/agents-sdk
🌐 Searching the web...
🌐 Searched: https://developers.openai.com/codex/config-reference
codex
I extracted concrete Codex CLI references for `codex exec`, JSONL output, MCP registration, and built-in `codex mcp-server`. Next I’m pulling Gemini and Claude primary docs in the same level of detail, then I’ll synthesize into a concrete architecture.
🌐 Searching the web...
🌐 Searched: 'mcp_servers' in https://developers.openai.com/codex/config-reference
🌐 Searching the web...
🌐 Searched: https://developers.openai.com/codex/noninteractive
🌐 Searching the web...
🌐 Searched: 'JSONL' in https://developers.openai.com/codex/noninteractive
🌐 Searching the web...
🌐 Searched: github.com/google-gemini/gemini-cli README MCP settings.json mcpServers
🌐 Searching the web...
🌐 Searched: https://github.com/google-gemini/gemini-cli
🌐 Searching the web...
🌐 Searched: https://geminicli.com/docs/
🌐 Searching the web...
🌐 Searched: https://geminicli.com/docs/reference/commands/
🌐 Searching the web...
🌐 Searched: '-p' in https://geminicli.com/docs/cli/headless/
🌐 Searching the web...
🌐 Searched: '--output-format' in https://geminicli.com/docs/reference/commands/
🌐 Searching the web...
🌐 Searched: site:geminicli.com/docs gemini --output-format
🌐 Searching the web...
🌐 Searched: 'mcpServers' in https://geminicli.com/docs/tools/mcp-server/
codex
I have enough primary data for Codex and most Gemini details; I’m doing one last verification pass on Claude/Gemini MCP server roles (client vs server) and then I’ll deliver the full 10-question architecture recommendation with concrete config/code.
🌐 Searching the web...
🌐 Searched: site:docs.anthropic.com Claude Code MCP servers configuration
🌐 Searching the web...
🌐 Searched: https://docs.anthropic.com/en/docs/claude-code/mcp
🌐 Searching the web...
🌐 Searched: 'Use Claude Code as an MCP server' in https://docs.anthropic.com/en/docs/claude-code/mcp
codex
`skill-creator` lens applied: I optimized for a lean always-loaded surface, progressive disclosure, and reusable adapters/scripts.

As of **March 5, 2026**, your proposed direction is strong. I would make one major adjustment: use **one MCP orchestration hub** (single tool surface), not three separate bridge servers exposed to clients.

## 1. Architecture: MCP-first? Native `codex mcp-server` vs custom bridges?
Yes, MCP-first is the right primary architecture.

Use this split:
1. **Client-facing**: one MCP server (`collab-hub`) exposed to Claude/Codex/Gemini/IDE.
2. **Provider adapters (internal)**: adapters that call `codex exec`, `gemini -p`, and your current Claude non-interactive path.
3. **Optional advanced mode**: allow direct native servers (`codex mcp-server`, `claude mcp serve`) when you explicitly want their native toolsets.

Why:
1. Native `codex mcp-server` and `claude mcp serve` are real and useful.
2. But direct native exposure makes policy/output normalization/security harder.
3. A custom hub gives one policy layer, one output schema, one audit trail.

Code sketch:
```txt
Any MCP client
  -> collab-hub MCP (tools: dispatch, status, cancel, fetch_artifact)
    -> adapter-codex (codex exec --json ...)
    -> adapter-gemini (gemini -p ... --output-format json/stream-json)
    -> adapter-claude (your existing non-interactive wrapper)
```

## 2. Permission model: better solution for subagent Bash approval storms?
Given your constraints, avoid subagent Bash entirely.

Recommended:
1. Main agent and subagents call **only MCP tools** (`collab_dispatch`), not Bash.
2. Run CLI invocations inside the MCP hub process, not inside child subagents.
3. Enforce provider-specific execution policy in the hub.
4. Keep fallback Bash mode only for environments where users can pre-allow commands.

Claude-specific notes from docs:
1. Subagents inherit tool context; you can restrict via `tools`/`disallowedTools`.
2. Parent `bypassPermissions` takes precedence.
3. Claude subagents cannot recursively spawn subagents.

Inference: your currently observed permission propagation bugs are architectural blockers; I would not wait for platform fixes before shipping v1.

## 3. Cross-platform portability: one skill across `.claude/.codex/.gemini`?
Use a **single canonical core** plus thin platform wrappers.

Structure:
```txt
multi-model-collab-skill/
  core/
    prompts/
    schemas/
    scripts/
    references/
  adapters/
    claude/SKILL.md
    codex/SKILL.md
    gemini/SKILL.md
  install/
    install-claude.sh
    install-codex.sh
    install-gemini.sh
```

Rules:
1. Put real logic in `core/`.
2. Keep each platform `SKILL.md` as adapter glue only.
3. Install scripts copy/symlink wrapper files into platform-specific skill directories.
4. Feature-detect capabilities at runtime (MCP available, headless available, subagents available).

## 4. Output standardization: Codex JSONL, Gemini JSON, Claude text
Define a canonical envelope and force every adapter to emit it.

Canonical result:
```json
{
  "run_id": "uuid",
  "provider": "codex|gemini|claude",
  "status": "success|partial|error",
  "summary": "string",
  "artifacts": [{"type":"patch|report|file","path":"string","sha256":"string"}],
  "usage": {"input_tokens":0,"output_tokens":0,"latency_ms":0},
  "events": [{"t":"timestamp","type":"tool|message|error","payload":{}}],
  "raw_ref": "path/to/raw.log"
}
```

Adapter strategy:
1. **Codex**: parse JSONL from `codex exec --json`; optionally use `--output-schema` + `-o` for stable final payload.
2. **Gemini**: use `--output-format json` for one-shot or streaming JSON for event capture.
3. **Claude**: wrap prompt with strict JSON schema contract and robust JSON extraction (fenced block + validator + retry).

## 5. Context efficiency: MCP tool descriptions are expensive
Use **one MCP server with minimal tools**, ideally:
1. `collab_dispatch`
2. `collab_status`
3. `collab_fetch_artifact`

Do not expose one tool per provider unless required.

Also:
1. Keep tool descriptions very short.
2. Move long instructions to references loaded on demand.
3. Return artifact pointers instead of huge inline payloads.
4. Use client-side tool filters where supported (`enabled_tools`, `includeTools`).
5. Enforce output truncation and artifact offload.

## 6. Sub-agent orchestration with different APIs
Use a unified orchestration abstraction:

```ts
type TaskNode = {
  id: string;
  provider: "codex"|"gemini"|"claude";
  objective: string;
  strategy: "single"|"provider_native_fanout";
  max_depth: number;
  budget: {token:number, seconds:number};
};
```

Execution policy:
1. Global depth limit: default `1` cross-provider, optional `2` in trusted mode.
2. Provider-native fanout allowed only inside adapter.
3. Parent orchestrator never trusts child-generated commands directly.
4. All child outputs revalidated before merge.

Inference: for reliability, assume Gemini subagent behavior is experimental and volatile; keep provider-native fanout optional.

## 7. Existing open-source solutions: what exists and gaps
Good building blocks exist, but no complete production-grade cross-model orchestrator yet.

Useful projects:
1. `kky42/codex-as-mcp` (Codex via MCP bridge).
2. `choplin/mcp-gemini-cli` (simple Gemini wrapper).
3. `centminmod/gemini-cli-mcp-server` (larger Gemini MCP wrapper).
4. `ZainRizvi/gemini-cli-mcp` (basic CLI bridge).

Common gaps:
1. No unified canonical output/event schema.
2. Limited policy engine and provenance controls.
3. Weak prompt-injection boundaries across model hops.
4. Sparse reliability features (timeouts, retries, idempotency, cancel/resume).

## 8. Codex capabilities likely underutilized
This is where I’d push harder on Codex:

1. `codex exec --json` gives structured JSONL events.
2. `--output-schema` and `-o/--output-last-message` make automation stable.
3. `codex mcp-server` lets Codex act as MCP server.
4. `codex mcp add/get/list/login` supports stdio + HTTP with OAuth.
5. `features.multi_agent` exposes `spawn_agent`, `wait`, `spawn_agents_on_csv`.
6. Config-level MCP controls are strong: required server boot, startup/tool timeouts, enabled/disabled tool lists.
7. `codex fork` enables branch-style conversational splitting.

Practical pattern:
```bash
codex exec \
  --json \
  --output-schema ./schemas/review.schema.json \
  -o ./out/review.json \
  --ask-for-approval never \
  --sandbox workspace-write \
  "Review this PR for security and regressions"
```

## 9. Security boundaries and prompt-injection chain defense
Treat every model output as untrusted input.

Minimum controls:
1. **Policy gate** before every provider invocation.
2. **Schema validation** for all model outputs.
3. **Command allowlist** for executable actions.
4. **Secret redaction** in prompts, logs, and artifacts.
5. **Provenance tags** (`source_provider`, `run_id`, `trust_level`) on every artifact.
6. **No implicit execution** of one model’s suggested commands.
7. **Depth/fanout/time/token budgets** to prevent runaway trees.
8. **Network egress controls** per provider executor.
9. **Immutable audit log** for every tool call and model hop.

Example policy fragment:
```rego
package collab.authz

default allow = false

allow {
  input.tool == "collab_dispatch"
  input.provider == "codex"
  input.capabilities.allow_shell == false
}

allow {
  input.tool == "collab_dispatch"
  input.provider == "gemini"
  input.capabilities.allow_network == false
}
```

## 10. If building from scratch today: concrete architecture
I’d ship this in 3 phases.

### Phase A (MVP, 1-2 weeks)
1. Single MCP hub with `dispatch/status/fetch_artifact`.
2. Adapters for Codex + Gemini + Claude wrappers.
3. Canonical output schema + raw logs.
4. Hard timeouts, retry once, deterministic error codes.

### Phase B (hardening)
1. OPA-style policy engine.
2. Artifact store + provenance.
3. Secret scrubber.
4. Cancellation and resume.

### Phase C (advanced)
1. Optional provider-native subagent fanout.
2. Adaptive routing (`auto` provider based on task type).
3. Budget-aware planner.

MCP hub skeleton:
```ts
import { z } from "zod";

const DispatchIn = z.object({
  provider: z.enum(["auto","codex","gemini","claude"]),
  task: z.string().min(1),
  mode: z.enum(["analyze","implement","review","test"]).default("analyze"),
  timeout_sec: z.number().int().min(10).max(3600).default(600),
  output_schema: z.any().optional()
});

server.tool("collab_dispatch", DispatchIn, async (input) => {
  policy.check(input);
  const run = await orchestrator.start(input);
  return { run_id: run.id, status: run.status, summary: run.summary };
});
```

Codex adapter:
```ts
const args = [
  "exec", "--json",
  "--ask-for-approval", "never",
  "--sandbox", "workspace-write",
  task
];
if (schemaPath) args.push("--output-schema", schemaPath, "-o", outputPath);
```

Gemini adapter:
```ts
const args = ["-p", task, "--output-format", stream ? "stream-json" : "json"];
```

Claude adapter (inference from your current prototype):
```ts
const wrapped = makeStrictJsonPrompt(task, schema);
const args = ["-p", wrapped]; // replace with your verified non-interactive flags
```

Client configs:

Claude:
```bash
claude mcp add collab --scope project -- node /opt/collab-hub/server.js
```

Codex (`~/.codex/config.toml`):
```toml
[mcp_servers.collab]
command = "node"
args = ["/opt/collab-hub/server.js"]
required = true
enabled_tools = ["collab_dispatch","collab_status","collab_fetch_artifact"]
tool_timeout_sec = 180
startup_timeout_sec = 20
```

Gemini (`~/.gemini/settings.json`):
```json
{
  "mcpServers": {
    "collab": {
      "command": "node",
      "args": ["/opt/collab-hub/server.js"],
      "timeout": 30000,
      "includeTools": ["collab_dispatch", "collab_status", "collab_fetch_artifact"]
    }
  }
}
```

## Sources
- OpenAI Codex CLI command options: https://developers.openai.com/codex/cli/reference
- OpenAI Codex non-interactive mode: https://developers.openai.com/codex/noninteractive
- OpenAI Codex config reference: https://developers.openai.com/codex/config-reference
- OpenAI Codex multi-agents: https://developers.openai.com/codex/multi-agent
- OpenAI Docs MCP page: https://platform.openai.com/docs/docs-mcp
- Gemini CLI headless mode: https://geminicli.com/docs/cli/headless/
- Gemini CLI cheatsheet: https://geminicli.com/docs/cli/cli-reference/
- Gemini CLI MCP servers: https://geminicli.com/docs/tools/mcp-server/
- Gemini CLI subagents: https://geminicli.com/docs/core/subagents/
- Gemini CLI remote subagents (A2A): https://geminicli.com/docs/core/remote-agents/
- Gemini CLI trusted folders: https://geminicli.com/docs/cli/trusted-folders/
- Gemini CLI settings: https://geminicli.com/docs/cli/settings/
- Claude Code MCP docs: https://docs.anthropic.com/en/docs/claude-code/mcp
- Claude Code subagents docs: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Community: https://github.com/kky42/codex-as-mcp
- Community: https://github.com/choplin/mcp-gemini-cli
- Community: https://github.com/centminmod/gemini-cli-mcp-server
- Community: https://github.com/ZainRizvi/gemini-cli-mcp
tokens used
134,247
`skill-creator` lens applied: I optimized for a lean always-loaded surface, progressive disclosure, and reusable adapters/scripts.

As of **March 5, 2026**, your proposed direction is strong. I would make one major adjustment: use **one MCP orchestration hub** (single tool surface), not three separate bridge servers exposed to clients.

## 1. Architecture: MCP-first? Native `codex mcp-server` vs custom bridges?
Yes, MCP-first is the right primary architecture.

Use this split:
1. **Client-facing**: one MCP server (`collab-hub`) exposed to Claude/Codex/Gemini/IDE.
2. **Provider adapters (internal)**: adapters that call `codex exec`, `gemini -p`, and your current Claude non-interactive path.
3. **Optional advanced mode**: allow direct native servers (`codex mcp-server`, `claude mcp serve`) when you explicitly want their native toolsets.

Why:
1. Native `codex mcp-server` and `claude mcp serve` are real and useful.
2. But direct native exposure makes policy/output normalization/security harder.
3. A custom hub gives one policy layer, one output schema, one audit trail.

Code sketch:
```txt
Any MCP client
  -> collab-hub MCP (tools: dispatch, status, cancel, fetch_artifact)
    -> adapter-codex (codex exec --json ...)
    -> adapter-gemini (gemini -p ... --output-format json/stream-json)
    -> adapter-claude (your existing non-interactive wrapper)
```

## 2. Permission model: better solution for subagent Bash approval storms?
Given your constraints, avoid subagent Bash entirely.

Recommended:
1. Main agent and subagents call **only MCP tools** (`collab_dispatch`), not Bash.
2. Run CLI invocations inside the MCP hub process, not inside child subagents.
3. Enforce provider-specific execution policy in the hub.
4. Keep fallback Bash mode only for environments where users can pre-allow commands.

Claude-specific notes from docs:
1. Subagents inherit tool context; you can restrict via `tools`/`disallowedTools`.
2. Parent `bypassPermissions` takes precedence.
3. Claude subagents cannot recursively spawn subagents.

Inference: your currently observed permission propagation bugs are architectural blockers; I would not wait for platform fixes before shipping v1.

## 3. Cross-platform portability: one skill across `.claude/.codex/.gemini`?
Use a **single canonical core** plus thin platform wrappers.

Structure:
```txt
multi-model-collab-skill/
  core/
    prompts/
    schemas/
    scripts/
    references/
  adapters/
    claude/SKILL.md
    codex/SKILL.md
    gemini/SKILL.md
  install/
    install-claude.sh
    install-codex.sh
    install-gemini.sh
```

Rules:
1. Put real logic in `core/`.
2. Keep each platform `SKILL.md` as adapter glue only.
3. Install scripts copy/symlink wrapper files into platform-specific skill directories.
4. Feature-detect capabilities at runtime (MCP available, headless available, subagents available).

## 4. Output standardization: Codex JSONL, Gemini JSON, Claude text
Define a canonical envelope and force every adapter to emit it.

Canonical result:
```json
{
  "run_id": "uuid",
  "provider": "codex|gemini|claude",
  "status": "success|partial|error",
  "summary": "string",
  "artifacts": [{"type":"patch|report|file","path":"string","sha256":"string"}],
  "usage": {"input_tokens":0,"output_tokens":0,"latency_ms":0},
  "events": [{"t":"timestamp","type":"tool|message|error","payload":{}}],
  "raw_ref": "path/to/raw.log"
}
```

Adapter strategy:
1. **Codex**: parse JSONL from `codex exec --json`; optionally use `--output-schema` + `-o` for stable final payload.
2. **Gemini**: use `--output-format json` for one-shot or streaming JSON for event capture.
3. **Claude**: wrap prompt with strict JSON schema contract and robust JSON extraction (fenced block + validator + retry).

## 5. Context efficiency: MCP tool descriptions are expensive
Use **one MCP server with minimal tools**, ideally:
1. `collab_dispatch`
2. `collab_status`
3. `collab_fetch_artifact`

Do not expose one tool per provider unless required.

Also:
1. Keep tool descriptions very short.
2. Move long instructions to references loaded on demand.
3. Return artifact pointers instead of huge inline payloads.
4. Use client-side tool filters where supported (`enabled_tools`, `includeTools`).
5. Enforce output truncation and artifact offload.

## 6. Sub-agent orchestration with different APIs
Use a unified orchestration abstraction:

```ts
type TaskNode = {
  id: string;
  provider: "codex"|"gemini"|"claude";
  objective: string;
  strategy: "single"|"provider_native_fanout";
  max_depth: number;
  budget: {token:number, seconds:number};
};
```

Execution policy:
1. Global depth limit: default `1` cross-provider, optional `2` in trusted mode.
2. Provider-native fanout allowed only inside adapter.
3. Parent orchestrator never trusts child-generated commands directly.
4. All child outputs revalidated before merge.

Inference: for reliability, assume Gemini subagent behavior is experimental and volatile; keep provider-native fanout optional.

## 7. Existing open-source solutions: what exists and gaps
Good building blocks exist, but no complete production-grade cross-model orchestrator yet.

Useful projects:
1. `kky42/codex-as-mcp` (Codex via MCP bridge).
2. `choplin/mcp-gemini-cli` (simple Gemini wrapper).
3. `centminmod/gemini-cli-mcp-server` (larger Gemini MCP wrapper).
4. `ZainRizvi/gemini-cli-mcp` (basic CLI bridge).

Common gaps:
1. No unified canonical output/event schema.
2. Limited policy engine and provenance controls.
3. Weak prompt-injection boundaries across model hops.
4. Sparse reliability features (timeouts, retries, idempotency, cancel/resume).

## 8. Codex capabilities likely underutilized
This is where I’d push harder on Codex:

1. `codex exec --json` gives structured JSONL events.
2. `--output-schema` and `-o/--output-last-message` make automation stable.
3. `codex mcp-server` lets Codex act as MCP server.
4. `codex mcp add/get/list/login` supports stdio + HTTP with OAuth.
5. `features.multi_agent` exposes `spawn_agent`, `wait`, `spawn_agents_on_csv`.
6. Config-level MCP controls are strong: required server boot, startup/tool timeouts, enabled/disabled tool lists.
7. `codex fork` enables branch-style conversational splitting.

Practical pattern:
```bash
codex exec \
  --json \
  --output-schema ./schemas/review.schema.json \
  -o ./out/review.json \
  --ask-for-approval never \
  --sandbox workspace-write \
  "Review this PR for security and regressions"
```

## 9. Security boundaries and prompt-injection chain defense
Treat every model output as untrusted input.

Minimum controls:
1. **Policy gate** before every provider invocation.
2. **Schema validation** for all model outputs.
3. **Command allowlist** for executable actions.
4. **Secret redaction** in prompts, logs, and artifacts.
5. **Provenance tags** (`source_provider`, `run_id`, `trust_level`) on every artifact.
6. **No implicit execution** of one model’s suggested commands.
7. **Depth/fanout/time/token budgets** to prevent runaway trees.
8. **Network egress controls** per provider executor.
9. **Immutable audit log** for every tool call and model hop.

Example policy fragment:
```rego
package collab.authz

default allow = false

allow {
  input.tool == "collab_dispatch"
  input.provider == "codex"
  input.capabilities.allow_shell == false
}

allow {
  input.tool == "collab_dispatch"
  input.provider == "gemini"
  input.capabilities.allow_network == false
}
```

## 10. If building from scratch today: concrete architecture
I’d ship this in 3 phases.

### Phase A (MVP, 1-2 weeks)
1. Single MCP hub with `dispatch/status/fetch_artifact`.
2. Adapters for Codex + Gemini + Claude wrappers.
3. Canonical output schema + raw logs.
4. Hard timeouts, retry once, deterministic error codes.

### Phase B (hardening)
1. OPA-style policy engine.
2. Artifact store + provenance.
3. Secret scrubber.
4. Cancellation and resume.

### Phase C (advanced)
1. Optional provider-native subagent fanout.
2. Adaptive routing (`auto` provider based on task type).
3. Budget-aware planner.

MCP hub skeleton:
```ts
import { z } from "zod";

const DispatchIn = z.object({
  provider: z.enum(["auto","codex","gemini","claude"]),
  task: z.string().min(1),
  mode: z.enum(["analyze","implement","review","test"]).default("analyze"),
  timeout_sec: z.number().int().min(10).max(3600).default(600),
  output_schema: z.any().optional()
});

server.tool("collab_dispatch", DispatchIn, async (input) => {
  policy.check(input);
  const run = await orchestrator.start(input);
  return { run_id: run.id, status: run.status, summary: run.summary };
});
```

Codex adapter:
```ts
const args = [
  "exec", "--json",
  "--ask-for-approval", "never",
  "--sandbox", "workspace-write",
  task
];
if (schemaPath) args.push("--output-schema", schemaPath, "-o", outputPath);
```

Gemini adapter:
```ts
const args = ["-p", task, "--output-format", stream ? "stream-json" : "json"];
```

Claude adapter (inference from your current prototype):
```ts
const wrapped = makeStrictJsonPrompt(task, schema);
const args = ["-p", wrapped]; // replace with your verified non-interactive flags
```

Client configs:

Claude:
```bash
claude mcp add collab --scope project -- node /opt/collab-hub/server.js
```

Codex (`~/.codex/config.toml`):
```toml
[mcp_servers.collab]
command = "node"
args = ["/opt/collab-hub/server.js"]
required = true
enabled_tools = ["collab_dispatch","collab_status","collab_fetch_artifact"]
tool_timeout_sec = 180
startup_timeout_sec = 20
```

Gemini (`~/.gemini/settings.json`):
```json
{
  "mcpServers": {
    "collab": {
      "command": "node",
      "args": ["/opt/collab-hub/server.js"],
      "timeout": 30000,
      "includeTools": ["collab_dispatch", "collab_status", "collab_fetch_artifact"]
    }
  }
}
```

## Sources
- OpenAI Codex CLI command options: https://developers.openai.com/codex/cli/reference
- OpenAI Codex non-interactive mode: https://developers.openai.com/codex/noninteractive
- OpenAI Codex config reference: https://developers.openai.com/codex/config-reference
- OpenAI Codex multi-agents: https://developers.openai.com/codex/multi-agent
- OpenAI Docs MCP page: https://platform.openai.com/docs/docs-mcp
- Gemini CLI headless mode: https://geminicli.com/docs/cli/headless/
- Gemini CLI cheatsheet: https://geminicli.com/docs/cli/cli-reference/
- Gemini CLI MCP servers: https://geminicli.com/docs/tools/mcp-server/
- Gemini CLI subagents: https://geminicli.com/docs/core/subagents/
- Gemini CLI remote subagents (A2A): https://geminicli.com/docs/core/remote-agents/
- Gemini CLI trusted folders: https://geminicli.com/docs/cli/trusted-folders/
- Gemini CLI settings: https://geminicli.com/docs/cli/settings/
- Claude Code MCP docs: https://docs.anthropic.com/en/docs/claude-code/mcp
- Claude Code subagents docs: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Community: https://github.com/kky42/codex-as-mcp
- Community: https://github.com/choplin/mcp-gemini-cli
- Community: https://github.com/centminmod/gemini-cli-mcp-server
- Community: https://github.com/ZainRizvi/gemini-cli-mcp
