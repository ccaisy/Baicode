# 技术栈方案：baicode CLI AI Coding Agent

本文记录当前代码实际采用的技术栈与取舍。它是面向接手开发的当前态说明，不是早期方案草稿。

## 1. 运行环境与包结构

- **语言**：Python 3.10+
- **包布局**：`src/` layout，源码位于 `src/baicode/`
- **打包入口**：`pyproject.toml` 的 `[project.scripts] baicode = "baicode.cli:main"`
- **安装方式**：`pip install -e .`
- **配置来源**：项目目录或上级目录中的 `.env`，由 `python-dotenv.find_dotenv(usecwd=True)` 查找
- **配置项**：
  - 必需：`DEEPSEEK_API_KEY`、`TAVILY_API_KEY`
  - 可选：`OPENAI_API_KEY`
  - 默认模型：`deepseek/deepseek-v4-flash`

当前代码没有引入 Click / Typer，也不支持 YAML 配置。全局命令由 setuptools entry point 直接指向 `baicode.cli:main`。

## 2. CLI 交互与终端渲染

### prompt_toolkit

- 用于 REPL 输入循环。
- `PromptSession(multiline=True, history=FileHistory("~/.baicode_history"))` 支持多行输入和跨会话历史。
- 顶层捕获 `KeyboardInterrupt` / `EOFError`，输入态退出时不泄露 traceback。

### Rich

- 用于 banner、spinner、Plan panel、Markdown 回复渲染。
- 最终回复通过 `rich.live.Live` + `rich.markdown.Markdown(code_theme="monokai")` 做伪流式打字机渲染。
- 工具 Observation 不直接打印到终端，只回喂模型。

## 3. 模型网关

### LiteLLM

- `baicode.llm.chat()` 统一封装模型调用，底层 `litellm.completion(..., stream=False)`。
- 对上层返回稳定 dict：`role`、`content`、`tool_calls`、`reasoning_content`。
- 保留 `reasoning_content` 是为了兼容 DeepSeek thinking-mode 多轮回传要求。
- 异常分为：
  - `FatalAuthError`：鉴权失败，CLI 直接退出。
  - `ChatError`：限流、网络、普通模型错误，CLI 提示后保留 REPL。

## 4. 工作流引擎

### LangGraph

当前实现是双层图：

- **Macro graph**：Planner / React / Executor / Replanner / Finalizer。
- **Micro graph**：手写 ReAct + Reflection，节点为 `agent_node` 和 `tool_node`。

实现约束：

- 使用 OpenAI function calling schema，不做正则解析。
- 禁用 LangGraph prebuilt `ToolNode` / `create_react_agent`，工具分发由 `graph/nodes.py` 手写。
- 0/1 step 请求走 `react_node`，保留单步任务的简洁 UX。
- 2+ step 请求走 Plan-and-Execute，失败时由 Replanner 插入补救步骤或 abort。

## 5. 内置工具

### `python_exec`

- 位置：`src/baicode/tools/python_exec.py`
- 实现：标准库 `subprocess.run([sys.executable, ".workspace/temp_exec.py"], ...)`
- 超时：10s
- 运行目录：用户启动 `baicode` 的当前目录
- 临时文件：`.workspace/temp_exec.py` 覆盖写

### `shell_exec`

- 位置：`src/baicode/tools/shell_exec.py`
- 实现：标准库 `subprocess.run(command, shell=True, ...)`
- Unix/macOS 默认通过系统 shell（通常 `/bin/sh`），Windows 默认通过 `cmd.exe`。
- 超时：60s
- stdout / stderr：各自最多 4000 字符，超长保留头 2000 + 截断标记 + 尾 2000。
- 每次调用都是独立子进程，无持久 CWD；目录切换必须写在同一条命令里，例如 `cd foo && ls`。
- 非 0 returncode 不自动算工具失败，只有超时 `returncode == -1` 或 Python 层异常才触发反思计数。

### `web_search`

- 位置：`src/baicode/tools/web_search.py`
- 实现：`tavily-python`
- 返回：Top-5 URL + cleaned content，整体 4000 字符截断。
- `topic="news"` 时传递 Tavily 的 `topic` / `days` 参数，用于时效查询。
- 明确不是天气、股价、航班、比分、实时卫星图像等结构化实时数据 API。

## 6. 测试与评测

- 当前没有 pytest 套件。
- `eval_runner.py` 是真实 LLM 自动评测脚本，会调用 DeepSeek API 并产生本地副作用清理。
- `memory-bank/eval.md` 记录评测 case、最近一次完整自动化结果、手测项和已知抖动。

## 7. 暂未引入的技术

- Docker / 容器沙箱：当前工具继承调用方权限。
- 真流式模型输出：通信层仍是 `stream=False`，UI 层伪流式。
- 多模型分工：Planner / Executor / Replanner / Finalizer 共用同一默认模型。
- YAML / 全局配置文件：当前仅 `.env`。
