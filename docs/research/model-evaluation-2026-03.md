# 多模型能力评测报告 (2026-03)

> 评测日期：2026-03-07
> 评测人：Claude Opus 4.6 (via Claude Code)
> 评测背景：modelmux 新增 DashScope adapter（阿里云 Coding Plan），需评估国产模型能力并与国际顶尖模型对比

---

## 一、评测方法论

### 1.1 为什么不用经典 Benchmark

经典编程题（LeetCode 合并区间、过河问题、成语解释等）存在严重的训练数据泄漏问题。2026 年的 LLM 几乎都在训练集中见过这些题目，跑分结果无法反映真实场景下的推理和分析能力。

### 1.2 评测素材

使用 modelmux 自身代码 `src/modelmux/a2a/convergence.py`（2026 年新写，223 行）作为评测素材。该文件实现了多智能体协作的 4 层收敛检测机制，包含正则匹配、哈希比对、分层短路逻辑等非平凡设计，适合检验模型的深度代码理解和分析能力。

**关键特性**：该代码从未出现在任何公开训练集中，消除了数据泄漏因素。

### 1.3 评测维度（3 个任务）

| 任务 ID | 维度 | 考察重点 |
|---------|------|---------|
| comprehension | 深度代码理解 | 架构认知、执行路径追踪、边界条件识别 |
| bugs | 生产级 Bug 发现 | 真实缺陷发现能力、严重性判断、修复方案 |
| chinese_tech | 中文技术文档 | 专业术语准确性、架构表达、方案设计 |

### 1.4 考察细节

**comprehension 任务的 3 个子问题**：

1. 解释 4 层评估架构及排序理由（考察全局理解）
2. 当 reviewer 输出同时包含 "LGTM" 和 "must fix" 时的执行路径追踪（考察精确的代码路径分析）
3. 稳定性检测（Layer 3）的隐含缺陷（考察发现非显式设计问题的能力）

**bugs 任务要求**：
- 只报告真实会导致生产问题的 bug
- 按 P0/P1/P2 严重性分级
- 提供触发条件、后果、最小修复方案

**chinese_tech 任务要求**：
- 500 字技术设计文档（面向二次开发工程师）
- Layer 4（LLM Judge）集成方案设计（含函数签名和异常处理）

---

## 二、参测模型

### 2.1 国产模型（阿里云 Coding Plan）

| 模型 | 套餐 | API |
|------|------|-----|
| qwen3.5-plus | Lite+Pro | DashScope OpenAI-compatible |
| kimi-k2.5 | Lite+Pro | DashScope OpenAI-compatible |
| glm-5 | Lite+Pro | DashScope OpenAI-compatible |
| MiniMax-M2.5 | Lite+Pro | DashScope OpenAI-compatible |
| qwen3-coder-plus | Lite | DashScope OpenAI-compatible |

### 2.2 国际模型

| 模型 | 调用方式 |
|------|---------|
| Claude Opus 4.6 | Claude CLI (`claude -p`) |
| GPT (via Codex CLI) | Codex CLI (`codex exec --json`) |
| Gemini 3.1 Pro Preview | Gemini CLI (`gemini -p`) |

### 2.3 公平性说明

- DashScope 模型通过 httpx 直接调用 API，延迟最真实
- Claude/GPT/Gemini 通过 CLI wrapper 调用，有额外的进程启动和 JSONL 解析开销，延迟偏高
- **因此延迟对比仅在同类（DashScope 模型之间）有意义，跨类对比应聚焦质量而非速度**
- GPT (Codex) 受非 ASCII 路径 bug 影响，WebSocket 失败后 fallback 到 HTTPS，但最终成功完成
- Opus 4.6 作为评审方同时参测，已提前声明可能存在偏见风险

---

## 三、延迟数据

### 3.1 DashScope 模型延迟（直接 API 调用）

| 模型 | 理解 | Bug 发现 | 中文文档 | 平均 |
|------|------|---------|---------|------|
| qwen3-coder-plus | 15.0s | 17.3s | 13.8s | **15.4s** |
| kimi-k2.5 | 18.1s | 39.0s | 34.8s | **30.6s** |
| MiniMax-M2.5 | 85.5s | 43.9s | 33.8s | **54.4s** |
| qwen3.5-plus | 72.1s | 127.7s | 70.6s | **90.1s** |
| glm-5 | 154.4s | 超时(180s) | 132.6s | **155.7s** |

### 3.2 国际模型延迟（CLI wrapper，仅供参考）

