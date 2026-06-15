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
| `README.md` | 对外项目说明：安装、使用、架构概览、工具约束、评测与已知限制 |
| `docs/banner.png` | README banner 图片资源 |
| `eval_runner.py` | 真实 LLM 自动化评测脚本，按 `memory-bank/eval.md` 的高价值 case 做路径/内容/耗时断言 |
| `memory-bank/` | 项目文档：PRD、技术栈、implement_plan、progress、architecture、eval、project_analysis、docs_sync_report |
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
| `_SYSTEM_PROMPT_TEMPLATE` / `_build_system_prompt()` | `str` / `() -> str` | 模板含 `{today}` 占位符；启动时 `date.today().isoformat()` 注入（每次 `baicode` 启动重算，**明年用是明年的日期**）。模板内嵌：禁止使用训练记忆中具体日期/数字；**偏离 15 起** `web_search` / `shell_exec` 对实时结构化数据（天气/股价/航班/汇率/卫星实时图像/比分）升级为编号 HARD RULE（① 不要调工具拉；② 立即告知能力受限 + 替代方案；③ **已调 1 次没拿到结构化数据就 STOP**），含中文示例覆盖 H-01 / E-02 真实 prompt；工具调用预算 5 次用完就停；**Phase 5 起**：模型输出代码必须使用带语言标注的围栏代码块以便 CLI 语法高亮；**Phase 6 起**：在工具清单中新增 `shell_exec` 段落，硬约束 cd 必须用 `&&` 串联（每次 shell 调用是独立子进程、无持久 CWD） + 禁交互式命令（vim/nano/less/more/top/htop/ssh-without-BatchMode） + 安装/包管理类命令必须非交互（`-y` / `--yes` / `--quiet` / `DEBIAN_FRONTEND=noninteractive`） |
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

**角色**：把 LLM 生成的 shell 命令字符串交给系统默认 shell 子进程执行，回传 stdout/stderr/returncode 三元组。**纯净、无状态、无持久 CWD**。Unix/macOS 通常是 `/bin/sh`；Windows 是 `cmd.exe`。

#### shell_exec.py 关键导出

| 名字 | 类型 | 作用 |
| --- | --- | --- |
| `TIMEOUT_SECONDS` | `int = 60` | 单次执行硬上限（详见 progress 偏离 8） |
| `MAX_CHARS` | `int = 4000` | stdout / stderr 各自独立的截断阈值 |
| `HEAD_CHARS` / `TAIL_CHARS` | `int = 2000` / `int = 2000` | 超长输出保留的头部与尾部字符数 |
| `_truncate(text)` | 私有 helper | 超长 → `text[:2000] + "\n...[truncated N chars]...\n" + text[-2000:]` |
| `run_shell(command) -> dict` | 单次执行入口 | 返回 `{"stdout": str, "stderr": str, "returncode": int}` |

#### shell_exec.py 行为约定

- 执行命令：`subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)`。**不显式 `executable=` 参数**，沿用系统默认 shell：Unix/macOS 通常为 `/bin/sh`（POSIX shell，`&&` / `|` / `>` 全支持，但 `[[ ]]` / process substitution 等 bash 拓展不支持）；Windows 为 `cmd.exe`。
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
| `SHELL_EXEC_SCHEMA` | `dict` | `function.name="shell_exec"`，参数 `command: string (required)`。description 按 `sys.platform` 区分 Windows `cmd.exe` 与 Unix `/bin/sh` 提示，并内嵌四条约束：60s 超时 / 输出截断 / cd 隔离（每次调用独立子进程） / 禁交互式命令 + 安装类命令必须非交互 |
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

**角色**：LangGraph 节点间流转的 `TypedDict`。Phase 7 起，宏图与微图共用同一份 `AgentState`，新增 4 个字段服务宏图层。

