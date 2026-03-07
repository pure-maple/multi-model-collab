# modelmux 功能规划

## 当前状态 (v0.28.0)

### MCP 工具
| 工具 | 功能 |
|------|------|
| mux_dispatch | 单模型分发（智能路由 v4、failover、会话连续性、自动任务拆解） |
| mux_broadcast | 多模型并行分发（共识/对比、Provider/Model 语法） |
| mux_collaborate | A2A 迭代多 agent 协作（review/consensus/debate、DashScope provider/model 支持） |
| mux_workflow | 多步流水线编排 |
| mux_feedback | 用户反馈评分（1-5 分，驱动路由优化） |
| mux_history | 历史查询与分析（含成本统计） |
| mux_check | 可用性检查与状态概览（含路由 v4 诊断） |

### A2A HTTP Server
| 端点 | 功能 |
|------|------|
| GET /.well-known/agent.json | Agent Card 能力发现 |
| POST / (tasks/send) | 同步任务执行（支持 Push Notification） |
| POST / (tasks/get) | 查询任务状态 |
| POST / (tasks/cancel) | 取消运行中任务 |
| POST / (tasks/sendSubscribe) | SSE 流式推送（支持 Push Notification） |

### CLI 命令
`modelmux` / `a2a-server` / `dispatch` / `broadcast` / `feedback` / `init` / `config` / `check` / `status` / `history` / `export` / `benchmark` / `dashboard` / `clean` / `version`

### Provider 适配器
codex / gemini / claude / ollama / dashscope / A2A remote / 自定义插件

### 基础设施
审计日志 / 策略引擎 / Profile 系统 / 实时状态追踪 / TUI 配置面板 / 流式输出 / 智能路由 v4（关键词+历史+benchmark+反馈+TTL缓存）/ 成本追踪 / Web Dashboard（趋势图表 + 协作可视化 + 反馈面板）/ Webhook 通知 / 导出报告 / 基准测试 / A2A 联邦 POC / 结构化日志 / GitHub Actions CI 集成

---

## 已完成 (v0.1.0 → v0.24.0+)

- [x] 初始原型：三大 CLI 适配器
- [x] 审计日志 + 策略引擎
- [x] 调用方平台检测与自动排除
- [x] Profile 系统
- [x] 执行容错 (Failover)
- [x] Ollama 适配器
- [x] CLI 子命令架构 (init/config/check/status/history/export/benchmark/dashboard)
- [x] TUI 配置面板
- [x] 实时状态追踪
- [x] mux_broadcast 并行广播
- [x] mux_history 历史查询
- [x] mux_workflow 工作流模板
- [x] 结果对比/Diff 分析
- [x] 自定义 Provider 插件
- [x] 流式输出 (on_progress 回调)
- [x] 智能路由 v2 → v3 → v4 (关键词 + 历史 + benchmark + 用户反馈)
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
- [x] Web Dashboard (REST API + Chart.js 趋势图表 + A2A 协作可视化)
- [x] Webhook 通知 (Slack/Discord/通用)
- [x] 基准测试套件 (`modelmux benchmark`)
- [x] 导出/报告功能 (`modelmux export`)
- [x] mux_collaborate DashScope provider/model 支持
- [x] A2A 联邦概念验证 (10 个测试覆盖完整链路)
- [x] 用户反馈工具 (mux_feedback) + 路由 v4 四信号融合
- [x] 安全加固 Phase 1+2 (v0.25.0 + v0.25.1): 3-agent 并行安全审计全量修复
- [x] 结构化日志 (MODELMUX_LOG_LEVEL/FORMAT)
- [x] Dashboard 反馈面板 + mux_check 诊断模式
- [x] 核心模块 logging 清理（bare except→logger）

---

## 近期规划 (P1)

### 质量与稳定性
- [x] 全量代码审查：3-agent 并行安全审计（SSRF、策略绕过、sandbox 提权、flag 注入、XSS、路径遍历）
- [x] 错误恢复增强：subprocess zombie 防护（kill 回退）、Dashboard 输入验证
- [x] 日志系统改进：modelmux.log 模块 + MODELMUX_LOG_LEVEL/FORMAT 环境变量
- [x] 核心模块 silent exception 清理

### 智能路由 v3 → v4
- [x] 基于 benchmark 结果的自动路由权重调整
- [x] 任务类型分类器（analysis/generation/reasoning/language）
- [x] 用户反馈闭环（mux_feedback 工具 + routing v4 四信号融合）

### 生态集成
- [ ] VS Code 扩展（MCP 客户端 + Dashboard WebView）
- [x] GitHub Actions 集成（CI 中使用 modelmux 进行代码审查）
- [x] `modelmux dispatch` CLI 子命令（JSON 输出，脚本/CI 友好）
- [x] `modelmux broadcast` / `feedback` CLI 子命令
- [x] Dashboard SSE 实时推送（替代轮询）
- [x] CLI dispatch `--failover` + `--max-retries` + broadcast `--compare`
- [x] 路由数据 TTL 缓存 + Provider 健康度摘要 + 配置校验

---

## 长期规划 (P2)

### A2A 生态
- [ ] A2A 联邦正式版：服务发现 + 负载均衡 + 健康检查
- [ ] Agent Discovery: mDNS/局域网自动发现
- [ ] A2A 协议 v1.0 完整实现
- [ ] 联邦拓扑可视化

### 产品化
- [ ] Tauri 桌面应用（产品成熟后评估）
- [ ] 多租户支持
- [ ] 用户管理与权限控制

---

*最后更新: 2026-03-07 (v0.28.0+, 817 tests, 69% coverage)*
