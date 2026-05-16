# 架构与文件职责 (Architecture)

本文档**逐文件**说明每个文件的角色、关键导出、依赖方向。Phase 演进时持续增补；后人改动 src 时请同步更新本文件。

---

## 1. 仓库根目录

| 路径 | 作用 |
| --- | --- |
| `pyproject.toml` | 包元信息（name=`baicode`、`requires-python>=3.10`）、依赖（`python-dotenv` / `prompt_toolkit` / `rich` / `litellm` / `tavily-python` / `langgraph`）、`[project.scripts] baicode = "baicode.cli:main"` 入口、`tool.setuptools.packages.find` 配 src 布局 |
| `.env` | 本地真实 Key（**已 .gitignore**） |
| `.env.example` | 配置模板，列出 `DEEPSEEK_API_KEY` / `TAVILY_API_KEY` / `OPENAI_API_KEY` |
| `.gitignore` | macOS / Python 工件 + `.env` + `.workspace/`（Phase 2 工具执行临时区） |
| `memory-bank/` | 项目文档：PRD、技术栈、implement_plan、progress（进度日志）、architecture（本文件） |
| `.venv/` | 开发环境 venv（**已 .gitignore**） |
| `src/baicode/` | 包代码主体，详见 §2 |

---

## 2. `src/baicode/` 包内文件

### 2.1 `__init__.py`

仅暴露 `__version__ = "0.1.0"`。**不引入任何运行时模块**，确保 `import baicode` 零副作用、零开销。

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
| `main()` | `() -> None` | `pyproject.toml [project.scripts] baicode` 注册的入口函数 |
| `render_typewriter(text, console, style=None, delay=0.005)` | 渲染器 | 流式 Markdown 渲染器：`rich.markdown.Markdown(buf, code_theme="monokai")` + `Live.update`。字符级 `time.sleep(delay)` 维持打字机节奏，但 `live.update` **只在换行符或末尾字符触发**（Phase 5 Step 12 方案 B 节流）。`style` 形参降级为 fallback hook（Phase 5 起不再强制染色，Markdown 自身样式优先） |
| `_SYSTEM_PROMPT_TEMPLATE` / `_build_system_prompt()` | `str` / `() -> str` | 模板含 `{today}` 占位符；启动时 `date.today().isoformat()` 注入（每次 `baicode` 启动重算，**明年用是明年的日期**）。模板内嵌：禁止使用训练记忆中具体日期/数字；`web_search` 不是结构化数据 API（天气/股价/航班/汇率遇到直接告知能力受限）；工具调用预算 5 次用完就停；**Phase 5 起**：模型输出代码必须使用带语言标注的围栏代码块以便 CLI 语法高亮；**Phase 6 起**：在工具清单中新增 `shell_exec` 段落，硬约束 cd 必须用 `&&` 串联（每次 shell 调用是独立子进程、无持久 CWD） + 禁交互式命令（vim/nano/less/more/top/htop/ssh-without-BatchMode） + 安装/包管理类命令必须非交互（`-y` / `--yes` / `--quiet` / `DEBIAN_FRONTEND=noninteractive`） |
| `HISTORY_PATH` | `str` 常量 | `~/.baicode_history` |

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

#### cli.py 颜色规范（Phase 5 起覆盖 implement_plan §0.4）

| 角色 | 颜色 |
| --- | --- |
| Banner / 用户输入 | 默认白 |
| Thought Spinner | `dim cyan` |
| Action Spinner（Phase 2 接入工具时） | `yellow` |
| 最终回复 | **Markdown 流式渲染（终端默认色 + 代码块 `monokai` 高亮 + 粗斜体/链接下划线由 Rich 决定）**。原 plan 的"`green` 打字机"已于 Phase 5 废止（progress 偏离 6） |
| 异常提示 | `red` |

#### cli.py 依赖关系

- 上游依赖：`prompt_toolkit` + `rich`（`Console` / `Live` / `Markdown`）+ `datetime` + `config` + `llm` + `graph.builder`。`pygments` 通过 Rich 传递引入，不在 `pyproject.toml` 显式声明。
- 被谁调：`pyproject.toml` 的 `baicode` 入口、`python -m baicode.cli`。

---

### 2.5 `tools/__init__.py`

包占位，**不导出任何符号**。Phase 3 的 `graph/nodes.py` 直接 `from baicode.tools.python_exec import run_python` / `from baicode.tools.web_search import web_search` 引用。

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
- 子进程沿用调用方的 CWD（即用户启动 `baicode` 的目录）。
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

- 上游依赖：`tavily` (`tavily-python` 包) + `baicode.config.load_config`。
- 被谁调：`graph/nodes.py::tool_node`。

---

### 2.8 `tools/shell_exec.py` — 本地 Shell 子进程执行器

**角色**：把 LLM 生成的 shell 命令字符串交给 `/bin/sh` 子进程执行，回传 stdout/stderr/returncode 三元组。**纯净、无状态、无持久 CWD**。

#### shell_exec.py 关键导出

