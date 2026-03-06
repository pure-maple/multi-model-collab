# modelmux

Model multiplexer — unified MCP server for cross-platform multi-model AI collaboration.

## Cross-Agent Collaboration

本项目与 clawmux 通过共享文档协调：

- **`../shared/modelmux-clawmux.md`** — 接口约定、状态同步、联动优先级
- **`../shared/modelmux-a2a-integration-guide.md`** — A2A 集成指南（面向 clawmux）

**重要**: 接口变更时同步更新 `../shared/modelmux-clawmux.md`。

## Quick Reference

- **Package**: `mcp/modelmux/` (pyproject.toml, src/modelmux/)
- **Install**: `uvx modelmux` or `claude mcp add modelmux -s user -- uvx modelmux`
- **Python**: Use `uv`, not system python. Requires 3.10+
- **Tests**: `cd mcp/modelmux && uv run --with pytest --with pytest-asyncio python -m pytest tests/ --ignore=tests/test_e2e.py`
- **Lint**: `uv run ruff check src/ && uv run ruff format src/`
- **Build**: `uv build`
- **CI**: GitHub Actions (matrix 3.10-3.12 x ubuntu/macos), auto-publish on tag

## Architecture

```
MCP Client → modelmux (FastMCP server, stdio)
  ├── mux_dispatch     → single provider dispatch (auto-route, failover, auto_decompose)
  ├── mux_broadcast    → parallel multi-provider dispatch (provider/model syntax)
  ├── mux_collaborate  → A2A iterative multi-agent collaboration
  ├── mux_workflow     → multi-step pipeline orchestration
  ├── mux_history      → query result history & analytics (costs)
  └── mux_check        → availability & config status
      │
      ├── CodexAdapter     → codex exec --json
      ├── GeminiAdapter    → gemini -p -o stream-json
      ├── ClaudeAdapter    → claude -p
      ├── OllamaAdapter    → ollama run <model>
      ├── DashScopeAdapter → OpenAI-compatible API (coding.dashscope.aliyuncs.com)
      └── A2ARemoteAdapter → external A2A agents (via httpx)

A2A HTTP Server (modelmux a2a-server)
  ├── GET  /.well-known/agent.json  → Agent Card
  ├── POST / (JSON-RPC 2.0)
  │   ├── tasks/send          → synchronous (+ push notification)
  │   ├── tasks/get           → query task state
  │   ├── tasks/cancel        → cancel running task
  │   └── tasks/sendSubscribe → SSE streaming (+ push notification)
  └── TaskStore (in-memory + JSONL persistence)

Web Dashboard (modelmux dashboard --port 41521)
  ├── GET  /                → monitoring UI (auto-refresh)
  ├── GET  /api/status      → active dispatches
  ├── GET  /api/history     → dispatch history
  ├── GET  /api/stats       → aggregated statistics
  ├── GET  /api/providers   → provider availability
  └── GET  /api/costs       → cost breakdown
```

## Key Files

| File | Purpose |
|------|---------|
| `server.py` | MCP tools (dispatch, broadcast, collaborate, history, check) |
| `adapters/base.py` | Threaded subprocess runner, canonical result schema |
| `adapters/{codex,gemini,claude,ollama,dashscope}.py` | Provider-specific adapters |
| `a2a/` | A2A protocol implementation |
| `a2a/types.py` | Data model (Task, Message, Artifact, AgentCard) |
| `a2a/context.py` | Layered memory (pinned facts + rolling summary + recent window) |
| `a2a/convergence.py` | 4-tier convergence detection |
| `a2a/patterns.py` | Collaboration patterns (review, consensus, debate) |
| `a2a/engine.py` | Multi-agent collaboration orchestrator |
| `a2a/http_server.py` | A2A HTTP transport (JSON-RPC 2.0 + SSE) |
| `a2a/client.py` | A2A client for connecting to external agents |
| `adapters/a2a_remote.py` | Remote A2A agent as standard adapter |
| `routing.py` | Smart routing v2 (keyword + history scoring) |
| `config.py` | Profile loading, routing rules |
| `detect.py` | Caller platform detection |
| `audit.py` | JSONL audit log (policy rate-limiting) |
| `history.py` | Full result storage (history.jsonl) |
| `policy.py` | Policy engine (rate limits, blocks) |
| `status.py` | Real-time dispatch status tracking |
| `tui.py` | Textual TUI config panel |
| `init_wizard.py` | Interactive setup wizard |
| `decompose.py` | Task decomposition (DAG planner + wave executor + merger) |
| `costs.py` | Token usage pricing and cost estimation |
| `notifications.py` | Webhook notifications (Slack/Discord/generic) |
| `dashboard.py` | Web dashboard (Starlette REST API + HTML UI) |
| `benchmark.py` | Provider benchmark suite (standardized tasks + scoring) |
| `export.py` | Export history to CSV/JSON/Markdown reports |
| `cli.py` | CLI entry point with subcommands |

