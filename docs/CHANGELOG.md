# Changelog

## v0.26.0 (2026-03-07)

### User Feedback Loop (routing v4)
- **New `mux_feedback` tool**: Rate dispatch results 1-5 to improve routing quality
  - Auto-detects provider and task category from dispatch history
  - Supports `list_recent=True` to view recent feedback
- **Routing v4**: Four-signal composite scoring
  - Keyword patterns (35%) + dispatch history (25%) + benchmark quality (20%) + user feedback (20%)
  - Adaptive weight degradation when data sources unavailable
  - `mux_check` now shows v4 routing diagnostics with feedback data status
- **Feedback persistence**: `~/.config/modelmux/feedback.jsonl`

### Bug Fixes (from DashScope cross-review)
- **Engine convergence fix** (P0): `_execute_round` sequential mode now returns turns instead of `[]`, enabling `convergence.evaluate()` to run correctly. Removed double `ctx.update_after_turn` call.
- **Generator return value fix** (P0): `BaseAdapter.run()` uses `while/next` loop instead of `for` to correctly capture `stream_subprocess` exit code via `StopIteration.value`
- **History metadata fix** (P1): `log_result` now places metadata (`ts`/`source`/`task`) after `**result_dict` to prevent override
- **Audit timezone fix** (P1): `read_recent` treats naive ISO timestamps as UTC to match `time.time()` cutoff

### Stats
- 25 new tests (14 feedback + 11 bugfix), 413 total
- New file: `feedback.py` (user rating collection + per-provider scoring)

## v0.25.1 (2026-03-07)

### Security Hardening (Phase 2)
- **Policy Enforcement Parity**: `mux_broadcast` now checks policy for ALL target providers (was only first); `mux_workflow` and `mux_collaborate` now enforce policy before execution
- **A2A Default Binding**: Server defaults to `127.0.0.1` instead of `0.0.0.0` to prevent unintended network exposure (use `--host 0.0.0.0` to opt-in)
- **Request Body Size Limit**: A2A HTTP server enforces 1MB max request body to prevent DoS
- **Task ID Hijacking Prevention**: `tasks/send` and `tasks/sendSubscribe` now generate server-side task IDs (ignoring client-supplied IDs) to prevent cross-client task manipulation
- **Timeout Cap**: `timeout_per_turn` in A2A capped at 3600s to prevent resource exhaustion
- **GenericAdapter Template Injection**: Built-in substitution keys (`task`, `workdir`, `sandbox`, `session_id`) protected from `extra_args` override
- **Environment Variable Blocklist**: `ProviderConfig.to_env_overrides()` blocks dangerous env vars (`PATH`, `LD_PRELOAD`, `PYTHONPATH`, etc.)
- **DashScope SSRF Fix**: `base_url` no longer accepted from `extra_args` (only from config/env overrides)
- **Policy Parse Logging**: Failed policy.json parsing now logs a warning instead of silently falling back to permissive defaults

### Stats
- 15 new security tests (388 total)
- All remaining findings from 3-agent security audit addressed

## v0.25.0 (2026-03-07)

### Security Hardening (based on 3-agent parallel security audit)
- **SSRF Protection**: Push notification URLs validated against private/reserved IP ranges, loopback, link-local, cloud metadata endpoints
- **A2A Policy Enforcement**: A2A HTTP server now enforces the same provider policy (allowlist/blocklist/sandbox) as the MCP path — previously completely bypassed
- **Sandbox Escalation Fix**: Codex adapter `sandbox_map` defaults to `"read-only"` for unknown values (was passthrough)
- **CLI Flag Injection Guard**: `sanitize_extra_args()` strips values starting with `-` to prevent argument injection via model/profile params
- **XSS Protection**: Dashboard HTML escaping via `esc()` (v0.24.0+)
- **Path Traversal Guard**: Status file names sanitized (v0.24.0+)
- **Subprocess Zombie Prevention**: `process.kill()` fallback after `process.terminate()` timeout
- **Dashboard Input Validation**: All query params clamped to safe ranges (prevents negative/overflow/NaN)

