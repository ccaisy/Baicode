"""Planner 节点：用户请求 → 0-5 步任务清单 (Phase 7 §1)."""

from __future__ import annotations

import json
from typing import Any

from rich.panel import Panel

from baicode.graph.nodes import _console
from baicode.llm import chat

PLAN_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "submit_plan",
        "description": (
            "Submit your decomposed plan for the user's request. Always call "
            "this tool exactly once; do not write free-form text. Use an "
            "empty steps array when the user message is simple chitchat, a "
            "greeting, or a single direct factual question that needs no "
            "tool use and no multi-step planning."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ordered list of 0 to 5 concrete sub-tasks. Each "
                        "step is an imperative sentence describing what to "
                        "accomplish (not which tool to call) with a clearly "
                        "verifiable outcome. Use an empty array for simple "
                        "chitchat. Use 1 task when the request needs a tool "
                        "but no real planning. Use 3-5 tasks for compound "
                        "work. Do NOT include a final 'summarize results' "
                        "step — the system handles that."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": "One short sentence explaining the decomposition.",
                },
            },
            "required": ["steps"],
        },
    },
}


_PLANNER_PROMPT = (
    "You are the Planner / triage of a coding agent. Given the user's "
    "latest message, decide how (and whether) to decompose it.\n"
    "\n"
    "★ CRITICAL RULE — this is the most common mistake, read first:\n"
    "\"Summarize / report / explain / 总结 / 简述 / 解释 the result\" is "
    "NEVER its own plan step. The downstream system automatically "
    "produces a user-facing summary at the end. If the user says "
    "\"查询 X 并总结要点\" / \"跑一下 Y 并报告结果\" / \"搜 Z 然后解释\", "
    "that is **ONE step (the action)**, NOT two. The reporting verb is "
    "implicit and MUST NOT appear as a plan step.\n"
    "\n"
    "Routing rules — pick the SMALLEST number of steps that fits:\n"
    "- Output empty array `[]` when the user message is:\n"
    "    * pure chitchat / greeting (\"你好\", \"thanks\")\n"
    "    * a factual question answerable from general knowledge with no "
    "      tool / file access (\"1+1=?\", \"what is Python\")\n"
    "    * any request that needs neither tool use nor planning.\n"
    "- Output exactly **1 step** when the entire task can be "
    "  accomplished by ONE action (one tool call sequence inside a "
    "  single ReAct loop). Examples: \"用 Python 算 1234567 × 7654321\", "
    "  \"搜一下 deepseek-v4 的最新版本号\", \"查今天的新闻并总结要点\", "
    "  \"跑一下 ./test.py 看看输出\", \"列出当前目录的文件\". When unsure "
    "  between 1 and N steps, prefer 1.\n"
    "- Output **3-5 steps** ONLY when the work genuinely touches "
    "  multiple files / tools / sequential phases where each phase's "
    "  output feeds the next, e.g. \"在新目录里写一个贪吃蛇并跑一遍验证\" "
    "  = create dir → write code → run & verify.\n"
    "\n"
    "Step content rules (apply when steps ≥ 1):\n"
    "- ALWAYS respond by calling the submit_plan tool exactly once. "
    "Never write free-form text.\n"
    "- Each step is ONE imperative sentence describing WHAT to "
    "accomplish, not WHICH tool to call.\n"
    "- Steps must be ordered so each one's output feeds the next.\n"
    "\n"
    "Examples:\n"
    "  User: \"你好\"\n"
    "    → submit_plan(steps=[])\n"
    "  User: \"用 Python 算 1+1\"\n"
    "    → submit_plan(steps=[\"运行 print(1+1) 并报告结果\"])\n"
    "  User: \"搜一下今天的全球新闻并简述要点\"\n"
    "    → submit_plan(steps=[\"搜索今天的全球新闻\"])  # 1 step, NOT 2 — 简述 is implicit\n"
    "  User: \"跑一下 my_script.py，看看会不会报错\"\n"
    "    → submit_plan(steps=[\"执行 my_script.py 并观察输出\"])  # 1 step\n"
    "  User: \"在当前目录新建 test_p7/，里面写一个能打印前 10 个斐波那契数的 fib.py，并运行验证\"\n"
    "    → submit_plan(steps=[\n"
    "        \"创建 test_p7/ 目录\",\n"
    "        \"在 test_p7/fib.py 写入打印前 10 个斐波那契数的 Python 代码\",\n"
    "        \"执行 test_p7/fib.py 并核对输出是否包含前 10 个斐波那契数\"\n"
    "      ])"
)


