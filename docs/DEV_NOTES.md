# 开发笔记

内部参考文档，记录技术决策、踩坑经验和设计思考。

## 技术选型

### 为什么选 Python 而非 TypeScript
- FastMCP 框架成熟度高，`@mcp.tool()` 装饰器开发体验好
- `uvx` 零配置分发（`uvx modelmux` 一条命令安装运行）
- Python subprocess 编排能力强
- TypeScript MCP SDK 需要更多样板代码

### 为什么用 subprocess 而非 API
- 各 CLI 的 API key 和配置由用户自己管理
- CLI 自动读取本地配置文件（Codex 的 config.toml、Gemini 的 settings.json 等）
- 无需在 modelmux 中重复配置认证信息
- 代码主权：外部模型输出通过 CLI 沙箱隔离

## 已知问题

### .venv shebang 失效
Google Drive 路径包含中文字符，如果父目录重命名会导致 .venv 中的 shebang 路径失效。
**解决**: `rm -rf .venv && uv sync`

### e2e 测试需要 pytest-asyncio
`test_e2e.py` 中的异步测试需要 `pytest-asyncio` 和实际 CLI 环境，CI 中跳过。
单元测试（41 项）覆盖核心逻辑。

### Ruff 格式化
提交前务必运行 `ruff check --fix src/ && ruff format src/`，CI 会检查。

## 设计思考

### 进度监控的两种模式
用户提出的概念：
1. **可视化模式** — 类似 Claude Code Team Mode 的 tmux 分屏，实时看到每个 provider 的输出
2. **静默模式** — 类似 subagent 黑盒，用户不关注细节，只要最终结果

目前 v0.9.0 的 status tracking 是可视化模式的基础设施。
静默模式是现有的默认行为（MCP tool 调用返回最终结果）。

### Claude Code Team Mode 参考
研究发现 Team Mode 的关键模式：
- 文件系统协调（`~/.claude/tasks/`）— modelmux 的 status/ 目录类似
- Peer-to-peer 通信 — 未来 workflow 模板可参考
- worktree 隔离 — 各 provider 已天然隔离（独立 subprocess）

### 广播 vs 分发
- `mux_dispatch`: 单点任务，带 failover 和 session
- `mux_broadcast`: 多点任务，并行执行，无 failover（每个 provider 独立）
- 广播不支持 session_id（各 provider 的 session 不互通）

## 发布流程

1. 更新版本号: `__init__.py` + `pyproject.toml` + `server.json`
2. `git commit` → `git push`
3. `git tag vX.Y.Z` → `git push origin vX.Y.Z`
4. GitHub Actions 自动构建并发布到 PyPI（Trusted Publisher）
5. MCP Registry 自动同步（需要 `mcp-name:` tag 在 README 中）

*最后更新: 2026-03-06*