### Infrastructure
- **Structured Logging**: `modelmux.log` module with `MODELMUX_LOG_LEVEL`/`MODELMUX_LOG_FORMAT` env vars
  - Text and JSON output formats, integrated at CLI and MCP server entry points
- **Flaky Test Fix**: Trend bucket boundary test stabilized

### Stats
- 48 new tests (30 security + 10 logging + 8 dashboard param), 361 total
- All security findings from parallel 3-agent audit addressed

## v0.24.0 (2026-03-07)
- **Dashboard 趋势图表**: `/api/trends` 端点返回时间序列聚合数据
  - 按小时分桶：分发量、成功率、平均延迟、累计成本
  - Chart.js 前端：堆叠柱状图（成功/失败）+ 双轴折线图（成功率/延迟）
  - 支持自定义时间范围和桶大小（`?hours=24&bucket=60`）
- **导出/报告功能**: `modelmux export --format csv/json/md`
  - CSV：完整字段导出，兼容 Excel/Google Sheets
  - JSON：含统计和成本数据的结构化报告
  - Markdown：带表格的人类可读报告（Summary + Provider Breakdown + Cost + History）
  - 支持文件输出（`--output report.csv`）、时间范围/provider 过滤
- 28 个新测试（9 trends + 3 dashboard API + 16 export），总计 296 个测试通过

## v0.23.0 (2026-03-07)
- **Web Dashboard**: `modelmux dashboard` 启动本地 Web 监控面板
  - Starlette REST API: /api/status, /api/history, /api/stats, /api/providers, /api/costs
  - 内嵌暗色主题 HTML 面板，5 秒自动刷新
  - 活跃分发表、provider 健康状态、统计概览、费用汇总、历史记录
- **Webhook 通知**: 分发完成时推送到 Slack/Discord/Generic webhook
  - 自动检测 URL 格式（Slack blocks、Discord embeds、通用 JSON）
  - profiles.toml `[notifications]` 配置或 `MODELMUX_WEBHOOK_URL` 环境变量
  - 事件过滤（仅 success/error 等）、后台线程非阻塞
  - 集成到 `log_result`，所有分发源自动触发
- **基准测试套件**: `modelmux benchmark` 标准化 provider 对比评测
  - 5 个内置任务：code_review、code_generation、reasoning、summarization、translation
  - 关键词匹配质量评分
  - 按 provider 汇总：成功率、平均延迟、关键词命中率
  - JSON 导出（--output）、任务过滤（--tasks）、--list-tasks
- 44 个新测试（14 dashboard + 16 notifications + 14 benchmark），总计 268 个测试通过

## v0.22.0 (2026-03-07)
- **Task Decomposition**: `mux_dispatch(auto_decompose=True)` 自动拆解复杂任务
  - 三阶段流程：planner 分析 → wave executor 并行/顺序执行 → merger 合并结果
  - DAG 拓扑排序，支持依赖声明和并行执行波
  - 新增 `decompose.py` 模块（DecompositionPlan, Subtask, parse, merge）
- **Provider/Model 语法**: `mux_dispatch(provider="dashscope/kimi-k2.5")` 和
  `mux_broadcast(providers=["dashscope/kimi-k2.5", "dashscope/MiniMax-M2.5"])`
  - 同一 provider 不同 model 可并行广播
  - `_parse_provider_spec()` 统一解析
- **DashScope token usage**: 从 OpenAI 兼容 API 响应提取 usage 字段
  - `costs.py` 新增 DashScope 全模型定价（Coding Plan 包月 = $0）
  - `estimate_cost()` 支持 `provider/model` 格式
- 28 个新测试，总计 217 个测试通过

