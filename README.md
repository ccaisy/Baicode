# baicode

> 一个 terminal-native 的 CLI AI Coding Agent —— 让大模型在本地终端里直接思考、写代码、调工具、跑命令。

![baicode banner](docs/banner.png)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/) [![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE) [![Model](https://img.shields.io/badge/Model-DeepSeek--v4--flash-purple.svg)](https://platform.deepseek.com/)

## 简介

baicode 是基于 [LangGraph](https://github.com/langchain-ai/langgraph) + [LiteLLM](https://github.com/BerriAI/litellm) 构建的极简 CLI Agent。设计哲学是 **"把复杂度交给模型，把确定性留给代码"**：

- 一个全局命令 `baicode` 即可启动 REPL；
- 模型可调用 `python_exec` / `shell_exec` / `web_search` 三个原生工具；
- 内置 ReAct + Reflection 自愈微图 + Plan-and-Execute 宏图，复杂任务自动拆步；
- 终端原生 Markdown 流式渲染 + 代码块 monokai 高亮 + 打字机视觉节奏。

## Features

| 特性 | 说明 |
| --- | --- |
| **多模型支持** | LiteLLM 统一接入，默认 `deepseek/deepseek-v4-flash`，一行配置切换 Gemini / Claude / GPT |
| **Plan-and-Execute 双层架构** | Planner 自动分诊：0/1 step 走 ReAct 直通；2+ step 走 Executor / Replanner / Finalizer 宏图 |
| **3 个原生工具** | `python_exec`（10s 超时）、`shell_exec`（60s 超时、cd 用 `&&` 串联）、`web_search`（Tavily 优化的搜索 API） |
| **Reflection 自愈** | 工具失败自动反思修正，3 次预算内自动重试；超限友好降级 |
| **Replanner 动态修补** | 复杂任务某步失败时，LLM 决策插入补救步或 abort，避免死循环 |
| **Rich Markdown 渲染** | 流式打字机 + 标题/列表/粗体/代码块 monokai 高亮；4000 字回复秒级渲染 |
| **Ctrl+C 三级中断** | 输入态：干净退出；工具态:杀子进程保 REPL；渲染态：仅换行收尾 |
| **真实工作目录** | 工具操作直接落在用户启动 `baicode` 的目录，所见即所得 |

## 快速开始

### 前置依赖

- **Python**：3.10+
- **API Keys**：
  - `DEEPSEEK_API_KEY` —— 默认 LLM，[DeepSeek Platform](https://platform.deepseek.com/) 申请
  - `TAVILY_API_KEY` —— web_search 工具，[Tavily](https://tavily.com/) 申请（免费 1000 次/月）
- **macOS Terminal 用户**：勾选 "Use Option as Meta key"（iTerm2 默认 OK）以支持 `Alt+Enter` 提交多行

### 安装

```bash
git clone https://github.com/ccaisy/baicode.git
cd baicode

python -m venv .venv
source .venv/bin/activate   # Windows 用 .venv\Scripts\activate

pip install -e .
```

`pip install -e .` 会注册全局命令 `baicode`，并把 `src/baicode/` 以 editable 模式安装到当前 venv。

### 配置 API Key

```bash
cp .env.example .env
# 编辑 .env 填入你的 DEEPSEEK_API_KEY 与 TAVILY_API_KEY
```

`.env` 已加入 `.gitignore`，不会被误提交。

### 启动

```bash
baicode
```

也可以用 `python -m baicode.cli`，效果完全相同。

## 使用

| 操作 | 快捷键 |
| --- | --- |
| 提交输入（含多行粘贴） | `Alt+Enter` / `Option+Enter` |
| 翻历史命令 | `↑` / `↓` |
| 中断当前工具执行 | `Ctrl+C`（不会退出 REPL） |
| 退出 REPL | 输入态按 `Ctrl+C` 或 `Ctrl+D` |

历史记录持久化到 `~/.baicode_history`，跨会话保留。

### 切换模型

编辑 `src/baicode/config.py` 中的 `DEFAULT_MODEL`，例如：

```python
DEFAULT_MODEL = "gemini/gemini-2.0-flash"      # 需 GEMINI_API_KEY
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"  # 需 ANTHROPIC_API_KEY
DEFAULT_MODEL = "openai/gpt-4o"                # 需 OPENAI_API_KEY
```

LiteLLM 自动处理鉴权 / schema 转换。完整模型列表见 [LiteLLM Providers](https://docs.litellm.ai/docs/providers)。

## 架构概览

```
┌────────────────────────────────────────────────────────────────┐
│                    cli.main() — REPL 入口                       │
│            (prompt_toolkit + Rich Markdown 流式渲染)             │
└────────────────────────────┬───────────────────────────────────┘
                             │ messages.append(user)
                             ▼
                    graph.builder.run(messages)
                             │
       ┌─────────── Macro Graph (Phase 7) ───────────┐
       ▼                                             │
   planner_node ──分诊──┬──► react_node ──► END     │  ← 0/1 step
                       │                             │     直通
                       └──► executor_node            │
                              ↑          ↓           │  ← 2+ step
                              │      replanner       │     plan 路径
                              │          ↓           │
                              │      finalizer ──────┤
                              │                     │
                              └── _run_micro ───────┤
                                       │            │
                              ┌── Micro Graph ──┐   │
                              ▼                 ▼   │
                          agent_node ◄──── tool_node│
                              │              │      │
                              ▼              ▼      │
                           llm.chat       python_exec
                          (litellm)       shell_exec
                                          web_search
       ────────────────────────────────────────────────
```

- **Macro Graph (Phase 7)**：Planner 把用户请求拆成 0-5 步任务清单。0/1 step 走 react 直通（chitchat / 单步任务）；2+ step 进入 Executor / Replanner / Finalizer 循环。
- **Micro Graph (Phase 1-6)**：经典 ReAct + Reflection 闭环。Executor 每步注入"全新隔离 messages"调用微图，使每步预算独立。
- **复用零修改**：Phase 7 在微图之上叠加宏图层，`agent_node` / `tool_node` 一行未动。

完整设计与各文件职责见 [`memory-bank/architecture.md`](memory-bank/architecture.md)。

## 工具

| 工具 | 用途 | 关键约束 |
| --- | --- | --- |
| `python_exec(code)` | 在当前 venv 子进程跑 Python 脚本 | 10s 超时；stdout/stderr 独立返回；`.workspace/temp_exec.py` 覆盖写 |
| `shell_exec(command)` | 通过系统默认 shell 跑命令（Unix/macOS 通常 `/bin/sh`，Windows 为 `cmd.exe`） | 60s 超时；每次独立子进程（cd 必须 `&&` 串联）；stdout/stderr 各 4000 字截断；禁交互式命令；安装类命令必须非交互 |
| `web_search(query, topic, days)` | Tavily 网络搜索 | Top-5 结果，整体 4000 字硬截断；`topic="news"` 触发时效过滤；**不是结构化数据 API**（天气/股价等直接告知能力受限） |

## 评测

仓库根目录的 [`eval_runner.py`](eval_runner.py) 用真实 DeepSeek API 跑 45 个 case（A-L 共 12 章覆盖路径分诊 / ReAct / Plan / Reflection / Replanner / 工具边界 / 多轮 / 鲁棒性 / 模型合规性）：

```bash
python eval_runner.py
```

最近一次完整自动化评测为 **42/45 = 93.3% PASS**（2026-05-17）；之后已针对 E-02 / H-01 实时结构化数据兜底做 6/6 精准验证，预期完整回归约 **~98%**。完整 case 清单 + 失败分析见 [`memory-bank/eval.md`](memory-bank/eval.md)。

## 项目状态

- [x] **Phase 1**：CLI 基建 + LiteLLM 网关 + .env 配置
- [x] **Phase 2**：python_exec / web_search 原生工具 + OpenAI schema
- [x] **Phase 3**：LangGraph 微图 + ReAct + Reflection 自愈
- [x] **Phase 4**：`pip install -e .` 全局命令打包
- [x] **Phase 5**：Markdown 流式渲染 + monokai 代码高亮
- [x] **Phase 6**：shell_exec 工具 + system prompt 守则加固
- [x] **Phase 7**：Plan-and-Execute 宏图（Planner / Executor / Replanner / Finalizer）+ react 分诊路径

Phase 8 候选方向（暂未规划）：pytest 自动化测试套件 / Docker 沙箱隔离 / Ctrl+C 跨步骤中断 / 多模型分工（Planner reasoning 强、Executor 便宜）/ History 自动 summarize。

## 项目文档

| 文档 | 内容 |
| --- | --- |
| [`memory-bank/product_requirements_document.md`](memory-bank/product_requirements_document.md) | 产品需求 (PRD) |
| [`memory-bank/tech_stack.md`](memory-bank/tech_stack.md) | 当前技术栈与取舍 |
| [`memory-bank/architecture.md`](memory-bank/architecture.md) | 各文件职责 + 依赖图 |
| [`memory-bank/project_analysis.md`](memory-bank/project_analysis.md) | 当前项目分析 + 运行链路 + 风险点 |
| [`memory-bank/implement_plan.md`](memory-bank/implement_plan.md) | 分阶段实施计划（Phase 1-7） |
| [`memory-bank/progress.md`](memory-bank/progress.md) | 进度日志 + 15 处架构偏离决策记录 |
| [`memory-bank/eval.md`](memory-bank/eval.md) | 评测集 + 失败 case 分析 |

## 已知限制

- **沙箱**：MVP 直接复用当前 venv，权限继承调用方。生产使用前建议加 Docker 容器隔离。
- **Ctrl+C 跨步骤**：当前只能中断单个工具，无法中断整个 plan 剩余步骤（Phase 8 候选）。
- **History 长度无上限**：长任务下宏图 `history` 列表会线性膨胀。
- **单模型**：Planner / Executor / Replanner / Finalizer 共用同一模型；可优化为按角色分模型。

## 贡献

欢迎 Issue 与 PR。改 `graph/*` / `cli.py` / `tools/*` 后请跑一遍 `python eval_runner.py` 回归。改架构 / 加偏离请同步更新 `memory-bank/progress.md`。

## License

[MIT](LICENSE) © 2026 baichuan
