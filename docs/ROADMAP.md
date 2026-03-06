# modelmux 功能规划

## 当前状态 (v0.12.0)

### MCP 工具
| 工具 | 功能 |
|------|------|
| mux_dispatch | 单模型分发（智能路由、failover、会话连续性） |
| mux_broadcast | 多模型并行分发（共识/对比） |
| mux_history | 历史查询与分析 |
| mux_check | 可用性检查与状态概览 |

### CLI 命令
`modelmux` / `init` / `config` / `check` / `status` / `history` / `version`

### Provider 适配器
codex / gemini / claude / ollama

### 基础设施
审计日志 / 策略引擎 / Profile 系统 / 实时状态追踪 / TUI 配置面板

---

## 近期规划

### P0: 工作流模板
预定义多步编排模式，配置在 workflow 文件中。

**用例：**
- 代码审查流水线：codex 实现 → claude 审查 → gemini 测试 UI
- 共识决策：broadcast 给多个模型 → 自动汇总差异
- 扇出合并：拆分任务 → 并行分发 → 合并结果

**实现思路：**
```toml
[workflows.code-review]
description = "代码审查流水线"

[[workflows.code-review.steps]]
provider = "codex"
task_template = "实现: {task}"
output_var = "code"

[[workflows.code-review.steps]]
provider = "claude"
task_template = "审查以下代码:\n{code}"
output_var = "review"
```

### P0: 结果对比/Diff
- broadcast 结果的结构化差异分析
- 高亮各模型的共识与分歧
- 可用于自动化决策

### P1: 流式输出
- 分发过程中实时返回部分输出
- MCP streaming + status 文件双通道
- 改善长任务用户体验

### P1: PTY 交互模式（调研中）
- 研究 PTY vs subprocess pipe 的差异
- OpenClaw 使用 PTY 获取更丰富的输出
- 评估对 modelmux 的价值和实现成本

---

## 中期规划

### P2: 自定义 Provider 插件
- 用户注册自定义适配器（任意 CLI/API）
- 插件发现机制（entry_points 或配置文件）
- 不局限于内置的 4 个 provider

### P2: 智能路由 v2
- 基于历史成功率、延迟数据优化路由
- 学习用户使用模式
- 替代纯关键词匹配

### P2: 成本估算
- 按 provider 追踪 token 用量
- 费用估算
- `modelmux history --costs` 查看

### P3: 任务拆解
- 复杂任务自动拆分为子任务
- 分发给最适合的模型分别处理
- 结果自动合并

---

## 长期规划

### Web Dashboard (modelmux-dashboard)
独立包，路线 B 方案：
- FastAPI 后端 + 轻量前端（htmx 或 React）
- 实时监控面板：活跃分发、历史图表、provider 健康
- 可视化工作流编辑器
- `modelmux dashboard` 启动本地 Web 服务

后期可考虑路线 C（Tauri 桌面应用），产品成熟后再评估。

### 生态集成
- Webhook 通知（Slack/Discord/邮件）
- VS Code 扩展
- 基准测试套件
- 导出/报告功能

---

## 技术调研

### 开发框架
评估 bmad-method、superpowers 等是否适用于规范化开发流程。

### PTY 交互
评估 pty/pexpect 替代 subprocess pipe 的可行性和收益。

---

*最后更新: 2026-03-06*
