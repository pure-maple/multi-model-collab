# modelmux

[English](../README.md) | 中文

跨平台多模型 AI 协作服务器。通过统一的 MCP 接口，将任务分发、广播、编排到 **Codex CLI**、**Gemini CLI**、**Claude Code CLI**、**Ollama** 和外部 **A2A Agent** —— 内置智能路由、自动容错、成本追踪和多 Agent 协作。

[![PyPI](https://img.shields.io/pypi/v/modelmux)](https://pypi.org/project/modelmux/)

## 为什么需要多模型协作？

不同 AI 模型各有所长：

| 模型 | 擅长领域 |
|------|---------|
| **Codex** (GPT) | 代码生成、算法实现、调试 |
| **Gemini** | 前端/UI、多模态、广泛知识 |
| **Claude** | 架构设计、深度推理、代码审查 |
| **Ollama** | 免费本地推理（DeepSeek、Llama、Qwen 等） |

modelmux 让任何 MCP 兼容平台都能跨模型编排任务——取各家之长，配合自动容错、成本追踪和真正的多 Agent 协作。

## 架构

```
MCP 客户端（Claude Code / Codex CLI / Gemini CLI / IDE）
    │
    └── modelmux（MCP 服务器，stdio）
        ├── mux_dispatch     → 单 provider 分发（智能路由、自动容错）
        ├── mux_broadcast    → 并行多 provider + 对比分析
        ├── mux_collaborate  → 迭代式多 Agent 协作（A2A 协议）
        ├── mux_workflow     → 多步骤流水线
        ├── mux_history      → 历史分析、成本追踪
        └── mux_check        → 可用性与配置状态
            │
            ├── CodexAdapter      → codex exec --json
            ├── GeminiAdapter     → gemini -p -o stream-json
            ├── ClaudeAdapter     → claude -p
            ├── OllamaAdapter     → ollama run <model>
            ├── A2ARemoteAdapter  → 外部 A2A Agent（httpx）
            └── 自定义适配器       → 用户插件

A2A HTTP 服务器（modelmux a2a-server）
    ├── GET  /.well-known/agent.json   → Agent Card
    ├── POST /（JSON-RPC 2.0）
    │   ├── tasks/send                 → 同步任务
    │   ├── tasks/get                  → 查询任务状态
    │   ├── tasks/cancel               → 取消运行中任务
    │   └── tasks/sendSubscribe        → SSE 流式传输
    └── TaskStore（内存 + JSONL 持久化）
```

## 快速开始

### 前置条件

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) 包管理器
- 至少安装一个模型 CLI：
  - `codex` — `npm i -g @openai/codex`
  - `gemini` — `npm i -g @google/gemini-cli`
  - `claude` — [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  - `ollama` — [Ollama](https://ollama.com)

### 安装

```bash
# 推荐：为 Claude Code 安装为 MCP 服务器
claude mcp add modelmux -s user -- uvx modelmux

# 或为所有平台安装
git clone https://github.com/pure-maple/modelmux.git
cd modelmux && ./install.sh --all

# 检查可用性
modelmux check
```

<details>
<summary>其他平台手动安装</summary>

```bash
# Codex CLI（~/.codex/config.toml）
[mcp_servers.modelmux]
command = "uvx"
args = ["modelmux"]

# Gemini CLI（~/.gemini/settings.json）
{"mcpServers": {"modelmux": {"command": "uvx", "args": ["modelmux"]}}}
```

</details>

## 使用方法

### 分发 — 单 provider

```python
# 智能路由（自动排除调用方，根据任务选择最佳模型）
mux_dispatch(provider="auto", task="实现一个二叉搜索树")

# 指定 provider
mux_dispatch(provider="codex", task="修复 pool.py 中的内存泄漏",
             workdir="/path/to/project", sandbox="write")

# 指定模型 + 多轮对话
r1 = mux_dispatch(provider="codex", model="gpt-5.4", task="分析这个代码库")
r2 = mux_dispatch(provider="codex", task="修复你发现的 bug",
                   session_id=r1.session_id)

# 本地模型（Ollama）
mux_dispatch(provider="ollama", model="deepseek-r1", task="解释这个算法")
```

### 广播 — 并行多 provider

```python
# 同时发送到所有可用 provider
mux_broadcast(task="审查这个 API 设计的安全问题")

# 指定 provider 并启用结构化对比
mux_broadcast(
    task="推荐最佳数据结构",
    providers=["codex", "gemini", "claude"],
    compare=True  # 添加相似度评分、速度排名
)
```

### 协作 — 多 Agent 迭代（A2A）

```python
# 审查循环：实现 → 审查 → 修改，直到通过
mux_collaborate(
    task="实现一个滑动窗口限流器",
    pattern="review"  # codex 实现，claude 审查，迭代
)

# 共识：并行分析 + 综合
mux_collaborate(task="评估我们的迁移策略", pattern="consensus")

# 辩论：正方 vs 反方 + 仲裁裁决
mux_collaborate(task="是否应该使用微服务？", pattern="debate")
```

### 工作流 — 多步骤流水线

```python
# 列出可用工作流
mux_workflow(workflow="", task="", list_workflows=True)

# 执行内置或自定义工作流
mux_workflow(workflow="review", task="优化数据库查询")
```

### 历史与成本追踪

```python
# 最近分发记录
mux_history(limit=20)

# 统计 + 成本分析
mux_history(stats_only=True, costs=True)

# 按 provider 和时间范围过滤
mux_history(provider="codex", hours=24, costs=True)
```

Token 用量会自动从 Codex 和 Gemini 的响应中提取。成本估算使用可配置的模型定价表。

### 检查 — 可用性与配置

```python
mux_check()
# 返回：provider 可用性、调用方检测、当前 profile、
#       策略摘要、审计统计、活跃分发任务
```

## A2A HTTP 服务器

将 modelmux 作为 [A2A 协议](https://google.github.io/A2A/) Agent 通过 HTTP 暴露：

```bash
# 默认启动
modelmux a2a-server

# 自定义端口 + 认证
modelmux a2a-server --port 8080 --token my-secret --sandbox write
```

其他 A2A 兼容 Agent 可以通过以下接口交互：
- `GET /.well-known/agent.json` — Agent Card（能力、技能声明）
- `POST /` — JSON-RPC 2.0（`tasks/send`、`tasks/get`、`tasks/cancel`、`tasks/sendSubscribe`）

### 连接外部 A2A Agent

在配置中注册外部 Agent，即可像其他 provider 一样使用：

```toml
# ~/.config/modelmux/profiles.toml
[a2a_agents.my-agent]
url = "http://localhost:8080"
token = "secret"
pattern = "code-review"
```

```python
mux_dispatch(provider="my-agent", task="审查这个 PR")
```

## CLI 命令

```bash
modelmux              # 启动 MCP 服务器（stdio）
modelmux a2a-server   # 启动 A2A HTTP 服务器
modelmux dashboard    # Web 监控面板（http://127.0.0.1:41521）
modelmux benchmark    # 运行 provider 基准测试
modelmux init         # 交互式配置向导
modelmux config       # TUI 配置面板（需要 modelmux[tui]）
modelmux check        # 检查 CLI 可用性
modelmux status       # 监控活跃分发任务
modelmux status -w    # 实时刷新模式（每秒更新）
modelmux history      # 查看最近分发记录
modelmux history --stats --costs   # 统计 + 成本分析
modelmux export --format csv       # 导出历史为 CSV/JSON/Markdown
modelmux version      # 显示版本
```

## 配置

创建 `.modelmux/profiles.toml`（项目级）或 `~/.config/modelmux/profiles.toml`（用户级）：

```toml
# 自定义路由规则
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

# 调用方检测
caller_override = ""
auto_exclude_caller = true

# 命名 profile
[profiles.budget]
description = "使用更便宜的模型"
[profiles.budget.providers.codex]
model = "gpt-4.1-mini"
[profiles.budget.providers.gemini]
model = "gemini-2.5-flash"
```

### 策略引擎

创建 `~/.config/modelmux/policy.json`：

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

## 输出格式

所有结果遵循标准化格式：

```json
{
    "run_id": "a1b2c3d4",
    "provider": "codex",
    "status": "success",
    "summary": "前 200 字符摘要...",
    "output": "完整模型响应",
    "session_id": "uuid-用于多轮对话",
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

`token_usage` 在 provider 返回 token 数据时包含（Codex、Gemini）。成本估算通过 `mux_history(costs=True)` 查看。

## 功能一览

| 功能 | 说明 |
|------|------|
| **智能路由** | 根据任务关键词 + 历史评分自动选择最佳模型，自动排除调用方 |
| **自动容错** | provider 失败时自动切换到下一个可用 provider |
| **配置 Profile** | 命名配置（budget、china 等），支持模型/API 覆盖 |
| **多轮对话** | 通过各 CLI 原生 session ID 保持会话连续性 |
| **广播** | 并行分发到多个 provider，支持结构化对比 |
| **多 Agent 协作** | 迭代式协作模式（review、consensus、debate） |
| **工作流** | 多步骤流水线，支持变量替换 |
| **成本追踪** | Token 用量提取 + 按模型定价估算 |
| **A2A 协议** | HTTP 服务器 + 客户端，支持 Agent 间互操作 |
| **策略引擎** | 速率限制、provider/沙箱封禁 |
| **审计日志** | 每次分发的完整 JSONL 审计轨迹 |
| **实时监控** | 通过 CLI 或状态文件实时查看分发进度 |
| **自定义插件** | 通过配置添加自定义适配器 |

## 设计决策

架构通过三个 AI 模型联合咨询设计：
- **Claude Opus 4.6** — 原始方案与综合
- **GPT-5.3-Codex** — 建议统一 Hub、OPA 策略引擎
- **Gemini-3.1-Pro-Preview** — 建议 A2A 协议骨干

核心共识：统一 MCP Hub（非 3 个独立 Bridge）、MCP 优先（无需 Bash 权限）、标准化输出格式、会话连续性、代码主权。

详见 `references/consultation/`。

## 许可证

MIT
