# 进度记录 (Progress Log)

本文档**逐步、增量**记录每个 Step 完成时的实际产出、偏离 implement_plan 的决策点、以及测试通过证据，供后续开发同学接续工作。

新阶段开工前请先阅读本文档**最后一节**，了解上一阶段留下的上下文。

---

## Phase 1: CLI 基建与网关打通 — ✅ 完成于 2026-05-15

### Step 1: 环境初始化与配置加载 — ✅

#### Step 1 落地文件

- `pyproject.toml`（包名 `cagent`、`requires-python >= 3.10`、`[project.scripts] cagent = "cagent.cli:main"`、`src/` 布局）
- `.env.example`（配置模板）
- `.env`（本地真实 Key，已加入 .gitignore）
- `.gitignore`（增补 Python 工件 + `.workspace/`）
- `src/cagent/__init__.py`、`src/cagent/config.py`

#### Step 1 API

- `load_config() -> Config`：调用 `dotenv.find_dotenv(usecwd=True)`，从 CWD 向上递归查找 `.env`。
- `Config (@dataclass(frozen=True))`：字段 `deepseek_api_key` / `tavily_api_key` / `openai_api_key` / `default_model`。
- `MissingAPIKeyError(key_name)`：自定义异常，附带 `.key_name` 字段方便上层分支。
- `DEFAULT_MODEL = "deepseek/deepseek-chat"`。

#### Step 1 测试证据

- ✅ 1A 正常加载：DEEPSEEK / TAVILY Key、model 名都正确读取。
- ✅ 1B 缺 `DEEPSEEK_API_KEY`：抛 `MissingAPIKeyError(key_name="DEEPSEEK_API_KEY")`。
- ✅ 1C 缺 `TAVILY_API_KEY`：抛 `MissingAPIKeyError(key_name="TAVILY_API_KEY")`。

### Step 2: REPL 基础交互循环 — ✅

#### Step 2 落地文件

- `src/cagent/cli.py`

#### Step 2 关键实现

- `PromptSession(multiline=True, history=FileHistory("~/.cagent_history"))`。
- 提交快捷键：**Alt+Enter / Meta+Enter**（macOS Terminal 须启用 "Use Option as Meta key"，iTerm2 默认 OK）。
- 顶层 `except (KeyboardInterrupt, EOFError)` → 打印"再见。"清退，无堆栈外泄。
- 启动时 `sys.stdin.isatty()` 守卫：非 TTY 给红字提示并退出（避免 prompt_toolkit 内部 KeyError 堆栈）。

#### Step 2 测试证据

- ✅ 启动 banner 自动化验证。
- ✅ 用户在真实终端手动验证：Alt+Enter 提交、↑/↓ 翻历史、`~/.cagent_history` 持久化、Ctrl+C 优雅退出。

### Step 3: LLM 网关 + 伪流式渲染 — ✅

#### Step 3 落地文件

- `src/cagent/llm.py` + `cli.py::render_typewriter()`

#### Step 3 关键实现

- LiteLLM `completion(model="deepseek/deepseek-chat", stream=False, api_key=...)`，**通信层非流式**。
- `render_typewriter(text, console, style="green", delay=0.005)`：Rich `Live + Text` 模拟逐字打字机。
- 异常分级：

| LiteLLM 异常 | 我方包装 | 行为 |
| --- | --- | --- |
| `AuthenticationError` | `FatalAuthError` | `sys.exit(1)` |
| `RateLimitError` | （内部）退避 2s 重试 1 次 → `ChatError` | 上层红字 + REPL 继续 |
| `APIConnectionError` / `Timeout` | `ChatError` | 同上 |
| 关键字命中 (`authentication` / `invalid api key` …) | `FatalAuthError` | `sys.exit(1)` |
| 其他 | `ChatError` | 上层红字 + REPL 继续 |

#### Step 3 测试证据

- ✅ 3A 真实 DeepSeek 调用：返回 `"pong from deepseek"`。
- ✅ 3B 错误 Key 致命退出（修复后通过，见下方"偏离记录 1"）。
- ✅ 3C 端到端：模型返回"你好世界"，`render_typewriter` 无崩溃。

