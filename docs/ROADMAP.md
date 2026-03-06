# modelmux 功能规划

## 当前状态 (v0.23.0)

### MCP 工具
| 工具 | 功能 |
|------|------|
| mux_dispatch | 单模型分发（智能路由 v2、failover、会话连续性、自动任务拆解） |
| mux_broadcast | 多模型并行分发（共识/对比、Provider/Model 语法） |
| mux_collaborate | A2A 迭代多 agent 协作（review/consensus/debate） |
| mux_workflow | 多步流水线编排 |
| mux_history | 历史查询与分析（含成本统计） |
| mux_check | 可用性检查与状态概览 |

### A2A HTTP Server
| 端点 | 功能 |
|------|------|
| GET /.well-known/agent.json | Agent Card 能力发现 |
| POST / (tasks/send) | 同步任务执行（支持 Push Notification） |
| POST / (tasks/get) | 查询任务状态 |
| POST / (tasks/cancel) | 取消运行中任务 |
| POST / (tasks/sendSubscribe) | SSE 流式推送（支持 Push Notification） |

### CLI 命令
`modelmux` / `a2a-server` / `init` / `config` / `check` / `status` / `history` / `version`

### Provider 适配器
codex / gemini / claude / ollama / dashscope / 自定义插件

### 基础设施
审计日志 / 策略引擎 / Profile 系统 / 实时状态追踪 / TUI 配置面板 / 流式输出 / 智能路由 v2 / 成本追踪

---

## 已完成 (v0.1.0 → v0.22.0)

- [x] 初始原型：三大 CLI 适配器
- [x] 审计日志 + 策略引擎
- [x] 调用方平台检测与自动排除
- [x] Profile 系统
- [x] 执行容错 (Failover)
- [x] Ollama 适配器
- [x] CLI 子命令架构 (init/config/check/status/history)
- [x] TUI 配置面板
- [x] 实时状态追踪
- [x] mux_broadcast 并行广播
- [x] mux_history 历史查询
- [x] mux_workflow 工作流模板
- [x] 结果对比/Diff 分析
- [x] 自定义 Provider 插件
- [x] 流式输出 (on_progress 回调)
- [x] 智能路由 v2 (关键词 + 历史评分)
- [x] A2A 数据模型 + 任务状态机
- [x] A2A 协作引擎 (review/consensus/debate)
- [x] A2A HTTP Server (Agent Card + JSON-RPC 2.0 + SSE)
- [x] A2A 客户端 + Remote Adapter
- [x] A2A Push Notifications (webhook 回调)
- [x] A2A 端到端集成测试
- [x] 任务持久化 (JSONL)
- [x] 认证机制 (Bearer token)
- [x] 成本追踪 (token usage + 费用估算)
- [x] DashScope adapter + 国产模型定价
- [x] Provider/Model 语法 (`provider/model`)
- [x] 任务自动拆解 (DAG 拓扑排序 + 并行波执行)
- [x] Codex UTF-8 workdir workaround

---

## 近期规划 (P1)

### Web Dashboard (modelmux-dashboard)
- [x] Starlette REST API (status/history/stats/providers/costs)
- [x] 内嵌暗色主题 HTML 面板（5s 自动刷新）
- [x] `modelmux dashboard` 启动本地 Web 服务
- [ ] 历史趋势图表（Chart.js）
- [ ] A2A 协作可视化（轮次、收敛过程）

### 生态集成
- [x] Webhook 通知（Slack/Discord/通用 webhook）
- [x] 基准测试套件 (`modelmux benchmark`)
- [ ] 导出/报告功能
- [ ] VS Code 扩展

---

## 长期规划 (P2)

### A2A 生态
- [ ] A2A 联邦：多个 modelmux 实例互连，形成 agent 网络
- [ ] Agent Discovery: 自动发现局域网内的 A2A agent
- [ ] A2A 协议 v1.0 完整实现

### 桌面应用
- [ ] Tauri 桌面应用（产品成熟后评估）

---

*最后更新: 2026-03-07 (v0.23.0)*