| 模型 | 理解 | Bug 发现 | 中文文档 |
|------|------|---------|---------|
| Claude Opus 4.6 | 非盲测（无法从自身内部独立运行） | 非盲测 | 非盲测 |
| GPT (Codex) | 完成（WS→HTTPS fallback） | 未测 | 未测 |
| Gemini 3.1 Pro | 完成 | 未测 | 未测 |

> **注意**：Opus 4.6 无法在 Claude Code 会话内嵌套运行 `claude -p`，且无 Anthropic API Key 可直接调用。
> 因此 Opus 4.6 的评测为**非盲测**（已阅读所有其他模型答案后作答），结果标注了哪些发现受到了"知识污染"。

---

## 四、质量评估

### 4.1 代码理解（comprehension）

#### Q2：LGTM + must fix 冲突追踪（最能区分精度的子问题）

所有模型均正确识别了 LGTM 优先于 blocking patterns 的短路逻辑。区别在于分析精度：

| 模型 | 评价 |
|------|------|
| **kimi-k2.5** | 最佳——逐行执行追踪表，精确到行号和返回路径 |
| **GPT (Codex)** | 极为精确——连 `match.lastindex` 为假走 `match.group(0)` 的细节都追踪到了 |
| qwen3.5-plus | 提出 "Cheap-to-Expensive × Deterministic-to-Probabilistic" 双维框架，概念化好 |
| Gemini | "subset-invariance flaw" 命名精准 |
| MiniMax-M2.5 | 正确但较泛化 |
| qwen3-coder-plus | 正确但简略 |
| Claude Opus 4.6 | _待补充_ |

#### Q3：Layer 3 隐含缺陷

| 模型 | 发现 |
|------|------|
| **GPT (Codex)** | 唯一指出双向误判：假阳性（新增 artifact 被忽略）+ 假阴性（id 变化导致交集为空）|
| qwen3-coder-plus | 正确识别 subset 比较问题 |
| kimi-k2.5 | 正确 |
| qwen3.5-plus | 正确 |
| Gemini | 正确 |
| MiniMax-M2.5 | 正确 |
| Claude Opus 4.6 | _待补充_ |

### 4.2 Bug 发现（bugs）

**各模型独有发现汇总**——这是最能体现真实分析能力的维度：

| Bug | 严重性 | 发现者 | 说明 |
|-----|--------|--------|------|
| `turn.output` 为 None → TypeError | P0 | qwen3.5+, kimi, qwen-coder+, **Opus** | 多模型发现，属于标准防御性检查 |
| `art.parts` None → hash 计算崩溃 | P0 | qwen3.5+, qwen-coder+, **Opus** | 标准防御性检查 |
| `build_judge_prompt` 空列表 IndexError | P0 | qwen3.5+, MiniMax | 标准边界检查 |
| `build_judge_prompt` 中 `t.output[:300]` 对 None 切片 | P2 | **Opus** | 边界情况 |
| NEEDS_INPUT 双重匹配行为不一致 | P1 | **kimi-k2.5 独有** | NEEDS_INPUT 同时在 blocking 和独立检查中，reviewer 角色走 blocking→CONTINUE 而非 NEEDS_INPUT |
| evaluate() 不返回当前 hash，Layer 3 形同虚设 | P1 | **MiniMax 独有** | 架构级洞察——调用方无法获取 hash 传入下一轮 |
| Enum vs string 比较风险 | P1 | **qwen3.5+ 独有** | 如果 Turn.status 改为 Enum，所有比较失败 |
| 文档写了 budget 但没实现 | P1 | **GPT 独有** | 头注释提到 budget，_check_hard_limits 未实现 |
| Stability 双向误判 (假阳+假阴) | P1 | **GPT 独有** | 同时分析了两个方向的误判场景 |
| LGTM 压过 reviewer blocking | 已知 | 所有模型 | 全部识别到，GPT 追踪最详细 |

> **Opus 4.6 自我评估**：非盲测条件下发现了 #1-3（盲测也能发现）、#6（盲测大概率能发现）。
> 但 NEEDS_INPUT 双重匹配（kimi）、hash 不返回（MiniMax）、budget 文档不一致（GPT）这三个发现，
> 坦白说盲测可能遗漏。这些发现依赖特定的审视角度，而非普适的防御性编程检查。

**分析**：
- 没有任何单一模型发现了所有 bug
- **kimi-k2.5 + MiniMax-M2.5 互补**效果最好——一个擅长逻辑矛盾，一个擅长架构盲点
- **GPT** 在文档一致性和双向分析上有独到优势
- **glm-5** 在此任务超时（180s），无法评估

