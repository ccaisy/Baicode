# 架构与文件职责 (Architecture)

本文档**逐文件**说明每个文件的角色、关键导出、依赖方向。Phase 演进时持续增补；后人改动 src 时请同步更新本文件。

---

## 1. 仓库根目录

| 路径 | 作用 |
| --- | --- |
| `pyproject.toml` | 包元信息（name=`cagent`、`requires-python>=3.10`）、依赖（`python-dotenv` / `prompt_toolkit` / `rich` / `litellm` / `tavily-python` / `langgraph`）、`[project.scripts] cagent = "cagent.cli:main"` 入口、`tool.setuptools.packages.find` 配 src 布局 |
| `.env` | 本地真实 Key（**已 .gitignore**） |
| `.env.example` | 配置模板，列出 `DEEPSEEK_API_KEY` / `TAVILY_API_KEY` / `OPENAI_API_KEY` |
| `.gitignore` | macOS / Python 工件 + `.env` + `.workspace/`（Phase 2 工具执行临时区） |
| `memory-bank/` | 项目文档：PRD、技术栈、implement_plan、progress（进度日志）、architecture（本文件） |
| `.venv/` | 开发环境 venv（**已 .gitignore**） |
| `src/cagent/` | 包代码主体，详见 §2 |

---

## 2. `src/cagent/` 包内文件

### 2.1 `__init__.py`

仅暴露 `__version__ = "0.1.0"`。**不引入任何运行时模块**，确保 `import cagent` 零副作用、零开销。

---

### 2.2 `config.py` — 配置加载层

**角色**：把 `.env` 中的散乱字符串收敛为强类型 `Config` 对象，并校验必需 Key。

#### config.py 关键导出

| 名字 | 类型 | 作用 |
| --- | --- | --- |
| `DEFAULT_MODEL` | `str` 常量 | `"deepseek/deepseek-v4-flash"`（thinking-mode；详见 progress 偏离 3） |
| `Config` | `@dataclass(frozen=True)` | 不可变配置容器；字段 `deepseek_api_key` / `tavily_api_key` / `openai_api_key` / `default_model` |
| `MissingAPIKeyError` | `Exception` 子类 | 携带 `.key_name` 字段，方便上层差异化提示 |
| `load_config()` | `() -> Config` | 调 `dotenv.find_dotenv(usecwd=True)` 从 CWD 向上递归找 `.env`；缺必需 Key 立即抛异常 |

#### config.py 依赖关系

- 上游依赖：`python-dotenv`。
- 被谁调：`cli.py` 启动时调一次；`llm.py::chat()` 在 `config=None` 时调一次。

---

### 2.3 `llm.py` — 大模型网关层

**角色**：屏蔽 LiteLLM 的供应商差异和异常多样性，对上层暴露稳定接口 `chat()` + 二元异常体系（`ChatError` 可恢复 / `FatalAuthError` 不可恢复）。

#### llm.py 关键导出

| 名字 | 签名 / 类型 | 作用 |
| --- | --- | --- |
| `ChatError` | `Exception` | **可恢复**：限流耗尽、网络瞬时、通用错误。上层捕获后 REPL 继续 |
| `FatalAuthError` | `Exception` | **不可恢复**：鉴权失败。上层 `sys.exit(1)` |
| `chat(messages, config=None, tools=None) -> dict` | 单次模型调用 | 返回 `{"role": "assistant", "content": str, "tool_calls": Optional[list], "reasoning_content": Optional[str]}`。**`reasoning_content` 是 thinking-mode 模型的链式思考；多轮调用必须回传，否则 DeepSeek 报 BadRequest（progress 偏离 3）。非推理模型该字段为 `None`** |
| `_looks_like_auth_error(exc)` | 私有 helper | 关键字嗅探兜底鉴权错误（DeepSeek 把 401 包成 `BadRequestError` 的边界场景） |

#### llm.py 关键约定

- LiteLLM 通信层统一 `stream=False`，所有流式视觉效果留给 cli.py 层模拟。
- 模块顶部 `os.environ.setdefault("LITELLM_LOG", "ERROR")` + `litellm.suppress_debug_info = True` 抑制 LiteLLM 默认的冗长日志。
- 异常分级矩阵：

