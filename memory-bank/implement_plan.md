# 实施计划：CLI AI Coding Agent (MVP 版本)

> 本文是落地执行手册。0 节为全局约定（**所有 Step 共用，遇歧义以此为准**），其后按阶段展开具体步骤。

---

## 0. 全局决策与约定

### 0.1 项目目录结构（采用 `src/` 隔离布局）

```
myagent/
├── .env                          # 各类 API Key（不入库）
├── .gitignore
├── pyproject.toml                # 包元信息 + 入口脚本 baicode
├── memory-bank/                  # 文档
└── src/
    └── baicode/
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
| CLI 入口命令名 | `baicode` |
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
  - 创建 Python 3.10+ 虚拟环境，初始化 `pyproject.toml`（包名 `baicode`，采用 §0.1 的 src 布局）。
  - 引入 `python-dotenv`，在 `src/baicode/config.py` 实现 `load_config()`：读取 `.env` 中的 `DEEPSEEK_API_KEY`、`TAVILY_API_KEY`（必需），`OPENAI_API_KEY`（可选）。
  - 任一必需 Key 缺失时抛出自定义异常 `MissingAPIKeyError`，错误信息明确指出缺哪个 Key。
- **测试**：
  - 构造完整 `.env`，断言 `load_config()` 正常返回。
  - 删除某个必需 Key，断言抛出 `MissingAPIKeyError` 且信息可读。

### Step 2: 构建 REPL 基础交互循环

- **指令**：
  - 在 `src/baicode/cli.py` 用 `prompt_toolkit` 构建持续监听的无限循环。
  - **多行输入**：`multiline=True`，提交快捷键绑定 **`Alt+Enter` (Meta+Enter)**。
  - **历史持久化**：`FileHistory("~/.baicode_history")`，支持方向键上下翻历史。
  - 顶层捕获 `KeyboardInterrupt`，打印优雅退出提示后结束进程，**不允许堆栈外泄**。
- **测试**：
  - 单行输入回显正常。
  - 粘贴多行文本块，按 Alt+Enter 一次性提交。
  - 按 Ctrl+C，验证仅看到退出提示，无 traceback。
  - 重启 CLI，验证上下方向键可调出上次历史。

### Step 3: 接入多模型调用层（伪流式渲染）

- **指令**：
  - 在 `src/baicode/llm.py` 封装 `chat(messages: list, tools: list | None = None) -> dict`，底层调用：
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
  - `src/baicode/tools/python_exec.py` 暴露 `run_python(code: str) -> dict`。
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
  - `src/baicode/tools/web_search.py` 暴露 `web_search(query: str) -> str`。
  - 调用 `tavily-python`，提取 **Top-3** 结果，每条按 `"[url]\ncontent\n"` 拼接，**整体施加 4000 字符硬截断**保护上下文。
  - 在 `tools/schemas.py` 暴露 OpenAI tools schema（参数 `query: string`）。
- **测试**：
  - 查询当日时效新闻，断言返回字符串含预期关键词、不超过 4000 字符。

---

## 阶段三：工作流状态机编排 (Milestone 2 & 3)

利用图结构串联前面的组件，构建带有 ReAct 和反思机制的大脑。

### Step 6: 定义状态图结构与基础节点

- **指令**：
  - `src/baicode/graph/state.py` 落地 §0.3 的 `AgentState`。
  - `src/baicode/graph/nodes.py` 实现 `agent_node`：调用 `llm.chat(messages, tools=[python_exec_schema, web_search_schema])`，将返回 assistant message 追加到 `messages`，回写新 state。
  - `src/baicode/graph/builder.py` 构建最小图：`START → agent_node → END`，预留条件边接口供 Step 7 接入。
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
    baicode = "baicode.cli:main"
    ```
  - `cli.py` 的 `main()` 使用 `Typer` 注册为默认命令（无子命令时直接进入 REPL）。
  - 在开发环境执行 `pip install -e .` 完成可编辑安装。
- **测试**：
  - 开启新独立终端，键入 `baicode`，断言瞬间进入 REPL。
  - 在新终端中完整跑一遍 ReAct 流程（含工具调用 + 反思）。

---

## 阶段五：Markdown 渲染与代码块语法高亮

