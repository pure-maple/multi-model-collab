# Multi-Model Collab

跨平台多模型 AI 协作技能。通过统一的 MCP 接口，将任务分发给 **Codex CLI**、**Gemini CLI** 和 **Claude Code CLI**。

[English](../README.md) | 中文

## 为什么需要多模型协作？

不同 AI 模型各有所长：

| 模型 | 擅长领域 |
|------|---------|
| **Codex** (GPT) | 代码生成、算法实现、调试 |
| **Gemini** | 前端/UI、多模态、广泛知识 |
| **Claude** | 架构设计、深度推理、代码审查 |

本项目让任何 MCP 兼容平台都能跨三大模型编排任务——取各家之长。

## 架构

```
任意 MCP 客户端（Claude Code / Codex CLI / Gemini CLI / IDE）
    │
    └── collab-hub（统一 MCP 服务器）
        ├── collab_dispatch(provider, task, ...) → 标准化结果
        └── collab_check() → 可用性检查
            │
            ├── CodexAdapter  → codex exec --json
            ├── GeminiAdapter → gemini -p -o stream-json
            └── ClaudeAdapter → claude -p
```

**三级降级方案：**
1. **MCP 工具**（推荐）— 无需 Bash 权限，跨平台通用
2. **Bash 脚本** — 基于 tmux 的并行分发，需预配置权限
3. **纯提示分析** — 降级模式，单模型多视角分析

## 快速开始

