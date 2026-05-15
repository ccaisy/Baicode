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

## Phase 2 ~ 4 — 未开始

### 下一步入口

Step 4：实现 `src/cagent/tools/python_exec.py`（subprocess Python 执行器，10s 超时，`.workspace/temp_exec.py` 覆盖写）。

### 接手者请先做的事

1. 阅读 `memory-bank/implement_plan.md` §0 全局决策、Step 4 详细要求。
2. 阅读本文件"偏离 implement_plan 的两处记录"理解既有兜底。
3. 阅读 `architecture.md` 把握现有依赖方向。
