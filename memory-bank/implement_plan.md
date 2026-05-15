# 实施计划：CLI AI Coding Agent (MVP 版本)

> 本文是落地执行手册。0 节为全局约定（**所有 Step 共用，遇歧义以此为准**），其后按阶段展开具体步骤。

---

## 0. 全局决策与约定

### 0.1 项目目录结构（采用 `src/` 隔离布局）

```
myagent/
├── .env                          # 各类 API Key（不入库）
├── .gitignore
├── pyproject.toml                # 包元信息 + 入口脚本 cagent
├── memory-bank/                  # 文档
└── src/
    └── cagent/
        ├── __init__.py
        ├── cli.py                # REPL 入口、prompt_toolkit、顶层 Ctrl+C
        ├── config.py             # .env 配置加载
        ├── llm.py                # LiteLLM 网关
        ├── tools/
        │   ├── __init__.py
        │   ├── python_exec.py    # subprocess Python 执行器
        │   ├── web_search.py     # Tavily 网络搜索
        │   └── schemas.py        # OpenAI tools schema 定义
        └── graph/
            ├── __init__.py
            ├── state.py          # AgentState (TypedDict)
            ├── nodes.py          # agent_node / tool_node
            └── builder.py        # 图构建与条件边
```

### 0.2 关键技术决策

| 维度 | 决策 |
| --- | --- |
| Tool Calling 通信协议 | LiteLLM 透传 **OpenAI 原生 function calling**（tools schema），**不写正则解析** |
| LangGraph 实现方式 | **手写** `agent_node` / `tool_node` + 条件边；**禁用** `create_react_agent`、`ToolNode` |
| 默认模型 | `deepseek/deepseek-chat` |
| 配置来源 | 仅 `.env`，**不支持 YAML** |
| Key 范围 | `DEEPSEEK_API_KEY`、`TAVILY_API_KEY`（必需）；`OPENAI_API_KEY`（可选兜底） |
| 反思上限 | `max_retries = 3`，超限抛异常并退回 REPL |
| Plan-and-Execute | **MVP 推迟**，本期只做 ReAct 单步推理闭环 |
| 流式策略 | LiteLLM 端 `stream=False`；UI 层用 Rich **伪流式打字机**渲染最终回复 |
| CLI 入口命令名 | `cagent` |
| 测试方式 | **MVP 不写 pytest**，全部通过启动 CLI 手动验证边界 |

### 0.3 AgentState 数据结构

```python
from typing import TypedDict

class AgentState(TypedDict):
    messages: list      # 完整消息序列（含 assistant.tool_calls 与 role="tool" 结果）
    error_count: int    # 当前任务内累计的工具执行失败次数
    retry_limit: int    # 常量 3，由入口初始化注入
```

### 0.4 终端颜色与状态渲染规范（Rich）

| 角色 | 颜色 / 样式 | 行为 |
| --- | --- | --- |
| 用户输入 | 默认白色 | prompt_toolkit 原生 |
| Thought（模型思考） | `dim cyan` | 暗青色 |
| Action（工具调用） | `yellow` | Rich `Console.status` Spinner |
| Observation（工具返回） | — | **后台静默，不在终端打印**，只回喂模型 |
| Response（最终回复） | `green` | 伪流式打字机渲染 |

### 0.5 Ctrl+C 分级中断策略

- **REPL 顶层**：捕获 `KeyboardInterrupt` → 打印告别语，干净退出进程。
- **工具执行期间**：`tool_node` 内层 `try/except KeyboardInterrupt`：先终止子进程，再把 `"Tool execution interrupted by user"` 包装成 Observation 回喂 agent_node，**进程与 REPL 保持存活**。

---

## 阶段一：CLI 基建与网关打通 (Milestone 1)

这一阶段的核心是搭建终端骨架，并确保大模型通信链路无阻。

### Step 1: 环境初始化与配置加载

- **指令**：
  - 创建 Python 3.10+ 虚拟环境，初始化 `pyproject.toml`（包名 `cagent`，采用 §0.1 的 src 布局）。
  - 引入 `python-dotenv`，在 `src/cagent/config.py` 实现 `load_config()`：读取 `.env` 中的 `DEEPSEEK_API_KEY`、`TAVILY_API_KEY`（必需），`OPENAI_API_KEY`（可选）。
  - 任一必需 Key 缺失时抛出自定义异常 `MissingAPIKeyError`，错误信息明确指出缺哪个 Key。