## v0.21.0 (2026-03-07)
- **成本追踪**: TokenUsage 数据类 + parse_token_usage() 适配器方法
- 自动从 Codex (turn.completed) 和 Gemini (usageMetadata) 提取 token 用量
- 新增 costs.py 模块（多模型定价表 + 聚合统计）
- mux_history(costs=True) 和 CLI --costs 参数
- **文档全面更新**: README 中英文完全重写，反映 v0.20.0+ 全部功能
- **仓库清理**: 移除不适合公开的原始会话日志、内部笔记（净减少 889 行）
- **安全加固**: .gitignore 添加 .mcpregistry_*、.env、*.key、*.pem
- 22 个新测试，总计 183 个测试通过

## v0.20.0 (2026-03-07)
- **结构化 Release Notes**: 每个版本独立的中英双语发布说明 (`docs/releases/`)
- **CI 自动 GitHub Release**: tag 推送后自动从 `docs/releases/{tag}.md` 创建 Release
- **历史版本补全**: 补全 v0.1.0 ~ v0.19.0 所有版本的详细 Release Notes
- **TaskStore JSONL 持久化**: A2A 终端任务持久化到 `a2a-tasks.jsonl`，重启恢复
- **A2A E2E 测试**: 10 个异步集成测试 (httpx AsyncClient + ASGI transport)
- **`--no-persist` CLI 参数**: 禁用持久化，仅内存运行
- 146 个测试全部通过

## v0.19.0 (2026-03-06)
- **A2A HTTP Server**: 首个 Agent-to-Agent 协议 HTTP 传输层实现
- `GET /.well-known/agent.json`: Agent Card 端点，自动从已安装的适配器和协作模式生成能力卡片
- `POST /` JSON-RPC 2.0: 支持 `tasks/send`、`tasks/get`、`tasks/cancel` 方法
- `tasks/sendSubscribe`: SSE 流式传输，实时推送协作进度、工件和状态变更事件
- `TaskStore`: 内存任务存储，支持自动淘汰旧任务（上限 1000）
- `modelmux a2a-server` CLI 子命令: `--host`、`--port`、`--workdir`、`--sandbox` 参数
- 基于 Starlette + uvicorn（复用 mcp[cli] 传递依赖，零额外依赖）
- Codex UTF-8 workaround: 非 ASCII workdir 自动创建临时 ASCII symlink
- 17 个新测试（总计 107 个）

## v0.18.0 (2026-03-06)
- **A2A 协作引擎**: 首个 Agent-to-Agent 协议实现，真正的多 agent 迭代协作
- `mux_collaborate` MCP 工具: 支持 review/consensus/debate 三种协作模式
- A2A 数据模型: Task 状态机 (submitted→working→input-required→completed/failed)、Message/Part/Artifact、AgentCard
- 分层上下文管理: 固定记忆 + 滚动摘要 + 最近原文窗口 + 工件索引
- 四层收敛检测: 硬上限 → 结构化信号 → 稳定性检测 → LLM 裁判
- 三种协作模式: review（实现→审查→修订循环）、consensus（多视角并行+合成）、debate（对抗辩论+仲裁）
- 协作引擎独立于传输层，未来可同时服务 MCP 和 A2A HTTP
- 23 个新测试（总计 82 个）

## v0.17.0 (2026-03-06)
- **智能路由 v2**: 基于历史分发数据的自适应路由
- 新模块 `routing.py`: 关键词匹配 (60%) + 历史性能评分 (40%) 加权路由
- 历史评分考量: 成功率 (70%) + 延迟速度 (30%)
- 自适应权重: 历史数据 ≥5 次用 40% 权重，2-4 次用 25%，不足 2 次仅用关键词
- 路由模式已从 server.py 提取到独立模块，消除重复代码
- 13 个新路由测试（总计 59 个测试）