### 前置条件

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) 包管理器
- 至少安装一个模型 CLI：
  - `codex` — `npm i -g @openai/codex`
  - `gemini` — `npm i -g @google/gemini-cli`
  - `claude` — [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

### 安装

```bash
git clone https://github.com/pure-maple/multi-model-collab.git
cd multi-model-collab

# 为 Claude Code 安装（一条命令）
./install.sh --claude

# 为所有平台安装
./install.sh --all

# 检查前置条件
./install.sh --check
```

### 手动安装

```bash
# Claude Code
claude mcp add collab-hub -s user -- uvx --from ./mcp/collab-hub collab-hub

# Codex CLI（添加到 ~/.codex/config.toml）
[mcp_servers.collab-hub]
command = "uvx"
args = ["--from", "/path/to/mcp/collab-hub", "collab-hub"]

# Gemini CLI（添加到 ~/.gemini/settings.json）
{"mcpServers": {"collab-hub": {"command": "uvx", "args": ["--from", "/path/to/mcp/collab-hub", "collab-hub"]}}}
```

## 使用方法

### 基础用法（从 Claude Code 或任何 MCP 客户端）

```python
# 检查可用模型
collab_check()

# 分发任务给 Codex
collab_dispatch(
    provider="codex",
    task="用 Python 实现一个二叉搜索树",
    workdir="/path/to/project",
    sandbox="read-only"
)

# 分发任务给 Gemini
collab_dispatch(
    provider="gemini",
    task="设计一个响应式仪表盘布局",
    workdir="/path/to/project"
)
```

### 智能路由

使用 `provider="auto"` 自动选择最合适的模型：

```python
# 自动路由：算法任务 → Codex，前端任务 → Gemini，架构任务 → Claude
collab_dispatch(
    provider="auto",
    task="实现一个 LRU 缓存",    # 自动路由到 Codex
    workdir="/path/to/project"
)
```

路由规则：
- **前端/UI/CSS/React/Vue** 关键词 → **Gemini**
- **算法/后端/API/调试/修复** 关键词 → **Codex**
- **架构/审查/安全/分析** 关键词 → **Claude**
- **无明确信号** → 默认 **Codex**（最通用）

### 指定模型版本

```python
# 指定 Codex 使用 gpt-5.4
collab_dispatch(provider="codex", model="gpt-5.4", task="...")

# 指定 Gemini 使用特定模型
collab_dispatch(provider="gemini", model="gemini-2.5-pro", task="...")

# 指定 Claude 使用特定模型
collab_dispatch(provider="claude", model="claude-sonnet-4-6", task="...")

# Codex 专属参数：配置文件 profile + 推理深度
collab_dispatch(
    provider="codex",
    profile="fast",
    reasoning_effort="xhigh",
    task="..."
)
```

> **注意**：各 CLI 的本地配置（如 Codex 的 `~/.codex/config.toml` 中的 `fast_mode`、`model_context_window`、`multi_agent` 等）会自动继承——hub 通过 subprocess 启动 CLI 进程，进程会正常读取自己的配置文件，无需在 hub 中重复配置。

### 多轮对话

通过 `session_id` 保持会话连续性：

```python
r1 = collab_dispatch(provider="codex", task="分析这个代码库")
# 继续同一会话
r2 = collab_dispatch(provider="codex", task="修复你发现的 bug",
                     session_id=r1.session_id)
```

### 工作流模式

**并行扇出** — 同时分发给多个模型：

```python
# 并行分发
result_codex = collab_dispatch(provider="codex", task="实现 API 端点")
result_gemini = collab_dispatch(provider="gemini", task="构建 React 组件")
# 综合两个结果
```

**顺序流水线** — 链式调用：

```python
code = collab_dispatch(provider="codex", task="实现二分搜索")
review = collab_dispatch(provider="gemini", task=f"审查这段代码:\n{code}")
```

**共识/双重审批** — 同一任务交给多个模型，对比结果：

```python
review_a = collab_dispatch(provider="codex", task=f"审查:\n{code}")
review_b = collab_dispatch(provider="gemini", task=f"审查:\n{code}")
# 对比并合并发现
```

### 作为 Agent Skill 使用

将 `SKILL.md` 复制到技能目录：

```bash
# Claude Code
mkdir -p ~/.claude/skills/multi-model-collab
cp SKILL.md ~/.claude/skills/multi-model-collab/SKILL.md

# Codex CLI
mkdir -p .agents/skills/multi-model-collab
cp SKILL.md .agents/skills/multi-model-collab/SKILL.md

# Gemini CLI
mkdir -p .gemini/skills/multi-model-collab
cp SKILL.md .gemini/skills/multi-model-collab/SKILL.md
```

## 输出格式

所有结果遵循统一的标准化格式：

```json
{
    "run_id": "a1b2c3d4",
    "provider": "codex",
    "status": "success",
    "summary": "前 200 字符...",
    "output": "完整模型响应",
    "session_id": "uuid-用于多轮对话",
    "duration_seconds": 12.5,
    "routed_from": "auto"
}
```

| 字段 | 说明 |
|------|------|
| `run_id` | 本次运行的唯一标识 |
| `provider` | 实际执行的模型（auto 路由后的） |
| `status` | `success` / `error` / `timeout` |
| `summary` | 输出前 200 字符摘要 |
| `output` | 完整的模型响应文本 |
| `session_id` | 会话 ID，传入下次调用可续接对话 |
| `duration_seconds` | 执行耗时（秒） |
| `routed_from` | 仅 `auto` 路由时出现，值为 `"auto"` |

## 项目结构

```
multi-model-collab/
├── README.md                       # 英文文档
├── docs/README_CN.md               # 中文文档（本文件）
├── SKILL.md                        # Agent Skill 定义（MCP 优先 + 三级降级）
├── install.sh                      # 一键安装脚本
├── mcp/collab-hub/                 # 统一 MCP 服务器
│   ├── pyproject.toml              # Python 包配置
│   ├── README.md
│   └── src/collab_hub/
│       ├── server.py               # MCP 工具：collab_dispatch, collab_check
│       ├── cli.py                  # 入口
│       └── adapters/               # 模型适配器
│           ├── base.py             # 线程化子进程管理 + 标准化输出
│           ├── codex.py            # JSONL 解析 + thread_id 会话
│           ├── gemini.py           # stream-json 解析 + session_id
│           └── claude.py           # 纯文本解析
├── mcp/collab-hub/tests/
│   └── test_e2e.py                 # 端到端测试（5 项全通过）
├── scripts/                        # 降级方案：基于 tmux 的 shell 脚本
│   ├── session.sh                  # tmux 会话管理
│   ├── dispatch.sh                 # 任务分发
│   ├── collect.sh                  # 结果收集
│   └── adapters/                   # shell 适配器
├── evals/evals.json                # 评估场景
└── references/                     # 架构文档
    ├── consultation/               # 三模型架构咨询记录
    ├── cross-platform.md           # 跨平台配置指南
    ├── adding-models.md            # 添加新模型指南
    └── workflow-examples.md        # 工作流示例
```

## CLI 配置继承

各 CLI 的本地配置在 hub 中**自动生效**，因为 hub 通过 `subprocess` 启动 CLI 进程，进程会正常读取自己的配置文件：

### Codex（`~/.codex/config.toml`）

```toml
model = "gpt-5.4"
model_context_window = 1000000
model_auto_compact_token_limit = 900000

[features]
multi_agent = true
fast_mode = true
```

以上配置在通过 `collab_dispatch(provider="codex", ...)` 调用时全部自动继承，无需额外设置。

### Gemini（`~/.gemini/settings.json`）

```json
{
  "model": "gemini-2.5-pro",
  "themeMode": "dark"
}
```

### Claude（`~/.claude/settings.json`）

```json
{
  "model": "claude-sonnet-4-6",
  "permissions": { ... }
}
```

## 设计决策

本架构通过三个 AI 模型联合咨询设计：
- **Claude Opus 4.6** — 提出原始方案并综合各方意见
- **GPT-5.3-Codex** — 建议统一 Hub 取代分散 Bridge、OPA 策略引擎、`--output-schema` 利用
- **Gemini-3.1-Pro-Preview** — 建议 A2A 协议骨干、Conductor 共享状态、动态工具暴露

核心共识：
1. **统一 MCP Hub** 取代 3 个独立 Bridge 服务器
2. **MCP 优先** 绕过子 agent 的 Bash 权限问题
3. **标准化输出格式** 统一跨模型结果
4. **会话连续性** 通过各 CLI 原生 session ID
5. **代码主权** — 外部模型输出仅为原型，需审查后再应用

完整咨询记录见 `references/consultation/`。

## 致谢

灵感来源与参考：
- [GuDaStudio/codexmcp](https://github.com/GuDaStudio/codexmcp) — Codex MCP 桥接模式
- [GuDaStudio/geminimcp](https://github.com/GuDaStudio/geminimcp) — Gemini MCP 桥接模式
- [GuDaStudio/skills](https://github.com/GuDaStudio/skills) — Agent Skills 结构
- [GuDaStudio/commands](https://github.com/GuDaStudio/commands) — RPI 工作流理论

## 许可证

MIT
