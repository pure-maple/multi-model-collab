# Changelog

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