| LiteLLM 抛出 | 我方包装 |
| --- | --- |
| `AuthenticationError` | `FatalAuthError` |
| `RateLimitError`（首次） | 退避 2s 后重试 1 次 |
| `RateLimitError`（重试仍失败） | `ChatError` |
| `APIConnectionError` / `Timeout` | `ChatError` |
| 其他 + 关键字命中鉴权 | `FatalAuthError` |
| 其他 | `ChatError` |

#### llm.py 依赖关系

- 上游依赖：`litellm` + `config.Config / load_config`。
- 被谁调：`cli.py` 主循环；后续 Phase 3 的 `graph/nodes.py::agent_node` 也会调它。

---

### 2.4 `cli.py` — REPL 入口 + 渲染

**角色**：人机交互的唯一入口。同时承载 prompt_toolkit 输入、Rich 渲染、调用链编排、顶层异常处理。

#### cli.py 关键导出

| 名字 | 签名 | 作用 |
| --- | --- | --- |
| `main()` | `() -> None` | `pyproject.toml [project.scripts] cagent` 注册的入口函数 |
| `render_typewriter(text, console, style, delay)` | 渲染器 | 用 Rich `Live + Text` 模拟逐字打字机。`Text.append(ch)` 而不是 markup，**避免被用户/模型字串里的方括号注入** |
| `_SYSTEM_PROMPT_TEMPLATE` / `_build_system_prompt()` | `str` / `() -> str` | 模板含 `{today}` 占位符；启动时 `date.today().isoformat()` 注入（每次 `cagent` 启动重算，**明年用是明年的日期**）。模板内嵌：禁止使用训练记忆中具体日期/数字；`web_search` 不是结构化数据 API（天气/股价/航班/汇率遇到直接告知能力受限）；工具调用预算 5 次用完就停 |
| `HISTORY_PATH` | `str` 常量 | `~/.cagent_history` |

#### cli.py 启动流程

1. 创建 `rich.console.Console`。
2. `sys.stdin.isatty()` 守卫 — 非 TTY 直接红字退出。
3. `load_config()` — 缺 Key 走 `MissingAPIKeyError` 红字退出。
4. 打印 banner（model 名 + 操作提示）。
5. 创建 `PromptSession(multiline=True, history=FileHistory(HISTORY_PATH))`。
6. 初始化 `messages = [{"role": "system", "content": _build_system_prompt()}]`。
7. 进入 `while True` 主循环。

#### cli.py 主循环单步

```text
user_input  ──► strip / 空串跳过
            ──► messages.append({"role": "user", ...})
            ──► graph.builder.run(messages)         # Phase 3 起：整张状态机
            ──► messages = updated_messages          # 用图返回的完整序列覆盖
            ──► render_typewriter(last.content, style="green")
```

`thinking...` (dim cyan) 与 `Running tool...` (yellow) 两个 Spinner 都已迁入 `graph/nodes.py` 内部，cli 端不再持有。

#### cli.py 异常处理矩阵

| 异常 | 行为 |
| --- | --- |
| 顶层 `KeyboardInterrupt` / `EOFError` | 打印"再见。" + `return` |
| `FatalAuthError` | 红字 + `sys.exit(1)` |
| `ChatError` | 红字提示 + `messages.pop()`（弹 user 保持序列洁净）+ `continue` |
| `ReflectionRetriesExceeded` | 红字 + `messages.pop()` + `continue`（工具失败 ≥ retry_limit） |
| `ToolCallBudgetExceeded` | 红字 + `messages.pop()` + `continue`（工具调用 ≥ max_tool_calls 仍想调） |
| 图执行期间 `KeyboardInterrupt` | 红字 + `messages.pop()` + `continue` |
| 渲染期间 `KeyboardInterrupt` | 仅打一个换行收尾 |

#### cli.py 颜色规范（落实 implement_plan §0.4）

| 角色 | 颜色 |
| --- | --- |
| Banner / 用户输入 | 默认白 |
| Thought Spinner | `dim cyan` |
| Action Spinner（Phase 2 接入工具时） | `yellow` |
| 最终回复 | `green` 打字机 |
| 异常提示 | `red` |

#### cli.py 依赖关系