| 字段 | 类型 | 由谁初始化 | 含义 |
| --- | --- | --- | --- |
| `messages` | `list` | `builder.run`（宏图）/ `_run_micro`（微图内部） | **宏图层**：`[system, user, ..., assistant_final]`（assistant_final 由 Finalizer 产出）。**微图层**：每次进入 Executor 时构造的"全新单步对话"（system+addendum, user(history_brief+task)），微图内部 tool_call / reasoning_content 等都只活在这段隔离 messages 中，宏图层不可见 |
| `error_count` | `int` | 宏图 `builder.run`（=0）/ 微图 `_run_micro`（=0） | **每个 Executor 单步内部**累计的工具失败次数。`python_exec.stderr` 非空 / `shell_exec` 超时（`returncode==-1`）或抛 Python 异常 / 任何 tool 抛异常 / JSON 解析失败 / 未知工具名 → ++。**`shell_exec` 的非 0 returncode 不计入**（grep 无匹配 / test 失败这类是正常业务输出）。`error_count >= retry_limit` → 微图抛 `ReflectionRetriesExceeded`，被 `executor_node` 捕获转 history failed 条目 |
| `retry_limit` | `int` | `builder.run`（=3） | 每步反思上限 |
| `tool_calls_count` | `int` | 同上（=0） | 每个 Executor 单步内部 `tool_node` 被调用的总次数 |
| `max_tool_calls` | `int` | `builder.run`（=5） | 每步工具调用上限 |
| **`plan`** | `list[str]` | `builder.run`（=`[]`），由 Planner / Replanner 写入 | **宏图字段**：待执行任务清单 FIFO，Executor 每步从 `plan[0]` 取并弹首项 |
| **`history`** | `list[dict]` | `builder.run`（=`[]`），由 Executor 追加 | **宏图字段**：已完成步骤清单。每条形如 `{"task": str, "summary": str, "status": "success" \| "failed"}`。Replanner 与 Finalizer 都读这个字段 |
| **`replan_count`** | `int` | `builder.run`（=0），由 Replanner ++ | **宏图字段**：已发生的重规划次数 |
| **`max_replans`** | `int` | `builder.run`（=3） | **宏图字段**：重规划上限。`replan_count >= max_replans` 且步骤失败时，宏图直接路由 Finalizer 而非 Replanner，防止死循环 |

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
- 模块顶部 `_console = Console()` 单例；与 `cli.py` 的 Console 不同实例但同写 stdout，Rich 内部安全。**Phase 7 起，Planner / Executor / Replanner / Finalizer 4 个宏图节点全部复用本单例**（共享同一 stdout，视觉风格统一）。

#### nodes.py 依赖关系

- 上游依赖：`rich.console.Console` + `baicode.llm.chat` + `baicode.tools.{python_exec, web_search, shell_exec, schemas}`。
- 被谁调：Phase 1-6 由 `graph.builder._build_micro_graph()` 注册为 `"agent"` / `"tool"` 节点；Phase 7 起仅被 Executor 内部的 `_run_micro` 间接调起。

---

### 2.13 `graph/builder.py` — 图构建 + 路由 + REPL 入口（Phase 1-6 微图 + Phase 7 宏图）

#### builder.py 关键导出

| 名字 | 类型 / 签名 | 作用 |
| --- | --- | --- |
| `ReflectionRetriesExceeded` | `RuntimeError` 子类 | 工具失败 ≥ `retry_limit`。**Phase 7 起仅在 Executor 内部抛出并被同节点捕获**，不再冒泡到 CLI（CLI 仍保留 except 分支作防御兜底） |
| `ToolCallBudgetExceeded` | `RuntimeError` 子类 | 工具调用 ≥ `max_tool_calls` 且模型仍想调。同上 |
| `run(messages, retry_limit=3, max_tool_calls=5, max_replans=3)` | **公共宏图入口** | Phase 7 起本函数装配宏图。签名向后兼容（新增 `max_replans` 通过默认值无缝接入），cli.py `graph_run(messages)` 调用点无需改动 |
| `_build_micro_graph()` | 私有 | Phase 1-6 的 `agent ↔ tool` 微图；模块外仅由 `_run_micro` 调起 |
| `_run_micro(messages, retry_limit, max_tool_calls)` | 私有 | Phase 1-6 的 REPL 入口同名函数，Phase 7 起改名+私有化。**仅 `executor_node` 内部调起**，每次注入"全新 executor_messages"。检查 final state 抛 `ReflectionRetriesExceeded` / `ToolCallBudgetExceeded`，让 `executor_node` 用 try/except 转 history failed |
| `_build_macro_graph()` | 私有 | Phase 7 宏图：`START → planner → {react \| executor} → (react→END) / (executor↔replanner→finalizer) → END`。**5 个节点函数都在函数体内 deferred import**（避免 builder→planner/react/executor/replanner/finalizer→builder 的传递循环） |