> **目标**：把当前 `cli.py::render_typewriter` 的纯字符流打字机升级为**流式 Markdown 渲染器**：模型回复中的标题、粗体、斜体、列表、链接、行内代码以富文本呈现；围栏代码块走 pygments 语法高亮（主题 `monokai`）。
>
> **范围内**：仅改动 `src/baicode/cli.py`（`render_typewriter` 内部逻辑 + `_SYSTEM_PROMPT_TEMPLATE` 末尾追加一句）。**不新增源码文件**、**不新增第三方依赖**（pygments 是 Rich 的传递依赖，安装 Rich 时已带入）。
>
> **设计取舍**（覆盖 §0.4 表格中 Response 行的 "green 打字机" 决策）：
>
> - 取消对最终回复整体染 `green`；普通段落使用 Rich 默认前景色，富文本样式（粗体、斜体、代码块背景、链接下划线）由 Markdown 自身生效。
> - 打字机机制保留：每追加 1 个字符后调用 `Live.update(...)`，把已累积的完整 buffer 重新交给 `rich.markdown.Markdown` 重渲染一次。
> - Ctrl+C 渲染期不退出 REPL 的契约保持不变。

### Step 10：依赖核对与 Markdown 渲染探针

- **指令**：
  - 在已激活 venv 内用 `pip show pygments` 确认 pygments 已被 Rich 传递安装；用 `pip show rich` 确认 Rich 版本满足 `pyproject.toml` 中的 `>=13.7.0`。**不要**把 pygments 显式加进 `pyproject.toml`。
  - 准备一段一次性 Markdown 探针字符串，至少包含以下元素：1 个 `##` 标题、1 段含粗体与斜体的句子、1 段含行内代码的句子、1 个无序列表（≥3 项）、1 个标注 `python` 的围栏代码块、1 行含 `<` `>` `&` 特殊字符的纯文本。
  - 在 venv 内用一次性 `python -c` 把探针字符串交给 `rich.markdown.Markdown` 并通过 `rich.console.Console().print(...)` 输出。**只验证 Rich 本身的渲染行为，不接入 baicode 任何模块**。
- **测试**：
  - 肉眼检查终端输出：标题字号或粗细可见、粗体加粗、斜体倾斜、行内代码有底色框、列表带圆点、围栏代码块出现 monokai 配色的关键字与字符串高亮、`<` `>` `&` 三字符正常显示且未引发 traceback。
  - 任意一项不通过：检查 Rich/pygments 是否真的装到当前 venv（不是系统 Python）；版本不达标则在本 Step 内升级，**不进入 Step 11**。

### Step 11：把 `render_typewriter` 改造为流式 Markdown 渲染器

- **指令**：
  - 在 `src/baicode/cli.py` 修改既有的 `render_typewriter(text, console, style=..., delay=...)`：
    - 保持函数名、形参顺序、调用方位置完全不变（`cli.py::main()` 唯一调用点不动）。
    - 把 `style` 形参的默认值由 `"green"` 改为 `None`，并在文档/注释里说明：自 Phase 5 起 `style` 仅作 fallback，整体不再强制染色，Markdown 内部样式优先。
  - 函数内部实现要点（**自然语言描述，禁止本文档出现真实 Python 代码**）：
    1. 维护一个累积字符串变量，初始为空。
    2. 进入一次 `rich.live.Live` 上下文，沿用现有的 `refresh_per_second=24`。
    3. 按字符遍历入参 `text`：每追加 1 个字符到累积字符串后，构造一个 `rich.markdown.Markdown` 实例（指定 `code_theme="monokai"`），用 `Live.update(...)` 把该实例作为新的可渲染对象交给 Live。
    4. 每个字符之间 `time.sleep(delay)`，`delay` 默认值沿用 0.005。
    5. 循环结束后 Live 自动退出，让最终态 Markdown 留在 stdout。
  - 顶层 `try/except KeyboardInterrupt`（在 `cli.py::main()` 包裹 `render_typewriter` 的那段）行为保持不变。