- 上游依赖：`prompt_toolkit` + `rich` + `datetime` + `config` + `llm` + `graph.builder`。
- 被谁调：`pyproject.toml` 的 `cagent` 入口、`python -m cagent.cli`。

---

### 2.5 `tools/__init__.py`

包占位，**不导出任何符号**。Phase 3 的 `graph/nodes.py` 直接 `from cagent.tools.python_exec import run_python` / `from cagent.tools.web_search import web_search` 引用。

---

### 2.6 `tools/python_exec.py` — 本地 Python 子进程执行器

**角色**：把 LLM 生成的代码字符串落地为脚本文件、用当前 venv 的 Python 子进程跑、把 stdout/stderr/returncode 三元组回传给上层。**纯净、无状态**。

#### python_exec.py 关键导出

| 名字 | 类型 | 作用 |
| --- | --- | --- |
| `TIMEOUT_SECONDS` | `int = 10` | 单次执行硬上限 |
| `WORKSPACE_DIR` | `Path(".workspace")` | 相对 CWD，首次调用时 `mkdir(exist_ok=True)` |
| `TEMP_SCRIPT` | `Path(".workspace/temp_exec.py")` | **覆盖写**，不主动清理 |
| `run_python(code) -> dict` | 单次执行入口 | 返回 `{"stdout": str, "stderr": str, "returncode": int}` |

#### python_exec.py 行为约定

- 执行命令：`subprocess.run([sys.executable, ".workspace/temp_exec.py"], capture_output=True, text=True, timeout=10)`。
- 子进程沿用调用方的 CWD（即用户启动 `cagent` 的目录）。
- 超时分支：捕获 `subprocess.TimeoutExpired`，`stderr` 末尾追加 `"TIMEOUT after 10s"`、`returncode = -1`。已捕获到的部分 stdout/stderr 会保留前缀。
- **MVP 不做沙箱**：直接复用当前 venv，权限继承调用方。
- Phase 3 的 `tool_node` Ctrl+C 中断策略（implement_plan §0.5）将在节点层包一层 `try/except KeyboardInterrupt`，**本文件不实现**。

#### python_exec.py 依赖关系

- 上游依赖：仅 Python 标准库 `subprocess` / `sys` / `pathlib`。
- 被谁调：Phase 3 `graph/nodes.py::tool_node`。

---

### 2.7 `tools/web_search.py` — Tavily 网络搜索

**角色**：用 Tavily 拉取 Top-5 高相关结果，拼成单一字符串回传。**纯净、无状态**。

#### web_search.py 关键导出

| 名字 | 类型 | 作用 |
| --- | --- | --- |
| `MAX_CHARS` | `int = 4000` | 输出硬截断阈值，护栏 LLM 上下文 |
| `TOP_K` | `int = 5` | Tavily `max_results` |
| `web_search(query, topic="general", days=30) -> str` | 单次搜索入口 | 返回 `"[url] (published_date)\ncontent\n..."` 形式字符串，整体 ≤ 4000 字符 |

#### web_search.py 行为约定

- 每次调用 `load_config()` 拿 `TAVILY_API_KEY`，新建 `TavilyClient(api_key=...)`。MVP 阶段调用频率低、不做 client 缓存。
- **`topic="news"` 时才传 Tavily 的 `topic` + `days` 字段**；默认 `general` 适用 docs/wiki/技术内容。schema 让模型自己选（progress 偏离 4）。
- Tavily 异常**未做包装**，直接冒泡到 `tool_node`，由节点层 `except Exception` 兜底（`error_count++`）。
- 截断采用朴素 `text[:MAX_CHARS]`，可能切在 UTF-8 字符中——MVP 风险可接受。

#### web_search.py 依赖关系

- 上游依赖：`tavily` (`tavily-python` 包) + `cagent.config.load_config`。
- 被谁调：`graph/nodes.py::tool_node`。

---

### 2.8 `tools/schemas.py` — OpenAI function schema 集中定义

**角色**：给 Phase 3 `agent_node` 一次性传给 `llm.chat(messages, tools=ALL_SCHEMAS)`，避免 schema 散落在各工具实现里。

#### schemas.py 关键导出