_PLANNER_RETRY_HINT = (
    "\n\nIMPORTANT: your previous attempt did not produce a valid "
    "submit_plan tool call. You MUST call the submit_plan tool with a "
    "well-formed `steps` array (use [] for chitchat). Do not output any "
    "free-form text."
)


def _extract_steps(raw: dict) -> list[str] | None:
    """从 chat() 返回的 dict 中提取 submit_plan 的 steps。

    返回 None 表示解析失败（无 tool_calls / 名字不对 / JSON 坏 / 字段缺失）。
    """
    tool_calls = raw.get("tool_calls")
    if not tool_calls:
        return None
    tc = tool_calls[0]
    if isinstance(tc, dict):
        name = tc.get("function", {}).get("name")
        args_str = tc.get("function", {}).get("arguments") or "{}"
    else:
        name = getattr(getattr(tc, "function", None), "name", None)
        args_str = getattr(getattr(tc, "function", None), "arguments", None) or "{}"
    if name != "submit_plan":
        return None
    try:
        args = json.loads(args_str)
    except json.JSONDecodeError:
        return None
    steps = args.get("steps")
    if not isinstance(steps, list):
        return None
    # Coerce each step to str, skip empties.
    out: list[str] = [str(s).strip() for s in steps if str(s).strip()]
    return out


def _render_plan_panel(plan: list[str]) -> None:
    # 仅在 plan ≥ 2 步时才打印 Panel：0/1 步走 react 路径，应保持 Phase 1-6
    # 原生 ReAct 的视觉（无 plan 字样）。详见 progress 偏离 14。
    if len(plan) <= 1:
        return
    body_lines = [f"{i}. {step}" for i, step in enumerate(plan, 1)]
    body = "\n".join(body_lines)
    _console.print(
        Panel(body, title="[bold cyan]📋 Plan[/bold cyan]", border_style="cyan")
    )


def planner_node(state: dict) -> dict:
    user_request = state["messages"][-1]["content"]

    planner_messages: list[dict[str, Any]] = [
        {"role": "system", "content": _PLANNER_PROMPT},
        {"role": "user", "content": user_request},
    ]

    with _console.status(
        "[dim cyan]planning...[/dim cyan]",
        spinner="dots",
        spinner_style="cyan",
    ):
        raw = chat(planner_messages, tools=[PLAN_SCHEMA])

    steps = _extract_steps(raw)

    if steps is None:
        # First parse failed: retry once with stricter prompt.
        retry_messages = [
            {"role": "system", "content": _PLANNER_PROMPT + _PLANNER_RETRY_HINT},
            {"role": "user", "content": user_request},
        ]
        with _console.status(
            "[dim cyan]planning (retry)...[/dim cyan]",
            spinner="dots",
            spinner_style="cyan",
        ):
            raw = chat(retry_messages, tools=[PLAN_SCHEMA])
        steps = _extract_steps(raw)

    if steps is None:
        # Still failed: fallback to a single-step plan with the raw user request.
        # 1-step falls into the react path (no Plan UX, pure ReAct), which is
        # the most permissive degradation when Planner output is unparseable.
        steps = [user_request]

    _render_plan_panel(steps)

    return {"plan": steps}
