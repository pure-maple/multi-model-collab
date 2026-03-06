# modelmux 功能规划

## 当前状态 (v0.21.0)

### MCP 工具
| 工具 | 功能 |
|------|------|
| mux_dispatch | 单模型分发（智能路由 v2、failover、会话连续性） |
| mux_broadcast | 多模型并行分发（共识/对比、结果比较） |
| mux_collaborate | A2A 迭代多 agent 协作（review/consensus/debate） |
| mux_workflow | 多步流水线编排 |
| mux_history | 历史查询与分析 |
| mux_check | 可用性检查与状态概览 |

### A2A HTTP Server
| 端点 | 功能 |
|------|------|
| GET /.well-known/agent.json | Agent Card 能力发现 |
| POST / (tasks/send) | 同步任务执行 |
| POST / (tasks/get) | 查询任务状态 |
| POST / (tasks/cancel) | 取消运行中任务 |
| POST / (tasks/sendSubscribe) | SSE 流式推送 |

### CLI 命令
`modelmux` / `a2a-server` / `init` / `config` / `check` / `status` / `history` / `version`

### Provider 适配器
codex / gemini / claude / ollama / 自定义插件

### 基础设施
审计日志 / 策略引擎 / Profile 系统 / 实时状态追踪 / TUI 配置面板 / 流式输出 / 智能路由 v2

---

## 已完成 (v0.1.0 → v0.21.0)

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
- [x] Codex UTF-8 workdir workaround

---

## 近期规划 (P0)

### A2A 协议增强
- [x] **A2A 客户端**: 作为 A2A 客户端连接外部 A2A agent（Client + Remote Adapter + 配置集成）
- [x] **端到端集成测试**: httpx AsyncClient → A2A server → 协作引擎 → 完整链路验证（10 tests）
- [x] **任务持久化**: 重启后恢复已完成任务（JSONL 持久化 + `--no-persist` CLI 选项）
- [x] **认证机制**: Bearer token + constant-time comparison
- [ ] **Push Notifications**: A2A 协议的异步结果通知（webhook 回调）

### 成本追踪
- [x] 按 provider 追踪 token 用量（Codex/Gemini 自动提取）
- [x] 费用估算（多模型定价表 + 聚合统计）
- [x] `mux_history(costs=True)` 和 `modelmux history --costs`

### 任务拆解
- [ ] 复杂任务自动拆分为子任务
- [ ] 分发给最适合的模型分别处理
- [ ] 结果自动合并

---

## 中期规划 (P1)

### Web Dashboard (modelmux-dashboard)
- [ ] FastAPI 后端 + 轻量前端
- [ ] 实时监控面板：活跃分发、历史图表、provider 健康
- [ ] 可视化工作流编辑器
- [ ] A2A 协作可视化（轮次、收敛过程）
- [ ] `modelmux dashboard` 启动本地 Web 服务

### 生态集成
- [ ] Webhook 通知（Slack/Discord/邮件）
- [ ] VS Code 扩展
- [ ] 基准测试套件
- [ ] 导出/报告功能

---

## 长期规划 (P2)

### A2A 生态
- [ ] A2A 联邦：多个 modelmux 实例互连，形成 agent 网络
- [ ] Agent Discovery: 自动发现局域网内的 A2A agent
- [ ] A2A 协议 v1.0 完整实现（当正式发布时）

### 桌面应用
- [ ] Tauri 桌面应用（产品成熟后评估）

---

*最后更新: 2026-03-07 (v0.20.0)*