| 名字 | 类型 | 作用 |
| --- | --- | --- |
| `PYTHON_EXEC_SCHEMA` | `dict` | OpenAI function calling schema，`function.name="python_exec"`，参数 `code: string (required)` |
| `WEB_SEARCH_SCHEMA` | `dict` | `function.name="web_search"`，参数 `query: string (required)` + `topic: enum["general","news"]` + `days: integer`。description 中明令"时效问题 MUST set topic='news'" |
| `ALL_SCHEMAS` | `list[dict]` | `[PYTHON_EXEC_SCHEMA, WEB_SEARCH_SCHEMA]` |

#### schemas.py 行为约定

- description 字段已写明用途、超时、截断等关键约束，引导模型合理选择工具。
- 字段名（`python_exec` / `web_search` / `code` / `query`）必须与工具函数签名 1:1 对应；Phase 3 `tool_node` 按这些字符串做分发。

#### schemas.py 依赖关系

- 上游依赖：无（纯数据）。
- 被谁调：Phase 3 `graph/nodes.py::agent_node` 调 `llm.chat(tools=ALL_SCHEMAS)`。

---

### 2.9 `graph/__init__.py`

包占位，不导出符号。

---

### 2.10 `graph/state.py` — AgentState 定义

**角色**：LangGraph 节点间流转的 `TypedDict`。

| 字段 | 类型 | 由谁初始化 | 含义 |
| --- | --- | --- | --- |
| `messages` | `list` | `builder.run` | 完整对话序列（含 assistant.tool_calls / role="tool" 结果 / reasoning_content） |
| `error_count` | `int` | `builder.run`（=0） | 当轮 user 内累计的工具失败次数（仅在 `python_exec.stderr` 非空 / tool 抛异常时 ++） |
| `retry_limit` | `int` | `builder.run`（=3） | `error_count >= retry_limit` → `ReflectionRetriesExceeded` |
| `tool_calls_count` | `int` | `builder.run`（=0） | 当轮 user 内 `tool_node` 被调用的总次数（按节点 +1，不按子调用） |
| `max_tool_calls` | `int` | `builder.run`（=5） | `tool_calls_count >= max_tool_calls` 且模型仍想调工具 → `ToolCallBudgetExceeded` |

---

### 2.11 `graph/nodes.py` — agent_node + tool_node（手写 ReAct + Reflection）

#### nodes.py 关键导出

| 名字 | 签名 | 作用 |
| --- | --- | --- |
| `agent_node(state) -> dict` | LangGraph 节点 | `Console.status("thinking...", style=dim cyan)` + `chat(messages, tools=ALL_SCHEMAS)` → assistant message（含 `reasoning_content` / `tool_calls` 时一并写入） |
| `tool_node(state) -> dict` | LangGraph 节点 | `Console.status("Running tool...", style=yellow)` + 按 `function.name` 分发 `python_exec` / `web_search`；Observation 静默；`tool_calls_count` 末尾 +1 |
| `_normalize_tool_calls(tool_calls)` | 私有 helper | 把 LiteLLM 的 pydantic `ChatCompletionMessageToolCall` 列表转成 dict 列表，**确保下次调用 LiteLLM 时格式合法** |

#### nodes.py 行为约定

- `python_exec`：`stderr` 非空 → `error_count++` + content 用反思格式（`Execution failed (returncode=...).\nCode:\n\`\`\`python\n{code}\n\`\`\`\nStderr:\n...\nStdout:\n...`）。
- `web_search`：把 `args.get("topic", "general")` 与 `args.get("days", 30)` 透传给工具函数；异常不走反思（直接 `except Exception` → `error_count++`）。
- JSON 解析失败：`json.JSONDecodeError` → `error_count++` + 回填错误提示，**不中断循环**（多 tool_call 场景仍能处理后续调用）。
- `KeyboardInterrupt`（implement_plan §0.5 落实点）：当前 tool_call 回填 `"Tool execution interrupted by user."`；后续所有 tool_call 回填 `"Tool execution skipped due to earlier interrupt."`；`break` 跳出循环；**不冒泡，REPL 保持存活**。子进程的 kill 由 `subprocess.run` 自身完成。
- 模块顶部 `_console = Console()` 单例；与 `cli.py` 的 Console 不同实例但同写 stdout，Rich 内部安全。

#### nodes.py 依赖关系