#### builder.py 图结构

**微图（Phase 1-6，复用零修改）**：

```text
START ──► agent ──┬──► tool ──┬──► agent      (常规 ReAct 回路)
                  │            └──► END       (error_count ≥ retry_limit → exceeded)
                  ├──► END                    (last 无 tool_calls → 自然收尾)
                  └──► END                    (last 有 tool_calls 但 tool_calls_count ≥ max → exceeded)
```

**宏图（Phase 7 新增；偏离 14 后含 react 分诊分支）**：

```text
START → planner ──┬─► react ──► END                            (Planner 输出 0/1 step：chitchat / 单步任务，无 Plan UX)
                  │
                  └─► executor ──┬─► executor    (plan 仍非空，跑下一步)
                                 ├─► replanner ──┬─► executor    (插补救后继续)
                                 │               └─► finalizer   (replanner 选 abort)
                                 └─► finalizer    (plan 空，全部完成)

finalizer → END
```

#### builder.py 路由函数

| 路由 | 来源 | 返回 | 判断逻辑 |
| --- | --- | --- | --- |
| `_route_after_agent` | 微图 | `"tool"` / `"end"` / `"exceeded"` | last 有 tool_calls 且预算未耗尽 → tool；预算耗尽 → exceeded；否则 → end。`"exceeded"` 与 `"end"` 都映射 END，由 `_run_micro` 事后检查 state 区分 |
| `_route_after_tool` | 微图 | `"agent"` / `"exceeded"` | `error_count >= retry_limit` → exceeded；否则 → agent |
| `_route_after_planner` | 宏图 | `"react"` / `"executor"` | `len(plan) >= 2` → executor（plan 模式）；否则 → react（0/1 step 走 react 直通，progress 偏离 14） |
| `_route_after_executor` | 宏图 | `"executor"` / `"replanner"` / `"finalizer"` | `history[-1].status == "failed"` 且 `replan_count < max_replans` → replanner；`plan == []` → finalizer；否则 → executor（下一步）|
| `_route_after_replanner` | 宏图 | `"executor"` / `"finalizer"` | `plan == []` → finalizer（Replanner 选 abort）；否则 → executor |

#### builder.py 其他约定

- `_RECURSION_LIMIT = 50` 兜底 LangGraph 死循环；正常情况 `retry_limit` / `max_tool_calls` / `max_replans` 都会先触发。
- 宏图层**不再**事后检查 `error_count` / `tool_calls_count` 超限——Executor 内部已经吃掉这两个异常并转 history。`run()` 公共入口正常路径不会抛 `ReflectionRetriesExceeded` / `ToolCallBudgetExceeded`。

#### builder.py 依赖关系

- 上游依赖：`langgraph.graph.StateGraph` + `baicode.graph.{nodes, state}` + （deferred）`baicode.graph.{planner, executor, replanner, finalizer}`。
- 被谁调：`cli.py::main()` 主循环唯一调 `run`；`executor.py` 调 `_run_micro` + import 2 个异常类。

---

### 2.14 `graph/planner.py` — Planner 节点（Phase 7 新增）

**角色**：把用户最新输入拆成 0-5 步任务清单，写入 `state["plan"]`。是宏图的起点（紧接 `START` 之后）。

#### planner.py 关键导出