- **测试**：
  - 写一个**仅供本 Step 验证的临时手动脚本**（不入库、不写文档）：构造一段 ~400 字符的 Markdown，包含粗体、斜体、行内代码、1 个 ```python 围栏代码块、1 个无序列表，直接调用 `render_typewriter`（不经过 graph、不经过 LLM）。
  - 验收项（全部满足才通过）：
    1. 字符自左向右逐个出现，肉眼能感到打字机节奏。
    2. 围栏闭合（出现配对的尾部 ```）那一刻，代码块整体切换为彩色高亮；高亮前可以是纯文本，**但代码块不能逐字带高亮闪烁**——若闪烁严重则视为 Step 12 性能问题，标记后继续。
    3. 列表 bullet、粗体、斜体在到达对应 Markdown token 后立即生效。
    4. 渲染结束无 traceback、终端无残留 ANSI 控制序列。

### Step 12：长文渲染的性能与节流验证

- **指令**：
  - 由于"每字符触发 1 次完整 Markdown 重解析"是该方案的天然代价，必须核实长回复不卡。
  - 写一个一次性手动脚本：构造一段长度约 4000 字符的 Markdown，至少含 3 个独立的 ```python 围栏代码块、≥20 行无序列表、若干粗体与行内代码。
  - 调用 `render_typewriter` 渲染该字符串，用 `time.monotonic()` 同时记录：
    - **总耗时** `wall_time`。
    - **单帧最大停顿** `max_gap`：在每次 `Live.update(...)` 调用前后采样时间戳，所有相邻两次 update 的时差中取最大值。
  - 期望基线：
    - `wall_time ≈ len(text) * delay`（4000 × 0.005 = 20s，主要由 `time.sleep` 贡献）；总偏差控制在 ±20% 之内。
    - `max_gap < 100ms`（除去 sleep 占用之后的 Markdown 解析 + 输出本身不超过 100ms）。
  - 不达标处理（任选其一，**不允许同时启用两项**）：
    - 方案 A：把 `delay` 默认值从 0.005 调到 0.002，整体压缩至 ~8s。
    - 方案 B：把 update 粒度从「每字符一次」改为「累计到换行符或 Markdown 块边界（例如 ```、`\n\n`）时才 update 一次」；字符级 `sleep` 保留以保持视觉节奏，但 Markdown 解析次数显著减少。
  - 实施完缓解方案后，**在本 Step 内用同一段 4000 字字符串重跑一次**，确认达标。
- **测试**：
  - 打印 `wall_time` 与 `max_gap` 两个数。
  - 通过判据：`wall_time` 偏差 ±20% 之内；`max_gap < 100ms`。
  - 不通过：回到本 Step 切换或调整缓解方案后重测。

### Step 13：联通主循环，真实 LLM 端到端验证

- **指令**：
  - `cli.py::main()` 不做任何代码改动；`render_typewriter` 的对外签名已保持兼容。
  - 在真实终端启动 `baicode`，依次输入下面两条用户消息，**每条独立观察**：
    1. "请用 Markdown 列出 Python 中常见的循环结构（for 和 while），并为每种结构给一个简短的 Python 代码示例。"
    2. "用三句话解释什么是大整数运算，请把其中两个关键术语用粗体标出。"
- **测试**：
  - 第 1 条期望：终端看到带圆点的列表、两个独立的 ```python 代码块且关键字着色、无任何裸 ```、`**`、`_`、`#` Markdown 标记残留。
  - 第 2 条期望：粗体在两个关键词上加粗生效；其余文本为终端默认色（不是 green）。
  - 任一条仍出现裸 Markdown 标记 → 渲染未真正生效，回到 Step 11 检查 `Live.update(...)` 的入参是否真的是 `Markdown` 实例而非 `Text` 实例。

### Step 14：边角 case 与异常路径

- **指令**：
  - 写一个一次性手动脚本，**依次**用 4 段 mocked content 调用 `render_typewriter`：
    1. 一段含 `if a < b and c > d & e:` 的行内代码段落（验证 HTML 特殊字符不被 Rich 当作 markup 解析也不被吞掉）。
    2. 一段未闭合的围栏代码块（以三反引号 + `python` 开头、内含 `print("hi")`、**不带**收尾的三反引号）。
    3. 空字符串 `""`。
    4. 一段不含任何 Markdown 标记的纯文本（约 80 字符）。
  - 接着在真实 REPL 触发一次长回复（如让模型写一段较长的解释），在打字机渲染过程中按 Ctrl+C。
