# 产品需求文档 (PRD)：baicode CLI AI Coding Agent

## 1. 产品概述

**产品愿景**：打造一个终端原生的 AI Coding Agent。开发者无需离开命令行，即可让模型理解意图、规划任务、调用本地工具、执行命令并汇总结果。

**当前阶段目标 (MVP 已落地)**：跑通 CLI 多轮对话、ReAct 工具调用、Reflection 自愈、Plan-and-Execute 宏图，以及 Markdown 终端渲染体验。

## 2. 核心功能需求

### 2.1 终端交互体验

- 全局命令 `baicode` 启动 REPL。
- 支持多行输入、方向键历史、`~/.baicode_history` 持久化。
- 最终回复以 Markdown 渲染，代码块使用 monokai 语法高亮。
- 思考、工具执行、规划、重规划等状态有 Rich spinner 或 panel 提示。
- 工具 Observation 默认静默，不直接刷屏。
- 输入态 `Ctrl+C` / `Ctrl+D` 干净退出；工具态 `Ctrl+C` 中断当前工具并保持 REPL 存活。

### 2.2 模型接入层

- 通过 LiteLLM 统一接入 OpenAI-compatible 模型。
- 当前默认模型为 `deepseek/deepseek-v4-flash`。
- 配置仅来自 `.env`：
  - 必需：`DEEPSEEK_API_KEY`、`TAVILY_API_KEY`
  - 可选：`OPENAI_API_KEY`
- 当前不支持 YAML 或 `~/.config/agent/config.yaml`。

### 2.3 Agent 工作流

- **ReAct**：模型可在回答前调用工具，工具结果回喂模型。
- **Reflection**：`python_exec` 报错、`shell_exec` 超时、工具异常、JSON 参数解析失败等会进入反思重试；每步默认最多 3 次。
- **Plan-and-Execute**：
  - Planner 将用户请求拆成 0-5 个步骤。
  - 0/1 step 走 `react_node`，避免单步任务出现过度 Plan UX。
  - 2+ step 走 Executor / Replanner / Finalizer 宏图。
  - Executor 每步独立调用微图，预算独立。
  - Replanner 在步骤失败时插入补救计划或 abort。
  - Finalizer 汇总多步执行历史，给用户自然语言结果。

### 2.4 工具能力

- `python_exec(code)`：本地 Python 子进程执行，10s 超时，用于计算、代码验证、文件检查等确定性任务。
- `shell_exec(command)`：本地 shell 命令执行，60s 超时，用于文件系统、git、包管理、日志检查等终端操作。
- `web_search(query, topic, days)`：Tavily 搜索 Top-5，用于联网查询、新闻和技术资料。

### 2.5 实时结构化数据限制

baicode 当前不能可靠提供天气预报、股价、航班状态、实时汇率、体育比分、实时卫星图像等结构化实时数据。System prompt 对这类请求要求模型直接说明能力限制并建议使用专用网站或 App；`react_node` 对工具预算耗尽提供 fail-soft 友好兜底。

## 3. 非功能性需求

- **低安装复杂度**：`pip install -e .` 后即可使用 `baicode`。
- **稳定错误边界**：鉴权失败致命退出；网络、限流、普通模型错误不杀 REPL。
- **上下文洁净**：跨轮 `messages` 只保留用户消息和最终 assistant 回复，宏图内部 tool / plan / history 不泄露到主对话。
- **安全边界明确**：MVP 不做 Docker 沙箱，本地工具继承调用方权限。

## 4. 当前路线图状态

- Milestone 1：CLI 基建 + 模型网关，已完成。
- Milestone 2：工具集成 + ReAct 闭环，已完成。
- Milestone 3：Reflection + shell 工具 + Markdown 渲染，已完成。
- Milestone 4：Plan-and-Execute 宏图 + Replanner + Finalizer，已完成。

## 5. 后续候选方向

- pytest 自动化测试套件。
- Docker / 容器沙箱隔离 `python_exec` 和 `shell_exec`。
- Planner / Executor / Finalizer 分模型。
- Ctrl+C 跨步骤取消整个 plan。
- History 自动 summarize 或长度上限。
