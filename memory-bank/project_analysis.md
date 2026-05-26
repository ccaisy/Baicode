# 项目分析：baicode 当前态

更新时间：2026-05-26

## 1. 项目定位

baicode 是一个 terminal-native 的 Python CLI AI Coding Agent。它把用户输入交给模型分诊，按任务复杂度选择单步 ReAct 或多步 Plan-and-Execute，并通过本地工具完成搜索、Python 执行和 shell 操作。

当前项目不是一个 Web 服务，也没有前端框架；交互面完全在终端。

## 2. 代码结构

```text
src/baicode/
├── cli.py                 # REPL 入口、banner、prompt_toolkit、Rich Markdown 渲染、顶层异常处理
├── config.py              # .env 配置加载与必需 Key 校验
├── llm.py                 # LiteLLM 网关、异常分级、reasoning_content 回传
├── tools/
│   ├── python_exec.py     # 本地 Python 子进程执行
│   ├── shell_exec.py      # 本地 shell 子进程执行
│   ├── web_search.py      # Tavily 搜索
│   └── schemas.py         # OpenAI function calling schema
└── graph/
    ├── builder.py         # 微图/宏图构建、路由、公共 run()
    ├── nodes.py           # agent_node / tool_node
    ├── planner.py         # 0-5 步规划与分诊
    ├── react.py           # 0/1 step 直通 ReAct，含预算耗尽 fail-soft
    ├── executor.py        # 多步计划逐步执行
    ├── replanner.py       # 失败后补救或 abort
    ├── finalizer.py       # 多步执行结果汇总
    └── state.py           # AgentState TypedDict
```

根目录还有：

- `pyproject.toml`：包元信息、依赖、`baicode` 入口。
- `eval_runner.py`：真实 LLM 自动评测脚本。
- `README.md`：对外说明。
- `docs/banner.png`：README 视觉资源。
- `memory-bank/`：项目长期上下文和交接文档。

当前工作树里还有未跟踪的 `test.py` 和 `uv.lock`。它们没有被现有文档当作核心源码路径，也没有被我纳入本次同步范围。

## 3. 运行链路

1. `baicode` 进入 `cli.main()`。
2. `load_config()` 从当前目录向上找 `.env`，校验 `DEEPSEEK_API_KEY` 和 `TAVILY_API_KEY`。
3. CLI 初始化主对话 `messages = [system]`。
4. 用户输入后追加 `user` 消息，调用 `graph.builder.run(messages)`。
5. Macro graph 先进入 `planner_node`：
   - `len(plan) <= 1`：进入 `react_node`。
   - `len(plan) >= 2`：进入多步 plan 路径。
6. React 路径直接调用 `_run_micro()`，只把最后 assistant 内容写回主对话。
7. Plan 路径由 Executor 每次取 `plan[0]`，构造隔离消息调用 `_run_micro()`；失败则 Replanner 决定补救或 abort；最终由 Finalizer 汇总。
8. CLI 使用 `render_typewriter()` 渲染最后 assistant 回复。

## 4. 当前能力边界

已具备：

- 多轮终端对话。
- Markdown + 代码块高亮输出。
- OpenAI function calling 工具协议。
- Python / shell / web_search 三类工具。
- 工具失败反思重试。
- 多步规划、逐步执行、失败补救和最终总结。
- 对实时结构化数据请求的 prompt 防护和预算耗尽兜底。

尚未具备：

- Docker 沙箱。
- 真流式模型输出。
- pytest 自动化测试套件。
- 跨 plan 全局取消。
- 多模型角色分工。
- 主对话历史压缩。

## 5. 风险与维护重点

- **本地命令权限风险**：`shell_exec` 和 `python_exec` 继承调用方权限，适合本地开发 MVP，不适合直接作为多用户服务暴露。
- **Planner 抖动**：路径分诊依赖 LLM，`planner.py` 的 prompt 是关键回归点。改动后应重点跑 `eval.md` A/L 章。
- **实时数据请求**：H-01 / E-02 曾经不稳定。改 `_SYSTEM_PROMPT_TEMPLATE` 或 `react.py` 后应回归相关 case。
- **上下文增长**：多轮主对话不会保存 tool 中间消息，但 assistant 最终回复仍会无限增长；长会话可能需要 summarize。
- **跨平台 shell 行为**：`shell=True` 在 macOS/Linux 与 Windows 使用不同默认 shell。`cli.py` 和 `schemas.py` 已根据 `sys.platform` 生成不同提示，但 `shell_exec.py` 本身没有显式固定 shell。

## 6. 推荐接手顺序

1. 读 `memory-bank/architecture.md` 了解文件职责和图结构。
2. 读 `memory-bank/progress.md` 的偏离 14、15，理解当前分诊和 fail-soft 的来龙去脉。
3. 运行静态导入或 compile 检查，确认环境基础可用。
4. 涉及行为改动时跑 `python eval_runner.py`；涉及 Ctrl+C 的改动还需要真实 TTY 手测。