- **测试**：
  - 子测试 1：`<` `>` `&` 三字符在最终输出中肉眼可见，且未引发 traceback。
  - 子测试 2：函数返回时**不抛异常**；剩余文本可被当成代码或当成普通段落，两种行为均可接受，**唯一硬要求是不崩溃**。
  - 子测试 3：函数立即返回；Live 上下文正常进入又退出；终端无残留光标、无空白行堆积。
  - 子测试 4：作为对照基准，逐字推进、无任何 Markdown 样式生效，视觉与 Phase 4 之前的字符流打字机一致。
  - REPL 渲染期 Ctrl+C：终端仅打印一个换行收尾，下一行立即看到 `You ▷` 提示符，REPL 不退出、不打印 traceback。

### Step 15：SYSTEM_PROMPT 微调，引导模型产出带语言标注的围栏代码块

- **指令**：
  - 在 `cli.py::_SYSTEM_PROMPT_TEMPLATE` 字符串末尾追加 1 句指引（与现有英文行风格一致即可，例如："When you output code, always wrap it in fenced code blocks with an explicit language tag (e.g. ```python …``` or ```bash …```), so the CLI can syntax-highlight it."）。
  - 不调整 prompt 的其他约束条款。
- **测试**：
  - 在真实 REPL 输入"写一段 Python 代码计算前 10 个斐波那契数，并解释关键步骤"。
  - 验收项：
    1. 模型回复中的 Python 代码块带 `python` 语言标注，肉眼能看到关键字 `def` / `for` / `print` 以及字符串字面量分别着色。
    2. 如回复中出现 shell 命令示范（例如 `pip install ...`），该代码块带 `bash` 标注。
  - 若模型在该 prompt 下仍输出无语言标记的围栏代码块：在本 Step 内向 system prompt 同一行追加一句"This is mandatory, not optional."并重测 1 次；若仍未达标，视为模型策略局限、**Phase 5 范围内不再扩展**，将其记为已知限制写入 progress。

### 阶段五完成判据

- `cli.py::render_typewriter` 已替换为流式 Markdown 渲染器，签名兼容、调用点不变。
- 附录 A 的 6 项手动验证清单在 Phase 5 完成后**全部重跑 1 次**仍通过。
- 仅 1 个源码文件被改动：`src/baicode/cli.py`（render_typewriter 内部逻辑 + system prompt 末尾追加 1 句）。
- 无新增源码文件、无新增第三方依赖。
- `memory-bank/progress.md` 与 `memory-bank/architecture.md` 已同步更新：标注 §0.4 表格中 "Response → green 打字机" 已被覆盖为 "Response → Markdown 流式渲染 + monokai 代码高亮"；记录 Step 12 最终选用的节流方案（A 或 B）以及 Step 15 是否触发"已知限制"分支。

---

# Phase 6: 终端交互能力 (Shell Execution) 基础实现
## Step 1: 构建底层 Shell 执行器
### 行动计划
1. 在工具目录下新建一个专门处理终端执行的文件。
2. 利用 Python 标准库中的子进程管理模块来接收并执行字符串形式的系统命令。这里必须开启允许通过 Shell 解释器执行的选项，以支持管道符和逻辑与（&&）等基础特性。
3. 设定一个强制的超时机制（例如 15 秒）。捕获超时异常，并在返回的错误信息中明确提示“执行超时，请确保命令非交互式”。
4. 实现输出硬截断逻辑。由于系统命令（如查阅日志）极易产生数万行的输出，必须在捕获到标准输出和标准错误后，检查其长度。如果超长，则仅保留开头和结尾各一部分（中间用提示符替换），以保护后续传递给模型时的上下文窗口不被撑爆。

### 验证测试
- 独立单元测试（不经过大模型）：编写一个一次性的测试脚本直接调用该底层函数。
- 传入基础命令（如打印一段字符串），期望正确返回标准输出。
- 传入会导致挂起的命令（如休眠 20 秒），期望 15 秒后函数安全返回并携带超时错误信息。
- 传入一条会打印巨量文本的命令（如循环打印一万行内容），期望返回的字符串被成功截断且包含截断提示。