| 名字 | 类型 | 作用 |
| --- | --- | --- |
| `TIMEOUT_SECONDS` | `int = 60` | 单次执行硬上限（详见 progress 偏离 8） |
| `MAX_CHARS` | `int = 4000` | stdout / stderr 各自独立的截断阈值 |
| `HEAD_CHARS` / `TAIL_CHARS` | `int = 2000` / `int = 2000` | 超长输出保留的头部与尾部字符数 |
| `_truncate(text)` | 私有 helper | 超长 → `text[:2000] + "\n...[truncated N chars]...\n" + text[-2000:]` |
| `run_shell(command) -> dict` | 单次执行入口 | 返回 `{"stdout": str, "stderr": str, "returncode": int}` |

#### shell_exec.py 行为约定

- 执行命令：`subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)`。**不显式 `executable=` 参数**，沿用系统默认 `/bin/sh`（POSIX shell，`&&` / `|` / `>` 全支持，但 `[[ ]]` / process substitution 等 bash 拓展不支持）。
- **无持久 CWD**：每次调用都是独立子进程，沿用调用方（`baicode` 启动目录）的 CWD；模型需要在同一条 command 内用 `&&` 串联 `cd`，单条 `cd` 无效（system prompt 已硬约束）。
- 超时分支：捕获 `subprocess.TimeoutExpired` → `returncode = -1` + `stderr` 末尾追加 `"TIMEOUT after 60s"`；已捕获到的部分 stdout/stderr 保留并照常截断。bytes 类型的部分输出自动 `decode("utf-8", errors="replace")`。
- 截断策略：stdout 与 stderr **各自独立**应用 `MAX_CHARS = 4000` 上限（详见 progress 偏离 9）。
- **MVP 不做沙箱、不做命令黑名单**：完全信任模型决策，与 python_exec 的策略一致（implement_plan §0.2 / progress Phase 6 决策点）。
- Phase 6 的 `tool_node` Ctrl+C 中断策略 100% 复用既有内层 `try/except KeyboardInterrupt`，**本文件不实现**。

#### shell_exec.py 依赖关系

- 上游依赖：仅 Python 标准库 `subprocess`。
- 被谁调：`graph/nodes.py::tool_node`。

---

### 2.9 `tools/schemas.py` — OpenAI function schema 集中定义

**角色**：给 Phase 3 `agent_node` 一次性传给 `llm.chat(messages, tools=ALL_SCHEMAS)`，避免 schema 散落在各工具实现里。

#### schemas.py 关键导出

| 名字 | 类型 | 作用 |
| --- | --- | --- |
| `PYTHON_EXEC_SCHEMA` | `dict` | OpenAI function calling schema，`function.name="python_exec"`，参数 `code: string (required)` |
| `WEB_SEARCH_SCHEMA` | `dict` | `function.name="web_search"`，参数 `query: string (required)` + `topic: enum["general","news"]` + `days: integer`。description 中明令"时效问题 MUST set topic='news'" |
| `SHELL_EXEC_SCHEMA` | `dict` | `function.name="shell_exec"`，参数 `command: string (required)`。description 内嵌四条约束：60s 超时 / 输出截断 / cd 隔离（每次调用独立子进程） / 禁交互式命令（vim/less/top/ssh-without-BatchMode） + 安装类命令必须非交互（`-y` / `--yes` / `--quiet` / `DEBIAN_FRONTEND=noninteractive`） |
| `ALL_SCHEMAS` | `list[dict]` | `[PYTHON_EXEC_SCHEMA, WEB_SEARCH_SCHEMA, SHELL_EXEC_SCHEMA]` |

#### schemas.py 行为约定

- description 字段已写明用途、超时、截断等关键约束，引导模型合理选择工具。
- 字段名（`python_exec` / `web_search` / `shell_exec` / `code` / `query` / `command`）必须与工具函数签名 1:1 对应；`tool_node` 按这些字符串做分发。

#### schemas.py 依赖关系

- 上游依赖：无（纯数据）。
- 被谁调：Phase 3 `graph/nodes.py::agent_node` 调 `llm.chat(tools=ALL_SCHEMAS)`。

---

### 2.10 `graph/__init__.py`

包占位，不导出符号。

---

### 2.11 `graph/state.py` — AgentState 定义

**角色**：LangGraph 节点间流转的 `TypedDict`。

| 字段 | 类型 | 由谁初始化 | 含义 |
| --- | --- | --- | --- |
| `messages` | `list` | `builder.run` | 完整对话序列（含 assistant.tool_calls / role="tool" 结果 / reasoning_content） |
| `error_count` | `int` | `builder.run`（=0） | 当轮 user 内累计的工具失败次数。触发条件：`python_exec.stderr` 非空 / `shell_exec` **超时**（`returncode == -1`）或抛 Python 异常 / 任何 tool 抛通用异常 / JSON 解析失败 / 未知工具名。**`shell_exec` 的非 0 returncode 不计入**（grep 无匹配 / test 失败这类是正常业务输出） |
| `retry_limit` | `int` | `builder.run`（=3） | `error_count >= retry_limit` → `ReflectionRetriesExceeded` |
| `tool_calls_count` | `int` | `builder.run`（=0） | 当轮 user 内 `tool_node` 被调用的总次数（按节点 +1，不按子调用） |
| `max_tool_calls` | `int` | `builder.run`（=5） | `tool_calls_count >= max_tool_calls` 且模型仍想调工具 → `ToolCallBudgetExceeded` |