- 上游依赖：`rich.console.Console` + `cagent.llm.chat` + `cagent.tools.{python_exec, web_search, schemas}`。
- 被谁调：`graph.builder.build_graph()` 注册为 `"agent"` / `"tool"` 节点。

---

### 2.12 `graph/builder.py` — 图构建 + 条件边路由 + REPL 入口

#### builder.py 关键导出

| 名字 | 类型 / 签名 | 作用 |
| --- | --- | --- |
| `ReflectionRetriesExceeded` | `RuntimeError` 子类 | 工具失败 ≥ `retry_limit` |
| `ToolCallBudgetExceeded` | `RuntimeError` 子类 | 工具调用 ≥ `max_tool_calls` 且模型仍想调 |
| `build_graph()` | `() -> CompiledGraph` | 装 `START → agent` + 两组条件边；模块外**不需要**自己持有图实例（`run()` 内部每次新建，开销小） |
| `run(messages, retry_limit=3, max_tool_calls=5)` | REPL 入口 | 执行整张图、检查 final state、抛超限异常或返回完整 messages |

#### builder.py 图结构

```text
START ──► agent ──┬──► tool ──┬──► agent      (常规 ReAct 回路)
                  │            └──► END       (error_count ≥ retry_limit → exceeded)
                  ├──► END                    (last 无 tool_calls → 自然收尾)
                  └──► END                    (last 有 tool_calls 但 tool_calls_count ≥ max → exceeded)
```

- 路由函数 `_route_after_agent` 返回 `"tool"` / `"end"` / `"exceeded"`；`_route_after_tool` 返回 `"agent"` / `"exceeded"`；`"exceeded"` 与 `"end"` 都映射到 `END`，由 `run()` 事后检查 state 区分。
- `_RECURSION_LIMIT = 50` 防止 LangGraph 死循环兜底；正常情况下 `retry_limit` / `max_tool_calls` 会先触发。

#### builder.py 依赖关系

- 上游依赖：`langgraph.graph.StateGraph` + `cagent.graph.{nodes, state}`。
- 被谁调：`cli.py::main()` 主循环。

---

## 3. 运行时产物（**不入库**）

| 路径 | 何时创建 | 用途 |
| --- | --- | --- |
| `~/.cagent_history` | REPL 启动时 prompt_toolkit 自动创建 | 跨会话方向键历史 |
| `.workspace/` | `tools.python_exec.run_python` 首次调用时 `mkdir(exist_ok=True)` | 工具执行临时区，相对 CWD |
| `.workspace/temp_exec.py` | 同上，每次 `run_python` **覆盖写** | Python 执行器临时代码文件，不主动清理（事后查验） |
| `.venv/` | 开发者 `python -m venv .venv` 后 | 开发环境 |

---

## 4. 调用方向（依赖图）

```text
                ┌──────────────┐
                │  cli.main()  │  入口
                └──────┬───────┘
                       │ messages.append(user)
                       ▼
              graph.builder.run(messages, retry_limit=3, max_tool_calls=5)
                       │
                       ▼
          ┌─────────  StateGraph  ─────────┐
          │                                 │
          ▼                                 ▼
   agent_node (chat + tools=ALL_SCHEMAS)    tool_node (python_exec | web_search)
          │                                 │
          ▼                                 ▼
        llm.chat                       tools.python_exec.run_python
       (litellm)                       tools.web_search.web_search
                                       (tavily-python + config.load_config)

                       │ updated_messages
                       ▼
              cli.render_typewriter (rich Live + Text)
```

- **单向依赖、无环**。
- `cli` 持有 `messages` 主权，每轮 user 后调 `graph_run` 拿回完整序列并覆盖。
- `prompt_toolkit` / `rich` / `litellm` / `tavily` / `langgraph` 均为叶子依赖。
- Phase 2 工具层 + Phase 3 图层闭环：`cli.main → graph.builder.run → graph.nodes.{agent,tool}_node → llm.chat / tools.*`。

---

## 5. 待添加文件

Phase 1-3 落地后，**implement_plan §0.1 列出的所有源码文件均已就位**。Phase 4 仅做产品化封装（`pip install -e .` 已可用、`pyproject.toml [project.scripts]` 已注册），不引入新代码文件。