- **测试**：
  - 构造完整 `.env`，断言 `load_config()` 正常返回。
  - 删除某个必需 Key，断言抛出 `MissingAPIKeyError` 且信息可读。

### Step 2: 构建 REPL 基础交互循环

- **指令**：
  - 在 `src/cagent/cli.py` 用 `prompt_toolkit` 构建持续监听的无限循环。
  - **多行输入**：`multiline=True`，提交快捷键绑定 **`Alt+Enter` (Meta+Enter)**。
  - **历史持久化**：`FileHistory("~/.cagent_history")`，支持方向键上下翻历史。
  - 顶层捕获 `KeyboardInterrupt`，打印优雅退出提示后结束进程，**不允许堆栈外泄**。
- **测试**：
  - 单行输入回显正常。
  - 粘贴多行文本块，按 Alt+Enter 一次性提交。
  - 按 Ctrl+C，验证仅看到退出提示，无 traceback。
  - 重启 CLI，验证上下方向键可调出上次历史。

### Step 3: 接入多模型调用层（伪流式渲染）

- **指令**：
  - 在 `src/cagent/llm.py` 封装 `chat(messages: list, tools: list | None = None) -> dict`，底层调用：
    ```python
    litellm.completion(model="deepseek/deepseek-chat", messages=..., tools=..., stream=False)
    ```
  - **不在通信层流式**，而是把返回的完整 assistant 文本交给 UI 层，用 Rich 的 `Live` 逐字符渲染（颜色按 §0.4 中 `green`）。
  - 集中异常分类：
    - 限流（`RateLimitError`）：退避后允许重试 1 次，仍失败则向 REPL 报错。
    - 网络瞬时错误：提示用户重试。
    - 鉴权失败：致命错误，安全退出整个进程。
- **测试**：
  - 输入简单问候语，验证 `green` 文本逐字渲染。
  - 把 `DEEPSEEK_API_KEY` 改成错值，验证触发鉴权致命错误并退出。

---

## 阶段二：工具层原子化抽象 (Milestone 2 铺垫)

将 Agent 与外界交互的"手脚"封装为纯净、无状态的原子工具。

### Step 4: 实现 Python 原生执行器工具

- **指令**：
  - `src/cagent/tools/python_exec.py` 暴露 `run_python(code: str) -> dict`。
  - 在项目根目录隐式创建 `.workspace/`，每次将代码**覆盖写入** `.workspace/temp_exec.py`（不主动清理，便于事后查验）。
  - 用 `subprocess.run([sys.executable, ".workspace/temp_exec.py"], capture_output=True, text=True, timeout=10)` 在**当前激活 venv** 中执行。
  - 返回 `{"stdout": str, "stderr": str, "returncode": int}`；超时时 `stderr` 显式标注 `"TIMEOUT after 10s"`。
  - 在 `tools/schemas.py` 暴露对应的 OpenAI tools schema（参数 `code: string`）。
- **测试**：
  - 传入 `print("hi")`，断言 `stdout == "hi\n"`、`returncode == 0`。
  - 传入带 `NameError` 的代码，断言函数不崩溃且 `stderr` 含 traceback。
  - 传入 `while True: pass`，断言 10 秒后返回 `TIMEOUT` 标记。

### Step 5: 实现 Web 搜索工具

- **指令**：
  - `src/cagent/tools/web_search.py` 暴露 `web_search(query: str) -> str`。
  - 调用 `tavily-python`，提取 **Top-3** 结果，每条按 `"[url]\ncontent\n"` 拼接，**整体施加 4000 字符硬截断**保护上下文。
  - 在 `tools/schemas.py` 暴露 OpenAI tools schema（参数 `query: string`）。
- **测试**：
  - 查询当日时效新闻，断言返回字符串含预期关键词、不超过 4000 字符。

---

## 阶段三：工作流状态机编排 (Milestone 2 & 3)

利用图结构串联前面的组件，构建带有 ReAct 和反思机制的大脑。

### Step 6: 定义状态图结构与基础节点

- **指令**：
  - `src/cagent/graph/state.py` 落地 §0.3 的 `AgentState`。
  - `src/cagent/graph/nodes.py` 实现 `agent_node`：调用 `llm.chat(messages, tools=[python_exec_schema, web_search_schema])`，将返回 assistant message 追加到 `messages`，回写新 state。
  - `src/cagent/graph/builder.py` 构建最小图：`START → agent_node → END`，预留条件边接口供 Step 7 接入。
