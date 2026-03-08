# mux_orchestrate 架构规范

> 设计者: Reef | 日期: 2026-03-07
> 状态: Draft — 待拆解为可分配的开发任务

## 一、定位

mux_orchestrate 是 modelmux 的顶层编排工具，管理 agent 生命周期和任务流水线。
它是 modelmux 从"模型调度器"升级为"agent 协作平台"的关键模块。

**灵感来源**:
- superpowers: Plan → Execute → Review 三阶段 + parallel agent dispatch
- BMAD: Agent Persona 角色 + 完整生命周期
- oh-my-opencode: Background agents + multi-model 编排

**与现有工具的关系**:
```
mux_orchestrate (NEW — 编排层)
  ├── mux_dispatch     (执行层 — 单次调度)
  ├── mux_broadcast    (执行层 — 并行调度)
  ├── mux_collaborate  (协作层 — 多轮迭代)
  └── mux_workflow     (流程层 — 多步流水线)
```

## 二、核心概念

### Agent Role（角色模板）

预定义角色，每个角色绑定推荐模型和适合的任务类型：

```python
ROLES = {
    "implementer": {
        "description": "功能实现、代码生成",
        "recommended_models": ["codex", "qwen3-coder-plus"],
        "skills": ["coding", "testing", "refactoring"],
    },
    "reviewer": {
        "description": "代码审查、Bug 发现",
        "recommended_models": ["dashscope/kimi-k2.5", "dashscope/MiniMax-M2.5"],
        "skills": ["review", "security-audit", "architecture-analysis"],
    },
    "writer": {
        "description": "文档、Release Notes、技术写作",
        "recommended_models": ["dashscope/qwen3.5-plus", "claude"],
        "skills": ["documentation", "translation", "technical-writing"],
    },
    "planner": {
        "description": "需求分解、任务拆解",
        "recommended_models": ["claude", "gemini"],
        "skills": ["decomposition", "architecture", "planning"],
    },
    "debugger": {
        "description": "问题诊断、根因分析",
        "recommended_models": ["claude", "dashscope/kimi-k2.5"],
        "skills": ["debugging", "root-cause-analysis", "profiling"],
    },
}
```

### Task Pipeline（任务流水线）

一个完整的任务经过以下阶段：

```
PLAN → IMPLEMENT → REVIEW → INTEGRATE
  │       │           │         │
  │       │           │         └── 合并到目标分支
  │       │           └── 自动审查（CodeRabbit + DashScope 交叉）
  │       └── 子 agent 执行（Codex/Sonnet/DashScope）
  └── Reef/Planner 分解需求为可执行 spec
```

### PR Review Pipeline

```python
async def auto_review(branch: str) -> ReviewResult:
    """三层自动审查 + 人工最终决策"""

    # Layer 1: 测试验证
    test_result = await run_tests(branch)
    if not test_result.passed:
        return ReviewResult(status="rejected", reason="tests failed")

    # Layer 2: DashScope 交叉审查（免费）
    reviews = await mux_broadcast(
        providers=["dashscope/kimi-k2.5", "dashscope/MiniMax-M2.5"],
        task=f"审查以下代码变更: {get_diff(branch)}",
        compare=True,
    )

    # Layer 3: 生成人类可读摘要（国产模型）
    summary = await mux_dispatch(
        provider="dashscope",
        model="qwen3.5-plus",
        task=f"用中文总结以下代码审查结果: {reviews}",
    )

    return ReviewResult(
        status="pending_approval",
        test_result=test_result,
        reviews=reviews,
        summary=summary,
    )
```

## 三、MCP Tool 接口设计

```python
@mcp.tool()
async def mux_orchestrate(
    action: str,           # "plan" | "assign" | "status" | "review" | "merge"
    task: str = "",        # 任务描述（plan 时使用）
    role: str = "",        # 角色模板（assign 时使用）
    branch: str = "",      # 分支名（review/merge 时使用）
    agent: str = "",       # agent 名称
) -> str:
    """Agent 编排工具 — 管理任务生命周期"""
```

### 操作示例

```
# 分解需求为可执行任务
mux_orchestrate action=plan task="将 server.py 测试覆盖率从 76% 提升到 90%"

# 分配给合适的 agent
mux_orchestrate action=assign task_id=T001 role=implementer agent=codex

# 查看当前状态
mux_orchestrate action=status

# 审查某个分支
mux_orchestrate action=review branch=codex1/server-tests

# 合并审查通过的分支
mux_orchestrate action=merge branch=codex1/server-tests
```

## 四、实现分阶段

### Phase 1: 基础框架（可分配给 Codex）

- [ ] `src/modelmux/orchestrate.py` — 角色定义 + 任务状态机
- [ ] `src/modelmux/orchestrate_store.py` — 任务持久化（JSONL）
- [ ] server.py 注册 mux_orchestrate tool
- [ ] 基础测试

### Phase 2: PR Review Pipeline（可分配给 Codex）

- [ ] `src/modelmux/review.py` — 三层自动审查
- [ ] 与 `mux_broadcast` 集成
- [ ] 审查结果摘要生成（DashScope qwen3.5-plus）
- [ ] CLI: `modelmux review <branch>`

### Phase 3: 知识沉淀（后续设计）

- [ ] 每次审查的结论自动归档
- [ ] Bug 模式提取和积累
- [ ] 架构决策记录

## 五、与 Meridian 的关系

mux_orchestrate 是 Meridian 知识资产层的入口：
- 每次任务执行产生结构化记录
- 审查结论、bug 模式、架构决策自动沉淀
- 为后续 RAG/向量索引提供高质量数据源