#### Step 3 真实观察

DeepSeek 服务端偶发 SSL `UNEXPECTED_EOF_WHILE_READING` 被 LiteLLM 分类为 `InternalServerError` → 我方走 `ChatError` 分支 → REPL 红字提示后继续可用，**符合 implement_plan §0.2 "网络瞬时错误：提示并允许重试"** 的设计（不自动重试，由人决定）。

---

## 偏离 implement_plan 的两处记录

### 偏离 1：`llm.py` 增加 `_looks_like_auth_error()` 关键字嗅探兜底

- **起因**：DeepSeek 在 LiteLLM 中把 401 错误包成 `BadRequestError`（非标准）。Plan §0.2 规约"鉴权失败必须致命退出"，原始 `except litellm.AuthenticationError` 分支会漏掉这种情况。
- **修复**：在通用 `except Exception` 末尾追加关键字判断（`authentication` / `unauthorized` / `invalid api key` …），命中则转抛 `FatalAuthError`。
- **影响范围**：仅扩大了 fatal 路径覆盖面，不影响其他异常分支。

### 偏离 2：`cli.py` 增加 `sys.stdin.isatty()` 守卫

- **起因**：Plan 未要求，但 `cagent < /dev/null` 会触发 prompt_toolkit 内部 `KeyError`，输出未捕获的堆栈。
- **修复**：启动时若 stdin 非 TTY，红字提示后干净退出。

---

## 运行说明（保留给后续接手者）

```bash
cd "/Users/shitangbaichuan/7822/实习/vibe coding/myagent"
source .venv/bin/activate
cagent
```

- 配置：`.env` 必须含 `DEEPSEEK_API_KEY`、`TAVILY_API_KEY`；可选 `OPENAI_API_KEY`。
- 安装方式：`pip install -e .`（已 editable 安装过；改 src 后无需重装）。
- 全局命令名：`cagent`。
- 历史文件：`~/.cagent_history`。

---

## Phase 2: 工具层原子化抽象 — ✅ 完成于 2026-05-15

### Step 4: Python 原生执行器 — ✅

#### Step 4 落地文件

- `src/cagent/tools/__init__.py`（包占位）
- `src/cagent/tools/python_exec.py`
- `pyproject.toml` 新增依赖 `tavily-python>=0.5.0`（与 Step 5 一并）

#### Step 4 API

- `run_python(code: str) -> dict`：返回 `{"stdout": str, "stderr": str, "returncode": int}`。
- 内部常量：`TIMEOUT_SECONDS = 10`、`WORKSPACE_DIR = Path(".workspace")`、`TEMP_SCRIPT = WORKSPACE_DIR / "temp_exec.py"`。
- 执行方式：`subprocess.run([sys.executable, ".workspace/temp_exec.py"], capture_output=True, text=True, timeout=10)`，在**当前激活 venv** 中运行。
- 超时处理：捕获 `subprocess.TimeoutExpired`，`stderr` 末尾追加 `"TIMEOUT after 10s"`，`returncode = -1`。

#### Step 4 测试证据

- ✅ A 正常：`run_python('print("hi")')` → `stdout="hi\n"`、`returncode=0`、`stderr=""`。
- ✅ B 异常：`run_python("print(undefined_var)")` → `returncode=1`、`stderr` 含完整 `NameError` traceback。
- ✅ C 超时：`while True: pass` 10.00s 后返回 `returncode=-1`、`stderr` 含 `"TIMEOUT after 10s"`。
- ✅ 用户已手动复测三个分支通过。

### Step 5: Tavily Web 搜索 — ✅

#### Step 5 落地文件

- `src/cagent/tools/web_search.py`
- `src/cagent/tools/schemas.py`（与 Step 4 工具一同集中）

#### Step 5 API

- `web_search(query: str) -> str`：取 Tavily Top-3，每条按 `[url]\ncontent\n` 拼接，**整体 4000 字符硬截断**。
- 内部常量：`MAX_CHARS = 4000`、`TOP_K = 3`。
- 鉴权来源：每次调用前 `load_config()` 取 `TAVILY_API_KEY`，传入 `TavilyClient(api_key=...)`。