---

### 2.12 `graph/nodes.py` — agent_node + tool_node（手写 ReAct + Reflection）

#### nodes.py 关键导出

| 名字 | 签名 | 作用 |
| --- | --- | --- |
| `agent_node(state) -> dict` | LangGraph 节点 | `Console.status("thinking...", style=dim cyan)` + `chat(messages, tools=ALL_SCHEMAS)` → assistant message（含 `reasoning_content` / `tool_calls` 时一并写入） |
| `tool_node(state) -> dict` | LangGraph 节点 | `Console.status("Running tool...", style=yellow)` + 按 `function.name` 分发 `python_exec` / `web_search` / `shell_exec`；Observation 静默；`tool_calls_count` 末尾 +1 |
| `_normalize_tool_calls(tool_calls)` | 私有 helper | 把 LiteLLM 的 pydantic `ChatCompletionMessageToolCall` 列表转成 dict 列表，**确保下次调用 LiteLLM 时格式合法** |
| `_format_python_failure` / `_format_python_success` | 私有 helper | `python_exec` 结果的反思格式 / 成功格式包裹 |
| `_format_shell_result` / `_format_shell_timeout` | 私有 helper | `shell_exec` 结果的统一格式（含 returncode + 原 command + stdout + stderr）；`_format_shell_timeout` 附加 60s 预算提示，专用于反思路径 |

#### nodes.py 行为约定

- `python_exec`：`stderr` 非空 → `error_count++` + content 用反思格式（`Execution failed (returncode=...).\nCode:\n\`\`\`python\n{code}\n\`\`\`\nStderr:\n...\nStdout:\n...`）。
- `web_search`：把 `args.get("topic", "general")` 与 `args.get("days", 30)` 透传给工具函数；异常不走反思（直接 `except Exception` → `error_count++`）。
- `shell_exec`：把 `args.get("command", "")` 传给 `run_shell`；**只在 `returncode == -1`（超时）时 `error_count++` + 用 `_format_shell_timeout` 反思格式**，其他 returncode（含非 0）一律走 `_format_shell_result` 原样回传，**不计入 error_count**（progress 偏离 7）。
- JSON 解析失败：`json.JSONDecodeError` → `error_count++` + 回填错误提示，**不中断循环**（多 tool_call 场景仍能处理后续调用）。
- 任何工具抛 Python 异常（含 `OSError` / Tavily 异常 / subprocess 启动失败等）：`except Exception` → `error_count++` + 回填 `Tool '...' raised XError: ...`。
- `KeyboardInterrupt`（implement_plan §0.5 落实点）：当前 tool_call 回填 `"Tool execution interrupted by user."`；后续所有 tool_call 回填 `"Tool execution skipped due to earlier interrupt."`；`break` 跳出循环；**不冒泡，REPL 保持存活**。子进程的 kill 由 `subprocess.run` 自身完成。**shell_exec 100% 复用此中断逻辑**，未单独实现。
- 模块顶部 `_console = Console()` 单例；与 `cli.py` 的 Console 不同实例但同写 stdout，Rich 内部安全。

#### nodes.py 依赖关系

- 上游依赖：`rich.console.Console` + `baicode.llm.chat` + `baicode.tools.{python_exec, web_search, shell_exec, schemas}`。
- 被谁调：`graph.builder.build_graph()` 注册为 `"agent"` / `"tool"` 节点。

---

### 2.13 `graph/builder.py` — 图构建 + 条件边路由 + REPL 入口

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

- 上游依赖：`langgraph.graph.StateGraph` + `baicode.graph.{nodes, state}`。
- 被谁调：`cli.py::main()` 主循环。

---

## 3. 运行时产物（**不入库**）

| 路径 | 何时创建 | 用途 |
| --- | --- | --- |
| `~/.baicode_history` | REPL 启动时 prompt_toolkit 自动创建 | 跨会话方向键历史 |
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
   agent_node (chat + tools=ALL_SCHEMAS)    tool_node (python_exec | web_search | shell_exec)
          │                                 │
          ▼                                 ▼
        llm.chat                       tools.python_exec.run_python
       (litellm)                       tools.web_search.web_search
                                       tools.shell_exec.run_shell
                                       (tavily-python + config.load_config + subprocess)

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

Phase 1-6 落地后，**implement_plan §0.1 列出的所有源码文件均已就位**，Phase 6 额外新增 `tools/shell_exec.py`（plan §0.1 目录树未列但属于 tools/ 自然扩展）。Phase 4 仅做产品化封装（`pip install -e .` 已可用、`pyproject.toml [project.scripts]` 已注册）、Phase 5 仅改动 `cli.py` 内部实现、Phase 6 新增 1 个源码文件 + 修改 3 个既有文件，均未引入新的第三方依赖。
