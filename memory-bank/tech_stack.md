# 技术栈方案：CLI AI Coding Agent (MVP 版本)

为了实现 CLI AI Coding Agent，并且满足"尽可能简单、同时稳健和鲁棒"的要求，这套技术栈方案主要围绕 Python 生态构建。核心原则是：避免过度封装，采用经过生产检验的轻量级库，把复杂度留给大模型，把确定性留给代码。

## 1. 核心语言与 CLI 交互层

- **开发语言**：Python 3.10+
  - AI 生态最完善，无论是调用模型还是执行脚本都最原生。

### 终端 UI 渲染：Rich

- 负责终端的美化输出，可完美渲染 Markdown、代码块（带语法高亮）、表格。
- 提供 `Console.status()` 方法实现"Agent 思考中"的 Spinner 动画。
- 极其稳定，开箱即用，是 Python CLI 领域美化输出的事实标准。

### 交互式输入 (REPL)：prompt_toolkit

- 替代原生的 `input()`，用于构建强大的多轮对话循环。
- 支持方向键查看历史记录、多行输入（对粘贴代码块非常重要）、快捷键中断。
- 能够提供类似 IPython 的丝滑输入体验。

## 2. 多方通用大模型统一接入层 (Model Gateway)

### 核心库：LiteLLM

- 将市面上几乎所有大模型（DeepSeek、Gemini、Claude、MiniMax 等）API 统一转化为 OpenAI 标准格式的轻量级代理库。
- 极度简化代码：只需写一套标准的 OpenAI API 调用代码，通过改变传参（如 `model="gemini/gemini-pro"` 或 `model="deepseek/deepseek-chat"`），LiteLLM 自动处理不同厂商的鉴权和请求格式适配。
- 支持流式输出，异常处理机制完善。

### 配置管理：python-dotenv

- 读取项目根目录的 `.env` 文件，管理各类 API Key。
- 简单、直接、安全。

## 3. Agent 工作流引擎 (Workflow Engine)

### 核心框架：LangGraph

- 作为 Agent 的底层状态机引擎，编排 ReAct、Plan and Execute 以及 Reflection 循环。
- 基于图（Graph）的状态流转机制完美契合复杂 Agent 的逻辑：每一步（如"思考"、"调用工具"、"报错反思"）定义为图中的节点，状态数据在节点间传递。
- 相比于传统线性代码或复杂的 Prompt 链，处理"执行失败 → 回退反思 → 重新生成"这种闭环时，代码结构更清晰、鲁棒性极强、易于追踪报错。

## 4. 基础工具调用系统 (Tool Calling)

### 网络搜索 (Web Search)：Tavily API + `tavily-python`

- 为 Agent 提供联网能力。
- Tavily 是专门为 AI Agent 优化的搜索引擎，直接返回经过清洗、无广告、高相关性的上下文文本。
- 大大降低 HTML 解析复杂度，显著提高 Agent 获取信息的准确率。

### 代码执行器 (Python Execute)：Python 原生 `subprocess` 模块

- 在本地执行 Agent 生成的 Python 代码。
- MVP 阶段无需引入 Docker 容器或沙盒，直接使用 `subprocess.run()`，通过 `capture_output=True` 捕获 stdout 和 stderr。
- 如果返回码不为 0，直接将 stderr 内容作为 Observation 返回给 LangGraph 中的 Reflection 节点进行纠错。

## 5. 打包与发布

### 打包工具：Click / Typer + pip

- 将 Python 脚本封装成一个全局命令行工具。
- 使用 Typer 可利用 Python 的类型提示快速生成命令行接口。
- 配合 `setup.py` 或 `pyproject.toml`，用户通过 `pip install -e .` 安装后，直接在终端键入 `myagent` 唤醒程序。

## 技术栈全景图总结

| 层级             | 技术选型                                   |
| ---------------- | ------------------------------------------ |
| 入口与交互       | `prompt_toolkit` (输入) + `Rich` (输出)    |
| 配置与路由       | `python-dotenv` + `LiteLLM`                |
| 大脑与控制流     | `LangGraph`                                |
| 手与脚 (Tools)   | `Tavily API` + `subprocess`                |

这套方案没有引入重量级的中间件或复杂的微服务架构，所有组件都是 Python 生态中轻量且专注于单一任务的最佳实践。