| 名字 | 签名 / 类型 | 作用 |
| --- | --- | --- |
| `PLAN_SCHEMA` | `dict` | OpenAI function calling schema，`function.name="submit_plan"`，参数 `steps: array of strings`、`rationale: string`。**仅 Planner 内部用**，不加入 `ALL_SCHEMAS`（避免主对话模型乱调） |
| `planner_node(state) -> dict` | LangGraph 节点 | `Console.status("planning...", style=dim cyan)` + `chat([system+_PLANNER_PROMPT, user(state.messages[-1].content)], tools=[PLAN_SCHEMA])` → 解析 `submit_plan` 的 `steps` → 写 `state["plan"]` |
| `_extract_steps(raw)` | 私有 helper | 从 chat 返回的 dict 中提取 `submit_plan` 的 steps（兼容 LiteLLM pydantic / dict 两种 tool_call 形态）。坏数据返回 `None` |
| `_render_plan_panel(plan)` | 私有 helper | 通过 `nodes._console` 打印蓝边框 `Panel(numbered_list, title="📋 Plan")` |

#### planner.py 行为约定

- **JSON 解析失败兜底**：第 1 次失败 → 用追加 `_PLANNER_RETRY_HINT` 的 prompt 重试 1 次；第 2 次仍失败 → fallback 为 `plan=[user_request]`（单步，自动落入 react 直通路径；progress 偏离 11）。
- **`_render_plan_panel` 阈值**：仅当 `len(plan) >= 2` 才打印蓝边框 Panel。0/1 step 静默（progress 偏离 14）——这样 react 路径（0/1 step）保持 Phase 1-6 原生 ReAct 视觉，无任何 plan 字样。
- **prompt 设计要点**（偏离 14 之后）：★CRITICAL RULE 置顶——"总结 / 简述 / report / explain the result is NEVER its own step"；新增 2 条反例 few-shot（"搜新闻并简述" / "跑 script.py 看输出" → 1 step）；明确 "When unsure between 1 and N steps, prefer 1"。

#### planner.py 依赖关系

- 上游依赖：`rich.panel.Panel` + `baicode.graph.nodes._console` + `baicode.llm.chat`。
- 被谁调：`_build_macro_graph` 注册为 `"planner"` 节点。

---

### 2.15 `graph/executor.py` — Executor 节点（Phase 7 新增）

**角色**：每次进入时取 `plan[0]` 当前任务、用 `history` 拼背景，构造**全新 executor_messages**（隔离派），调用微图 `_run_micro` 跑一遍 ReAct 循环，提取末条 assistant content 作为 summary 写入 `history`，从 `plan` 弹首项。

#### executor.py 关键导出

| 名字 | 签名 / 类型 | 作用 |
| --- | --- | --- |
| `executor_node(state) -> dict` | LangGraph 节点 | 主入口。打印 `▶ Step N/M: <task>`（粗体蓝 + dim 任务描述），调 `_run_micro`，捕获 `ReflectionRetriesExceeded` / `ToolCallBudgetExceeded` 转 failed 条目，返回 `{history, plan, error_count=0, tool_calls_count=0}` |
| `_format_history_brief(history)` | 公共 helper | 把 history 渲染为 `"1. [✓] task\n   → summary\n2. [✗] ..."` 形式。**被 Replanner / Finalizer 共用** |
| `_build_executor_messages(current_task, history, base_system_prompt)` | 私有 helper | 构造 `[system+_EXECUTOR_ADDENDUM, user(history_brief+task)]` 单步对话 |
| `_EXECUTOR_ADDENDUM` | `str` | 拼到 base system prompt 末尾，告知模型"你是 EXECUTOR MODE，只解决当前 task、不要规划下一步、最终回复用 1-3 句总结" |

#### executor.py 行为约定

