# Changelog

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
