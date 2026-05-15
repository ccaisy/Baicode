# 架构与文件职责 (Architecture)

本文档**逐文件**说明每个文件的角色、关键导出、依赖方向。Phase 演进时持续增补；后人改动 src 时请同步更新本文件。

---

## 1. 仓库根目录

| 路径 | 作用 |
| --- | --- |
| `pyproject.toml` | 包元信息（name=`cagent`、`requires-python>=3.10`）、依赖（`python-dotenv` / `prompt_toolkit` / `rich` / `litellm`）、`[project.scripts] cagent = "cagent.cli:main"` 入口、`tool.setuptools.packages.find` 配 src 布局 |
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
| `DEFAULT_MODEL` | `str` 常量 | `"deepseek/deepseek-chat"` |
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
| `chat(messages, config=None, tools=None) -> dict` | 单次模型调用 | 返回 `{"role": "assistant", "content": str, "tool_calls": Optional[list]}` |
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
| `SYSTEM_PROMPT` | `str` 常量 | 系统提示词；当前仅为简短角色设定，Phase 3 接入工具时需要扩写 |
| `HISTORY_PATH` | `str` 常量 | `~/.cagent_history` |

#### cli.py 启动流程

1. 创建 `rich.console.Console`。
2. `sys.stdin.isatty()` 守卫 — 非 TTY 直接红字退出。
3. `load_config()` — 缺 Key 走 `MissingAPIKeyError` 红字退出。
4. 打印 banner（model 名 + 操作提示）。
5. 创建 `PromptSession(multiline=True, history=FileHistory(HISTORY_PATH))`。
6. 初始化 `messages = [{"role": "system", "content": SYSTEM_PROMPT}]`。
7. 进入 `while True` 主循环。

#### cli.py 主循环单步

```text
user_input  ──► strip / 空串跳过
            ──► messages.append({"role": "user", ...})
            ──► console.status("thinking...", spinner_style="cyan")
            ──► llm.chat(messages, config)
            ──► render_typewriter(content, style="green")
            ──► messages.append({"role": "assistant", ...})
```

#### cli.py 异常处理矩阵

| 异常 | 行为 |
| --- | --- |
| 顶层 `KeyboardInterrupt` / `EOFError` | 打印"再见。" + `return` |
| `FatalAuthError` | 红字 + `sys.exit(1)` |
| `ChatError` | 红字提示 + 弹出最后一条 user 消息（**保证 messages 序列洁净，下次重试不带脏数据**）+ `continue` |
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

- 上游依赖：`prompt_toolkit` + `rich` + `config` + `llm`。
- 被谁调：`pyproject.toml` 的 `cagent` 入口、`python -m cagent.cli`。

---

## 3. 运行时产物（**不入库**）

| 路径 | 何时创建 | 用途 |
| --- | --- | --- |
| `~/.cagent_history` | REPL 启动时 prompt_toolkit 自动创建 | 跨会话方向键历史 |
| `.workspace/temp_exec.py` | Phase 2 Step 4 落地后 | Python 执行器临时代码文件，覆盖写、不主动清理 |
| `.venv/` | 开发者 `python -m venv .venv` 后 | 开发环境 |

---

## 4. 调用方向（依赖图）

```text
                  ┌──────────────┐
                  │  cli.main()  │  入口
                  └──────┬───────┘
                         │
        ┌────────────────┼─────────────────────┐
        ▼                ▼                     ▼
  config.load_config   llm.chat        cli.render_typewriter
        │                │                     │
        ▼                ▼                     ▼
   python-dotenv     litellm                rich (Live + Text)
                        │
                        ▼
                  config.load_config
```

- **单向依赖、无环**。
- `prompt_toolkit` / `rich` / `litellm` 都是叶子依赖，彼此不互相调用。
- Phase 3 引入 `graph/builder` 后，调用链将变为：`cli.main → graph.builder.run(state) → graph.nodes.{agent_node, tool_node} → llm.chat / tools.*`。

---

## 5. 待添加文件（按 implement_plan 顺序）

| 路径 | 由哪个 Step 产出 | 角色草案 |
| --- | --- | --- |
| `src/cagent/tools/__init__.py` | Step 4 | 包占位 |
| `src/cagent/tools/python_exec.py` | Step 4 | `run_python(code) -> {stdout, stderr, returncode}`，subprocess + 10s timeout |
| `src/cagent/tools/web_search.py` | Step 5 | `web_search(query) -> str`，Tavily Top-3 + 4000 字符截断 |
| `src/cagent/tools/schemas.py` | Step 4-5 | OpenAI tools schema 集中定义 |
| `src/cagent/graph/__init__.py` | Step 6 | 包占位 |
| `src/cagent/graph/state.py` | Step 6 | `AgentState (TypedDict)`：messages / error_count / retry_limit |
| `src/cagent/graph/nodes.py` | Step 6-8 | `agent_node` / `tool_node`（手写，**禁用 prebuilt ToolNode**） |
| `src/cagent/graph/builder.py` | Step 6-7 | LangGraph 图构建 + 条件边路由 |