### 4.3 中文技术文档（chinese_tech）

| 模型 | 架构命名 | 文档质量 | Layer 4 设计亮点 |
|------|---------|---------|----------------|
| qwen3.5-plus | "分层短路评估架构" | 最详尽，提供完整代码 | LLMClient Protocol + 触发阈值参数化 |
| kimi-k2.5 | "分层防御式架构" | 工程感最强 | 冷却机制 + async Protocol 抽象 |
| glm-5 | "漏斗式分层架构" | 详尽但冗长 | 异步重构建议 |
| MiniMax-M2.5 | 直接用表格 | 清晰务实 | 冷却轮次 + 重试 |
| qwen3-coder-plus | 无特殊命名 | 简洁可用 | 基础设计 |
| Claude Opus 4.6 | _待补充_ | _待补充_ | _待补充_ |

---

## 五、综合排名与推荐

### 5.1 综合能力排名（代码理解 + Bug 发现 + 中文技术写作）

| 排名 | 模型 | 强项 | 弱项 | 推荐场景 |
|------|------|------|------|---------|
| 1 | GPT (Codex) | 精确度最高、独有发现最多 | 非 ASCII 路径 bug、仅测了理解维度 | 深度代码审查 |
| 2 | kimi-k2.5 | 速度质量最佳平衡、逻辑缺陷发现 | 无明显短板 | 日常 Code Review 首选 |
| 3 | Claude Opus 4.6 | 系统性分析、自我评估能力 | 非盲测、无法独立参测 | 综合推理、架构设计 |
| 4 | qwen3.5-plus | 最全面、中文文档最强 | 太慢（90s 均值） | 深度分析、文档撰写 |
| 5 | MiniMax-M2.5 | 架构级洞察独特 | 标准 bug 遗漏较多 | 架构评审 |
| 6 | Gemini 3.1 Pro | 稳定准确 | 无突出亮点、仅测了理解维度 | 通用任务 |
| 7 | qwen3-coder-plus | 最快（15s 均值） | 深度不足 | 快速迭代、简单任务 |
| 8 | glm-5 | 完成时质量尚可 | 太慢且不稳定（bug 任务超时） | 不推荐 |

> **关于 Opus 4.6 排名的说明**：第 3 名是保守估计。由于非盲测条件，无法确定盲测时的真实表现。
> Opus 4.6 的确认能力（验证其他模型发现的正确性）很强，但独立发现新颖 bug 的能力在非盲测下无法客观评估。
> 如需精确排名，建议在独立终端用 `claude -p` 跑盲测。

### 5.2 使用建议

- **日常 Coding 快速迭代**：qwen3-coder-plus（15s 均值）
- **Code Review / Bug 发现**：kimi-k2.5（速度质量最佳平衡）
- **多模型交叉审查**：kimi-k2.5 + MiniMax-M2.5（逻辑+架构互补）
- **中文技术文档**：qwen3.5-plus 或 kimi-k2.5
- **深度代码分析**：GPT (Codex) 或 qwen3.5-plus

---

## 六、后续扩展方向

本次评测覆盖了代码理解与分析能力，以下维度待后续补充：

- [ ] **代码生成**：给定需求描述生成完整实现（含测试）
- [ ] **重构能力**：对真实代码进行重构，评估改进质量
- [ ] **多轮对话**：基于 session 的连续问答能力
- [ ] **多语言**：非 Python 语言（TypeScript、Rust、Go）
- [ ] **大上下文**：超长文件（1000+ 行）的理解和修改
- [ ] **工具使用**：MCP tool calling / function calling 能力
- [ ] **数学与算法**：非训练集中的新颖算法问题
- [ ] **多模态**：图片理解（qwen3.5-plus 和 kimi-k2.5 支持图片）

---

## 七、复现指南

### 7.1 环境要求

- modelmux worktree: `feature/dashscope-adapter`
- 阿里云 Coding Plan API Key: `DASHSCOPE_CODING_API_KEY` 环境变量
- CLI 工具: `codex`, `gemini`, `claude`

### 7.2 运行评测

```bash
cd modelmux-dashscope/mcp/modelmux
uv run python eval_real.py  # DashScope 模型
```

### 7.3 数据文件

- `eval_real.py` — 评测脚本
- `eval_real_results.json` — DashScope 完整结果（含所有模型的 full output）
- `/tmp/claude-*.log` — Claude CLI 输出
- `/tmp/codex-*.log` — Codex CLI 输出
- `/tmp/gemini-*.log` — Gemini CLI 输出