- **测试**：
  - 通过起始点传入一条测试消息，验证图能完整走通并在终端获得最终回复（颜色按 §0.4）。

### Step 7: 闭环 ReAct 逻辑与 Tool 节点集成

- **指令**：
  - 在 `nodes.py` 新增 `tool_node`：从 `messages[-1].tool_calls` 中解析 `name` 与 `arguments`，分发到 `python_exec` 或 `web_search`，结果以 `role="tool"` 消息回填 `messages`。
  - 进入 `tool_node` 时用 `Console.status("Running tool...", spinner="dots", style="yellow")` 渲染加载动画（颜色见 §0.4）。
  - **工具结果不直接打印到终端**（保持 Observation 静默），仅作为消息回喂模型。
  - 条件边：
    - `messages[-1].tool_calls` 非空 → 路由到 `tool_node`，执行完转回 `agent_node`。
    - 否则 → `END`。
- **测试**：
  - 输入"计算 1234567 × 7654321"。预期看到 yellow Spinner → 工具节点执行 → 回到 agent_node → 终端 green 输出最终结果。

### Step 8: 实现错误反思与自愈循环 (Reflection)

- **指令**：
  - 修改 `tool_node`：检测到 `python_exec` 返回的 `stderr` 非空时，把 `stderr` + 原代码包装为特定格式的 `role="tool"` 消息，**并将 `state["error_count"] += 1`**。
  - 条件边追加判断：若 `error_count >= retry_limit (=3)`，直接路由到 `END` 并抛出 `RuntimeError("Reflection retries exceeded")`，REPL 捕获后提示用户、回到输入提示符。
  - **Ctrl+C 工具内层中断**（落实 §0.5）：`tool_node` 包一层 `try/except KeyboardInterrupt`，先 `subprocess.kill()`，再构造一条 `"Tool execution interrupted by user"` 的 Observation 喂回 agent_node，**REPL 不退出**。
- **测试**：
  - 输入"写一段含除零错误的 Python 代码并运行"。验证：第一次失败 → agent 重写 → 第二次（或第三次）内成功并输出。
  - 强制让代码连续失败 3 次，验证第 4 次循环被中断，REPL 提示 "Reflection retries exceeded"。
  - Spinner 显示时按 Ctrl+C：验证子进程被杀、REPL 仍存活、模型收到中断 Observation 后给出回应。

---

## 阶段四：产品化封装

将跑通的核心逻辑转化为开箱即用的命令行工具。

### Step 9: 全局 CLI 命令打包部署

- **指令**：
  - 在 `pyproject.toml` 中配置入口脚本：
    ```toml
    [project.scripts]
    cagent = "cagent.cli:main"
    ```
  - `cli.py` 的 `main()` 使用 `Typer` 注册为默认命令（无子命令时直接进入 REPL）。
  - 在开发环境执行 `pip install -e .` 完成可编辑安装。
- **测试**：
  - 开启新独立终端，键入 `cagent`，断言瞬间进入 REPL。
  - 在新终端中完整跑一遍 ReAct 流程（含工具调用 + 反思）。

---

## 附录 A：贯穿所有 Step 的手动验证清单

| # | 场景 | 期望结果 |
| --- | --- | --- |
| 1 | 错误 API Key 启动 | 鉴权致命错误，进程优雅退出 |
| 2 | 断网状态下输入指令 | 模型层报网络错误，REPL 存活 |
| 3 | REPL 输入态按 Ctrl+C | 打印退出提示，干净结束 |
| 4 | 工具执行态按 Ctrl+C | 子进程被杀、REPL 存活、模型收到中断 Observation |
| 5 | 连续 3 次工具失败 | 第 4 次循环被强制中断，提示 "Reflection retries exceeded" |
| 6 | 新终端键入 `cagent` | 行为与 `python -m cagent.cli` 完全一致 |

## 附录 B：MVP 明确不做的事

- Plan-and-Execute 多步规划（延后到下一里程碑）。
- pytest 自动化测试套件（仅手动验证）。
- YAML / 全局 `~/.config/agent/config.yaml`（仅 `.env`）。
- 流式 tool_call chunk 解析（统一 `stream=False`）。
- 工具结果在终端的可视化打印（Observation 全程静默）。
- Docker / 沙箱隔离（直接复用当前 venv）。
