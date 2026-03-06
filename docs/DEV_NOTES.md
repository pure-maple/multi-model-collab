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

## 调研结论

### PTY vs Subprocess Pipe

**现状**: modelmux 使用 `subprocess.Popen` + pipe 与各 CLI 交互。

**PTY 的优势**:
- **实时输出**: pipe 模式下输出是 block-buffered，PTY 强制 line-buffered，输出即时可见
- **程序行为差异**: 很多 CLI 在非终端环境下行为不同（无颜色、无进度条、不触发交互式提示）
- **ANSI 保留**: PTY 保留完整的终端格式化（颜色、粗体等）

**PTY 的劣势**:
- stdout/stderr 合并（PTY 无法分离），对错误解析有影响
- 仅 Unix/macOS 原生支持，Windows 需要 ConPTY
- 实现复杂度更高，调试更困难

**结论**: PTY 对**流式输出**（Task #33）有明确价值。当前 subprocess pipe 对基本功能足够，但当实现流式输出功能时，应考虑用 `pty` 或 `pexpect` 替换 `subprocess.PIPE`，以获得实时 line-buffered 输出。可以做成适配器层的可选模式，不破坏现有兼容性。

**行动**: 暂不改动核心适配器，在 Task #33（流式输出）中评估引入 PTY。

### 开发框架评估

**BMAD-METHOD** (bmad-code-org/BMAD-METHOD):
- 全称: Breakthrough Method for Agile AI Driven Development
- 19 个专业 AI agent + 50+ 工作流，覆盖分析→规划→架构→实现全生命周期
- v6 架构: Core（协作引擎）+ Method（开发方法）+ Builder（自定义模块）
- MIT 开源，支持 Claude Code / Cursor / Windsurf
- **评估**: 非常全面但偏重型。适合大型团队项目。modelmux 当前体量不需要引入完整框架，但其中的"story-driven development"和"scale-adaptive intelligence"理念可以借鉴。

**Superpowers** (obra/superpowers):
- 42K+ GitHub stars，已入 Anthropic 官方插件市场
- 核心价值: Socratic 头脑风暴 → 详细规划 → TDD → 子 agent 并行开发 → 代码审查
- 安装: `/plugin marketplace add obra/superpowers-marketplace`
- 实用命令: `/brainstorm`, `/write-plan`, `/execute-plan`
- **评估**: 更轻量实用，适合个人开发者。可以直接作为 Claude Code 插件使用来辅助 modelmux 的开发，但不需要集成到项目代码中。

**结论**: 这两个框架都是**开发过程工具**，不需要集成到 modelmux 产品代码中。推荐用户安装 Superpowers 插件来辅助日常开发。BMAD 的结构化规划思路可在大功能（如 Dashboard）开发时参考。modelmux 自身已有 CLAUDE.md + ROADMAP + CHANGELOG 的文档体系，当前阶段够用。

*最后更新: 2026-03-06*
