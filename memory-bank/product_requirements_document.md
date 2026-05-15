# 产品需求文档 (PRD)：通用 CLI AI Coding Agent (MVP 版本)

## 1. 产品概述

- **产品愿景**：打造一个极客友好、终端原生（Terminal-native）的通用 AI Agent，开发者无需离开命令行即可让 Agent 自动理解意图、编写代码、调用工具并执行系统操作。
- **当前阶段目标 (MVP)**：跑通基于纯命令行的交互闭环，实现"终端输入 → 模型思考与规划 → 终端内工具调用 → 渲染执行结果"，重点验证 CLI 下的流式输出体验与基础 Agent 工作流的稳定性。

## 2. 核心功能需求 (MVP 阶段)

### 2.1 终端交互体验 (CLI UX)

**需求描述**：提供流畅、美观且符合开发者直觉的命令行交互界面。

**功能点**：

- **多轮对话 REPL (Read-Eval-Print Loop)**：支持持续的交互式对话，支持方向键上翻历史命令。
- **富文本渲染**：在终端内原生解析并高亮渲染 Markdown 格式，特别是代码块（Syntax Highlighting）。
- **状态可视化**：当 Agent 处于"思考中"、"执行 Web Search" 或 "运行 Python 代码" 等状态时，终端需有明确的 Loading 动画（如 Spinner）或状态提示。
- **流式输出 (Streaming)**：打字机效果逐字输出模型回复，做到低延迟响应。

### 2.2 多方通用大模型统一接入层 (Model Gateway)

**需求描述**：系统需支持动态切换底层的 LLM，配置过程需极其轻量。

**功能点**：

- **统一 API 适配**：兼容 OpenAI 标准协议作为主接入方式，支持切换至 DeepSeek、Gemini、MiniMax 等。
- **本地配置驱动**：通过项目根目录的 `.env` 文件或 `~/.config/agent/config.yaml` 集中管理 API Key 和默认模型，无需每次启动时指定。

### 2.3 Agent 工作流引擎 (Workflow Engine)

**需求描述**：构建底层状态机，管理 Agent 在复杂任务中的思考与执行流。

**功能点**：

- **ReAct (Reason + Act)**：实现基础循环。Agent 分析终端输入，决定输出最终文本还是生成工具调用指令。
- **Plan and Execute (计划与执行)**：针对如"帮我写一个完整脚本并测试"的指令，Agent 先在终端输出分步 Plan，然后逐节点执行状态图。
- **Reflection (反思机制)**：当工具执行出错（例如 Python 代码在本地抛出异常），Agent 必须能够捕获 stderr 并在后台触发自动重试或自我修正，然后再向用户报告最终结果。

### 2.4 基础工具调用系统 (Tool Calling)

**需求描述**：为 Agent 提供与外部世界及本地计算环境交互的接口。

**功能点**：

- **Web Search (网络搜索)**：接入标准搜索 API，使 CLI Agent 具备联网查询文档或报错信息的能力。
- **Python Execute (本地执行器)**：
  - Agent 生成的 Python 代码可以直接在当前的本地环境中（或指定的虚拟环境中）运行。
  - 精准捕获标准输出 (stdout) 和错误流 (stderr) 并回传给 Agent。

## 3. 非功能性需求

- **极简启动**：系统应被打包为一个全局可执行命令（例如通过 pip 安装后，直接在终端输入 `myagent` 即可唤醒）。
- **清晰的日志分级**：在终端界面中，Agent 的内部思考过程（Thought/Plan）、工具调用过程（Action）与最终回复（Observation/Response）需要通过不同的颜色进行区分，避免信息过载。
- **优雅的中断处理**：用户按下 `Ctrl+C` 时，应能安全地中断当前正在执行的工具或正在生成的回复，并平滑退回到对话输入提示符，而不是直接让整个程序崩溃退出。

## 4. MVP 开发与演进路线 (Roadmap)

### Milestone 1: CLI 基建与模型打通

- 搭建基础的命令行 REPL 循环。
- 集成 `rich` 等库实现终端界面的 Markdown 渲染和颜色美化。
- 通过 `.env` 加载配置，跑通调用 DeepSeek 或其他模型的流式对话。

### Milestone 2: 工具集成与 ReAct 闭环

- 编写 Web Search 和 Python Execute 两个基础 Tool 的封装函数。
- 引入工作流状态图（如 LangGraph），将大模型与 Tool 绑定，跑通单一的 ReAct 循环。
- 在终端实现工具调用时的状态提示（如显示 "Agent is searching the web..."）。

### Milestone 3: 复杂任务与错误反思

- 实现 Plan and Execute 逻辑，在终端以列表形式展示 Agent 的计划任务。
- 完善 Python Execute 的错误捕获机制。
- 测试自愈能力：要求 Agent 写一段带有语法错误的 Python 代码并运行，验证其能否自动读取终端报错、修改代码并重新执行成功。