#### Step 5 测试证据

- ✅ 真实查询 `"what is python programming language"` 返回 3329 字符（≤4000）、含 `[url]` 标记、内容为 python.org 等高相关网页。
- ✅ 用户已手动复测通过。

### Step 4-5 通用：tools schema 集中定义 — ✅

#### schemas 关键导出

- `PYTHON_EXEC_SCHEMA`：OpenAI function schema，参数 `code: string`。
- `WEB_SEARCH_SCHEMA`：OpenAI function schema，参数 `query: string`。
- `ALL_SCHEMAS = [PYTHON_EXEC_SCHEMA, WEB_SEARCH_SCHEMA]`：供 Phase 3 `agent_node` 一次性传给 `llm.chat(messages, tools=...)`。

#### Phase 2 决策点（无偏离 implement_plan）

- `.workspace/` 目录使用 `Path(".workspace")` 相对路径，子进程沿用当前 CWD。`cagent` 在哪个目录被启动，`.workspace/temp_exec.py` 就落在哪。已在 `.gitignore` 中排除。
- `web_search` 暂未做 client 缓存（每次调用 `load_config()` + 新建 `TavilyClient`）；MVP 阶段调用频率低，等 Phase 3 看实际开销再决定是否做 `functools.lru_cache`。

---

## Phase 3: 工作流状态机 + ReAct + Reflection — ✅ 完成于 2026-05-16

### Step 6-8 一并落地 — ✅

#### Phase 3 落地文件

- `src/cagent/graph/__init__.py`（占位）
- `src/cagent/graph/state.py`：`AgentState` TypedDict，字段 `messages` / `error_count` / `retry_limit` / `tool_calls_count` / `max_tool_calls`
- `src/cagent/graph/nodes.py`：手写 `agent_node` + `tool_node`（禁用 prebuilt `ToolNode` / `create_react_agent`）；`_normalize_tool_calls` 把 LiteLLM 的 pydantic tool_calls 转成 dict 列表
- `src/cagent/graph/builder.py`：`build_graph()` + `run(messages, retry_limit=3, max_tool_calls=5)`；异常 `ReflectionRetriesExceeded` / `ToolCallBudgetExceeded`；`_RECURSION_LIMIT=50`
- `src/cagent/cli.py`：主循环切到 `graph_run(messages)`；新增两个异常分支；`SYSTEM_PROMPT` 改成 `_build_system_prompt()` 启动时注入 `date.today()`
- `pyproject.toml` 新增 `langgraph>=0.2.0`

#### Phase 3 关键设计点

- **agent_node**：`Console.status("thinking...", style=dim cyan)` + `chat(messages, tools=ALL_SCHEMAS)`；把 `reasoning_content` 与 `tool_calls` 一同写入 assistant message。
- **tool_node**：`Console.status("Running tool...", style=yellow)` + 按 `function.name` 分发 `python_exec` / `web_search`；Observation 静默不打印；`python_exec` 的 `stderr` 非空 → `error_count++` + 反思格式 content；任何 tool 异常 → `error_count++`；`KeyboardInterrupt` → 回填 `"Tool execution interrupted by user."` 并把剩余 tool_calls 标 `"skipped due to earlier interrupt"`；节点末尾 `tool_calls_count += 1`。
- **条件边**：
  - `agent → tool` 当 `last.tool_calls` 非空且 `tool_calls_count < max_tool_calls`；否则 → `END`（自然收尾）或 `exceeded`（仍想调工具但预算耗尽）。
  - `tool → agent`，但 `error_count >= retry_limit` → `exceeded`。
- **超限语义**：`exceeded` 路由到 `END` 后 `run()` 检测并抛 `ReflectionRetriesExceeded` 或 `ToolCallBudgetExceeded`；REPL 红字 + `messages.pop()` 回到提示符。

#### Phase 3 测试证据（脚本绕过 REPL 直调 `graph.builder.run`）