## Dev Workflow

1. Edit `src/modelmux/` files
2. `uv sync` (if deps changed)
3. Run tests + lint
4. Commit → push → tag `vX.Y.Z` → auto-publish to PyPI

## Conventions

- Adapters inherit `BaseAdapter`, implement `build_command()` and `parse_output()`
- All dispatch results use `AdapterResult` canonical schema
- Config files: `~/.config/modelmux/` (user) or `.modelmux/` (project)
- Status files: `~/.config/modelmux/status/{run_id}.json`
- Chinese for internal docs, bilingual for public docs

## Multi-Model Collaboration Protocol

**复杂决策和架构设计必须与 GPT 和 Gemini 共同讨论**。具体要求：

- **何时协作**: 涉及架构设计、协议选型、关键算法决策、竞品调研等复杂问题时，
  必须通过 `mux_broadcast` 或 `mux_collaborate` 与其他模型共同讨论
- **推荐配置**:
  - GPT (Codex): `provider="codex"`, model="gpt-5.4", reasoning_effort="xhigh"
  - Gemini: `provider="gemini"`, model="gemini-3.1-pro-preview"
- **超时设置**: 深度研究任务超时可设为数小时甚至一天，不做严格限制
- **代码审查**: 关键功能的代码审查可委托给 codex 和 gemini 共同完成

### 后台并行执行（推荐）

使用 Bash 工具的 `run_in_background` 参数可以让 codex/gemini 在后台执行，不阻塞 Claude Code 主线程。
这是提升多模型协作效率的关键手段。

**模式**: 发起后台任务 → 继续主线工作 → 后台完成时收到通知 → 读取结果

```bash
# 后台发起 Codex 代码审查（run_in_background=true）
codex exec --json -- "Review this code for security issues: $(cat src/file.py)" \
  > /tmp/codex-review.log 2>&1

# 后台发起 Gemini 架构分析（run_in_background=true）
gemini -p "Analyze the architecture of: $(cat CLAUDE.md)" \
  > /tmp/gemini-analysis.log 2>&1
```

**适用场景**:
- 代码审查：发起 codex/gemini 后台审查，自己继续编码
- 调研任务：后台让多个模型并行调研不同方面
- 测试验证：后台跑长时间测试，同时处理其他任务
- 多模型对比：同时发起多个后台任务，汇总结果做决策

**注意事项**:
- 使用 `run_in_background=true` 参数而非 `&` 后缀，Claude Code 会在完成时通知
- 输出重定向到 `/tmp/` 下的日志文件以便后续读取
- 确保代码已保存到磁盘再发起审查（后台进程读取的是磁盘文件）
- 后台任务不要依赖当前 session 的环境变量或状态

## Documentation & Knowledge Management

**关键里程碑和调研成果必须持久化为文档**：

- **CHANGELOG**: 每个版本发布时更新 `docs/CHANGELOG.md`
- **调研文档**: 有价值的调研结果保存到 `docs/research/` 目录，作为 AI 知识资产持续沉淀
- **架构决策**: 重大架构决策记录到 `docs/decisions/` 目录 (ADR 格式)
- **里程碑**: 关键功能完成时更新 CLAUDE.md 架构图和文件表

See `docs/ROADMAP.md` for feature planning, `docs/CHANGELOG.md` for version history.