- **隔离派 messages**：每步全新构造 `[system, user]` 两条消息，微图内部的 tool_call / reasoning / observation 都活在这段隔离序列里。微图返回后只把末条 assistant content 当 summary 抽取出来，原序列丢弃。
- **预算每步重置**：通过 `_run_micro` 内部 invoke 时 `error_count=0` / `tool_calls_count=0` 实现；本节点返回 `error_count=0 / tool_calls_count=0` 是仅作宏图状态卫生，宏图本身不读这两个字段。
- **失败转 history**：`_run_micro` 抛上述两个异常时 status="failed"，summary 含异常名 + 消息；其他情况 status="success"，summary 取末条 assistant content（空时填 `"(empty)"`）。其它异常（编程错误、KeyboardInterrupt）**不捕获**，照常冒泡到 CLI。
- **Step 编号**：`step_num = len(history) + 1`、`total = step_num + len(plan) - 1`。Replanner 中途插补救步会让 `total` 动态增长。
- **deferred import**：`from baicode.cli import _build_system_prompt` 在函数体内执行，避免 cli → builder → executor → cli 的模块加载期循环。

#### executor.py 依赖关系

- 上游依赖：`baicode.graph.builder.{_run_micro, ReflectionRetriesExceeded, ToolCallBudgetExceeded}` + `baicode.graph.nodes._console` + （deferred）`baicode.cli._build_system_prompt`。
- 被谁调：`_build_macro_graph` 注册为 `"executor"` 节点；`_format_history_brief` 被 `replanner.py` / `finalizer.py` 共用 import。

---

### 2.16 `graph/replanner.py` — Replanner 节点（Phase 7 新增）

**角色**：在 Executor 报告 step failed 时被宏图路由进入，决策"插入补救任务"还是"放弃整任务"。

#### replanner.py 关键导出

| 名字 | 签名 / 类型 | 作用 |
| --- | --- | --- |
| `REPLAN_SCHEMA` | `dict` | OpenAI function calling schema，`function.name="submit_replan"`，参数 `action: enum["insert_remedy","abort"]` + `new_plan: array of strings` + `rationale: string`。仅本节点内部用 |
| `replanner_node(state) -> dict` | LangGraph 节点 | `Console.print("🔄 Replanning...")` + `chat([system+_REPLANNER_PROMPT, user(原始请求+全 history+失败 step+剩余 plan)], tools=[REPLAN_SCHEMA])` → 解析 action+new_plan → 替换 `state["plan"]` 并 `replan_count++` |
| `_extract_replan(raw)` | 私有 helper | 解析 `submit_replan`，校验 action 在合法枚举内、new_plan 是 list；坏数据返回 `None` |
| `_render_new_plan_panel(new_plan)` | 私有 helper | 通过 `nodes._console` 打印黄边框 `Panel(numbered_list, title="🔄 Revised Plan")`；空 plan 打印"Replanner aborted" 黄字 |

#### replanner.py 行为约定

- **JSON 解析失败兜底**：直接 `action="abort"` + `new_plan=[]` + `replan_count++`。让流程进入 Finalizer 报告部分完成。
- **new_plan 语义**：当 action=insert_remedy 时，new_plan 是"完整的剩余 plan"（补救步在前 + 可能改写过的原剩余步），不是"补救步追加"。Replanner 的 prompt 已明确这一点。
- **触发条件由宏图把控**：`_route_after_executor` 在 `history[-1].status == "failed"` 且 `replan_count < max_replans` 时才路由进来；本节点不需要再判 `max_replans`，自己只管 ++。

#### replanner.py 依赖关系

- 上游依赖：`rich.panel.Panel` + `baicode.graph.executor._format_history_brief` + `baicode.graph.nodes._console` + `baicode.llm.chat`。
- 被谁调：`_build_macro_graph` 注册为 `"replanner"` 节点。

---

### 2.17 `graph/finalizer.py` — Finalizer 节点（Phase 7 新增）

**角色**：宏图的终点节点。综合 `history` 调一次 LLM 用自然语言写出用户友好的最终回复，append 到 `state["messages"]`（被 cli.py `render_typewriter` 渲染）。

#### finalizer.py 关键导出