- ✅ 简单对话不调工具（"请只回复两个字：你好"）。
- ✅ 算术触发 `python_exec` 一次成功（1234567×7654321 = 9449772114007）。
- ✅ 反思自愈（除零 → tool 报错 → 修复 → 成功）。
- ✅ `retry_limit` 红线：mock `run_python` 永远失败 → 3 次后抛 `ReflectionRetriesExceeded`。
- ✅ Ctrl+C 内层：mock `run_python` 抛 `KeyboardInterrupt` → tool_node 不冒泡，回填 Observation。
- ✅ `max_tool_calls` 硬兜底：mock chat 死磕调工具 → 5 次后抛 `ToolCallBudgetExceeded`。
- ✅ 用户已在 REPL 手动验证多 case 顺手。

### Phase 3 偏离 implement_plan 的决策记录

#### 偏离 3：默认模型切到 `deepseek-v4-flash`

- **起因**：implement_plan §0.2 与 Phase 1 的 `DEFAULT_MODEL` 是 `deepseek/deepseek-chat`；用户切到 `deepseek/deepseek-v4-flash` 以获取推理能力。
- **影响**：v4-flash 是 thinking-mode 模型，响应额外带 `reasoning_content`；多轮调用时该字段**必须回传**，否则 DeepSeek 返回 `BadRequestError: "The reasoning_content in the thinking mode must be passed back to the API."`。
- **修复**：`llm.chat()` 用 `getattr(msg, "reasoning_content", None)` 把字段读出来挂在返回 dict；`agent_node` 把它写进 assistant message。非推理模型字段为 `None` 自动跳过，**向后兼容 `deepseek-chat`**。

#### 偏离 4：`web_search` 扩展 + SYSTEM_PROMPT 动态化与强化

implement_plan 原本只要求 `web_search(query)` + Top-3 + 4000 字硬截断。实际使用中暴露两个问题：

1. 时效问题（如"ChatGPT 最新模型"）返回旧综述，模型用训练记忆脑补具体日期/版本号。
2. 不可搜场景（如"明天北京天气"）模型反复换 query 死循环。

修复（4 处一并）：

| 维度 | 改动 |
| --- | --- |
| 工具签名 | `web_search(query, topic="general", days=30)`；`TOP_K=5`；只在 `topic="news"` 时传 Tavily 的 `topic` / `days`；输出每条带 `(published_date)` 标记 |
| schemas | `WEB_SEARCH_SCHEMA` 增 `topic` (enum: general/news) 与 `days` 可选字段 |
| SYSTEM_PROMPT | 启动时 `date.today().isoformat()` 注入；新增「禁止使用训练记忆中具体日期/数字」「web_search 不是结构化数据 API（天气/股价/航班/汇率等遇到直接告知能力受限、不要循环搜）」「工具调用预算 5 次用完就停」三段约束 |
| 兜底 | `max_tool_calls=5` 在图层硬截断，模型即便不遵守 prompt 也会被路由层踢出 |

效果：「明天北京天气怎么样？」从无限 thinking↔tooling 死循环变为 0 次工具调用、3.5s 给出"能力受限 + 替代方案"答复。

---

## 运行说明（保持不变）

参见上文"运行说明（保留给后续接手者）"。`cagent` 首次运行时 `.workspace/` 会在当前 CWD 自动创建。

---

## Phase 4 — 未开始

### 下一步入口

Step 9：产品化封装。`pyproject.toml` 的 `[project.scripts] cagent = "cagent.cli:main"` 与 `pip install -e .` 已在 Phase 1-3 期间反复验证可用；剩下的事仅是新开终端跑一遍完整 ReAct+反思流程做最后冒烟。implement_plan §0.2 提到的 Typer 改造**已被实践证明不必要**（直接 `def main()` + entry_points 即可），可保留现状。

### 接手者请先做的事

1. 阅读本文件全部历史决策（特别是偏离 1-4）。
2. 阅读 `architecture.md` §2 各文件职责与 §4 依赖图。
3. 跑 implement_plan 附录 A 的 6 项手动验证清单。