## Step 2: 定义工具的 Schema 并暴露接口
### 行动计划
1. 在统一管理工具架构描述（Schema）的文件中，为新完成的 Shell 执行器新增一个描述字典。
2. 该 Schema 需要符合之前已有的结构标准，清晰定义工具名称、工具的用途描述，以及它所需要的参数（一个代表完整终端命令的字符串类型参数）。
3. 将该 Schema 加入到全局允许大模型调用的工具列表中。

### 验证测试
- 结构断言测试：在 Python 交互式环境中导入全局工具列表，人工检查该列表的长度是否增加了 1，并且新增的 Schema 字典中，必填参数项是否正确指向了命令字符串。

## Step 3: 工作流图节点 (Graph Nodes) 集成与路由
### 行动计划
1. 在定义 LangGraph 节点的文件中，导入刚建好的 Shell 执行器函数和对应的 Schema。
2. 找到现有的处理工具调用的节点（即解析模型输出并分发给具体本地函数的那个节点）。
3. 在该节点的分发逻辑中增加一个新的分支条件：当大模型请求的函数名与新工具的 Schema 名称匹配时，提取其中的命令参数，传递给 Step 1 写好的底层执行器。
4. 确保执行器的返回结果（无论成功、报错还是超时截断）都能以相同的格式打包成观察结果（Observation），写回到图的状态（State）中，供下一轮反思或决策使用。

### 验证测试
- Mock 路由测试：构造一个模拟的大模型返回状态（假装大模型决定调用新的 Shell 工具执行列出当前目录内容的命令），将其喂给你的工具处理节点。验证节点能够正确捕获该请求，触发真实的目录读取，并将结果写回新的状态消息列表中。

## Step 4: 更新系统提示词 (System Prompt) 以规避环境陷阱
### 行动计划
1. 打开存放全局系统提示词的文件或配置。
2. 在提示词末尾新增专门针对终端工具的约束守则。
3. 约束一（状态隔离）：明确告知模型，每次终端调用都是独立的进程，单独使用切换目录的命令是无效的。要求它必须使用逻辑与（&&）将目录切换和后续操作串联在同一条命令中执行。
4. 约束二（阻塞防范）：严禁模型调用任何需要人工交互的工具（如文本编辑器、分页查看器），并要求在执行安装等可能需要确认的命令时，主动附加自动确认的参数。

### 验证测试
- 端到端联调测试：启动你的命令行代理（CLI），给它下达一个需要多步系统操作的任务。例如：“请在当前目录下创建一个名为 test_agent_dir 的新文件夹，进入该文件夹，新建一个空的 hello.txt 文件，然后列出该文件夹的内容。”
- 期望结果：模型能够一次性规划出正确的串联命令，或者通过多次工具调用成功完成操作，且终端不会因为等待输入而卡死，最终能看到创建好的文件和目录。


## 附录 A：贯穿所有 Step 的手动验证清单

| # | 场景 | 期望结果 |
| --- | --- | --- |
| 1 | 错误 API Key 启动 | 鉴权致命错误，进程优雅退出 |
| 2 | 断网状态下输入指令 | 模型层报网络错误，REPL 存活 |
| 3 | REPL 输入态按 Ctrl+C | 打印退出提示，干净结束 |
| 4 | 工具执行态按 Ctrl+C | 子进程被杀、REPL 存活、模型收到中断 Observation |
| 5 | 连续 3 次工具失败 | 第 4 次循环被强制中断，提示 "Reflection retries exceeded" |
| 6 | 新终端键入 `baicode` | 行为与 `python -m baicode.cli` 完全一致 |

## 附录 B：MVP 明确不做的事

- Plan-and-Execute 多步规划（延后到下一里程碑）。
- pytest 自动化测试套件（仅手动验证）。
- YAML / 全局 `~/.config/agent/config.yaml`（仅 `.env`）。
- 流式 tool_call chunk 解析（统一 `stream=False`）。
- 工具结果在终端的可视化打印（Observation 全程静默）。
- Docker / 沙箱隔离（直接复用当前 venv）。