| 名字 | 签名 / 类型 | 作用 |
| --- | --- | --- |
| `finalizer_node(state) -> dict` | LangGraph 节点 | `Console.status("wrapping up...", style=dim cyan)` + `chat(...)` → assistant message append 到 messages |
| `_FINALIZER_ADDENDUM` | `str` | 拼到 base system prompt 末尾，告知模型"你是 FINALIZER MODE，直面用户，把机器输出翻译成用户语言，承认未完成部分" |

#### finalizer.py 行为约定

- **chitchat 短路**：`history == []`（Planner 输出空 plan 的路径）→ finalizer messages 仅 `[system, user(原始请求)]`，**不带 addendum**，让 LLM 等价于 Phase 1-6 单轮对话直接回应。
- **多步路径**：`history != []` → finalizer messages 形如 `[system+_FINALIZER_ADDENDUM, user("原始请求 + history_brief + 请给我友好回复")]`。
- **`tools=None`**：Finalizer 强制纯文本输出，不再触发任何工具调用。即使模型想调工具，schema 不存在它也无从下手。
- **deferred import**：与 executor.py 同理，函数体内 `from baicode.cli import _build_system_prompt`。

#### finalizer.py 依赖关系

- 上游依赖：`baicode.graph.executor._format_history_brief` + `baicode.graph.nodes._console` + `baicode.llm.chat` + （deferred）`baicode.cli._build_system_prompt`。
- 被谁调：`_build_macro_graph` 注册为 `"finalizer"` 节点。**仅在 plan 模式（plan ≥ 2 step）路径终点被命中**——偏离 14 之后，0/1 step 走 react 不经过本节点。

---

### 2.18 `graph/react.py` — React 节点（Phase 7 偏离 14 新增；偏离 15 引入 fail-soft）

**角色**：Planner 判定 `len(plan) <= 1`（chitchat / 单步任务 / 解析失败兜底）时走的纯 ReAct 直通路径，等价于 Phase 1-6 行为；偏离 15 起对 `ToolCallBudgetExceeded` 加 fail-soft 兜底。

#### react.py 关键导出

| 名字 | 签名 / 类型 | 作用 |
| --- | --- | --- |
| `react_node(state) -> dict` | LangGraph 节点 | 调 `_run_micro(state["messages"], retry_limit, max_tool_calls)`，把末条 assistant content 追加到宏图 messages；命中 `ToolCallBudgetExceeded` 时改用 `_BUDGET_EXCEEDED_FALLBACK` 作为末条 content |
| `_BUDGET_EXCEEDED_FALLBACK` | `str` 常量 | 工具预算耗尽时的友好降级 markdown 回复（提示能力受限 + 列出实时结构化数据的替代渠道）|

#### react.py 行为约定

- **直跑用户原始 messages**：不构造 executor_messages、不附加 `_EXECUTOR_ADDENDUM`、不传 history_brief。agent 看到的就是 cli.py 喂进来的 `[system, user]`（或多轮的完整历史），与 Phase 1-6 一致。
- **末条 assistant content 写回宏图**：微图返回的 messages 序列包含中间的 tool_calls / role="tool" 响应等，**只取最后一条 assistant 的 content** append 到 macro state["messages"]。这与 multi-step 的 Finalizer 输出形态一致——CLI 看到的每轮回复永远是干净的 `[system, user, ..., user_n, assistant_n]`。
- **异常处理（偏离 15 后）**：
  - `ToolCallBudgetExceeded`：**捕获 + 替换 last_content** 为 `_BUDGET_EXCEEDED_FALLBACK`。E-02 / H-01 之类实时结构化数据请求烧光预算时的 UX 兜底，避免红字穿透。捕获后 messages 仍正常 append 一条 assistant，CLI 端看不出区别（render_typewriter 正常渲染 markdown 回复）。
  - `ReflectionRetriesExceeded`：**不捕获**，照常冒泡到 cli.py，由既有 except 矩阵处理（红字提示 + `messages.pop()` 回滚 + REPL 继续）。这是确定性的 3 次工具失败（语法/类型/真错误），保留红字让用户知道发生了什么。
  - 其他异常（编程错误、KeyboardInterrupt 等）：**不捕获**，照常冒泡。