## v0.16.0 (2026-03-06)
- **流式输出**: 所有 MCP 工具（dispatch/broadcast/workflow）支持逐行流式进度更新
- on_progress 回调逐行触发，实时更新 status 文件中的 output_preview 和 output_lines
- 节流写入（0.5s 间隔），避免高频 I/O 影响性能
- DispatchStatus 新增 output_lines 字段，可跟踪输出行数

## v0.15.0 (2026-03-06)
- **自定义 Provider 插件**: 用户可在 profiles.toml 的 `[providers.*]` 中注册任意 CLI 工具
- GenericAdapter: 通过 command + args 模板（{task}, {workdir}）驱动任意命令行工具
- mux_dispatch 现接受任意 provider 名称，不限于内置的 4 个
- mux_check 中自定义 provider 标记 `custom: true`

## v0.14.0 (2026-03-06)
- **结果对比**: mux_broadcast 新增 `compare=True` 参数
- Jaccard 相似度分析、速度排名、各 provider 独有术语
- 共识分数 (agreement_score) 量化多模型一致性

## v0.13.0 (2026-03-06)
- **mux_workflow**: 新增工作流模板引擎，多步流水线编排
- 内置工作流: `review`（codex 实现 → claude 审查）、`consensus`（多模型共识合成）
- 用户自定义工作流: profiles.toml 的 `[workflows.*]` 配置
- 步骤间通过 `{step_name}` 占位符传递输出
- `list_workflows=True` 查看所有可用工作流

## v0.12.0 (2026-03-06)
- **mux_history**: 新增 MCP 工具，支持按 provider/状态/时间范围查询分发历史
- **history.jsonl**: 完整分发结果持久化存储，自动轮转（10MB 上限）
- **modelmux history**: CLI 查看最近分发记录
- **modelmux history --stats**: 按 provider 统计成功率、平均延迟

## v0.11.0 (2026-03-06)
- **mux_broadcast**: 新增并行广播工具，同一任务同时发给多个模型
- asyncio 并行执行，比顺序调用快数倍
- 自动选择所有可用 provider（排除调用方）
- 返回聚合结果含 success/error 统计

## v0.10.0 (2026-03-06)
- **modelmux config**: TUI 配置面板（基于 textual）
- Overview/Routing/Policy 三个标签页，可视化编辑
- textual 作为可选依赖：`pip install modelmux[tui]`
- 保存写入 profiles.toml + policy.json

## v0.9.0 (2026-03-06)
- **实时状态追踪**: 分发期间写入 status 文件，支持外部监控
- **modelmux status**: CLI 查看活跃分发
- **modelmux status -w**: 实时刷新模式
- mux_check 输出包含 _active_dispatches

## v0.8.0 (2026-03-06)
- **modelmux init**: 交互式配置向导，自动检测 CLI、生成配置
- **modelmux check**: 快速 CLI 可用性检查
- **modelmux version**: 版本显示
- CLI 重构为 argparse 子命令架构

## v0.7.0 (2026-03-06)
- **Ollama 适配器**: 支持本地模型（DeepSeek、Llama、Qwen 等）
- `mux_dispatch(provider="ollama", model="deepseek-r1")`
- 自动过滤下载进度输出

## v0.6.0 (2026-03-06)
- **执行容错 (Failover)**: Provider 失败时自动重试下一个
- MCP 进度通知 (`ctx.info()`)
- failover_from 字段标识原始 provider

## v0.5.0 (2026-03-06)
- 工具重命名: collab_dispatch → mux_dispatch, collab_check → mux_check
- 包重命名: collab-hub → modelmux

## v0.4.x
- Trusted Publisher 自动发布
- MCP Registry 注册
- PyPI 包发布

## v0.3.0
- 审计日志 (audit.jsonl)
- 策略引擎 (policy.json)

## v0.2.0
- 首次 PyPI 发布
- 调用方平台检测与自动排除
- 用户偏好 Profile 系统

## v0.1.0
- 初始原型：tmux + MCP 混合架构
- 三大 CLI 适配器（Codex、Gemini、Claude）
- 智能路由、会话连续性