- **无任何 UI 副作用**：不打印 Plan panel、不打印 ▶ Step 指示。视觉上只剩下 `agent_node` 的 `thinking...` spinner 与 `tool_node` 的 `Running tool...` spinner——与 Phase 1-6 完全一致。命中 fail-soft 时也无额外打印（fallback 文案直接走 render_typewriter）。
- **路由触发条件**：`_route_after_planner` 在 `len(plan) <= 1` 时返回 `"react"`，含 3 种情况：①Planner 输出 `[]`（chitchat）；②Planner 输出 1 step（含 1-action task）；③Planner JSON 解析失败 fallback 的 `[user_request]`。

#### react.py 依赖关系

- 上游依赖：`baicode.graph.builder.{_run_micro, ToolCallBudgetExceeded}`。
- 被谁调：`_build_macro_graph` 注册为 `"react"` 节点。

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
       graph.builder.run(messages, retry_limit=3, max_tool_calls=5, max_replans=3)
                       │
                       ▼
       ┌────────────  Macro StateGraph (Phase 7)  ──────────────┐
       │                                                         │
       ▼                                                         │
  planner_node ──分诊──┬──► react_node ──► END                  │
       │              │   (0/1 step：chitchat / 单步任务)        │
       │              │                                          │
       │              └──► executor_node ──► replanner_node     │
       │                       │                  │              │
       │                       │ _run_micro       │              │
       │                       ▼                  └──► finalizer │
       │             ┌── Micro StateGraph (Phase 1-6) ──┐       │
       │             │                                   │       │
       │             ▼                                   ▼       │
       │         agent_node ◄────────────────── tool_node        │
       │             │                              │             │
       │             ▼                              ▼             │
       │          llm.chat                  tools.python_exec.run_python
       │          (litellm)                 tools.web_search.web_search
       │                                     tools.shell_exec.run_shell
       │                                                          │
       └─chat(tools=[PLAN_SCHEMA])      chat(tools=[REPLAN_SCHEMA])
                                                                  │
                       │ updated_messages [system, user, ..., assistant_final]
                       ▼
              cli.render_typewriter (rich Live + Markdown)
```

- **单向依赖、无环**（循环导入靠 deferred import 避开）。
- `cli` 持有 `messages` 主权，每轮 user 后调 `graph_run` 拿回完整序列并覆盖。每轮 messages 终态为 `[system, u1, a1, ..., un, an]`，宏图内部的 plan / history / replan_count 不进入 messages、随 `run()` 返回消失。
- `prompt_toolkit` / `rich` / `litellm` / `tavily` / `langgraph` 均为叶子依赖。
- Phase 7 闭环（偏离 14 后）：`cli.main → graph.builder.run（宏图）→ planner_node → 分诊到 react_node 或 executor_node{_run_micro→agent_node↔tool_node} → (replanner_node) → (finalizer_node) → llm.chat / tools.*`。
- **两条路径的视觉差异**：react 路径无 Plan panel / 无 ▶ Step 指示，与 Phase 1-6 ReAct 一致；plan 路径有 📋 Plan panel + ▶ Step k/N + （失败时）🔄 Replanning + 🔄 Revised Plan panel。

---

## 5. 待添加文件

Phase 1-7 全部落地后，**implement_plan §0.1 + §Phase 7 列出的所有源码文件均已就位**：
- Phase 6 额外新增 `tools/shell_exec.py`（plan §0.1 目录树未列但属于 tools/ 自然扩展）。
- Phase 7 在 `graph/` 下新增 `planner.py` / `executor.py` / `replanner.py` / `finalizer.py` 4 个节点文件 + （偏离 14 实施后）`react.py`，共 **5 个新节点文件**。复用 `nodes.py` 单例 Console 与 `_run_micro` 入口。
- Phase 4 仅做产品化封装、Phase 5 仅改动 `cli.py` 内部实现、Phase 6 新增 1 个源码文件 + 修改 3 个既有文件、**Phase 7 新增 5 个源码文件 + 修改 2 个既有文件**（state.py + builder.py），均未引入新的第三方依赖。
