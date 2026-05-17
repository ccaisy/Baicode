"""Executor 节点：取 plan[0] 跑一次微图 ReAct (Phase 7 §2)."""

from __future__ import annotations

from typing import Any

from baicode.graph.builder import (
    ReflectionRetriesExceeded,
    ToolCallBudgetExceeded,
    _run_micro,
)
from baicode.graph.nodes import _console

_EXECUTOR_ADDENDUM = (
    "\n\n--- EXECUTOR MODE ---\n"
    "You are executing a SINGLE step of a larger plan that another node has "
    "already decomposed. Stay focused: solve only the current task. Do not "
    "plan ahead, do not anticipate what the next step might be, do not act "
    "on tasks listed under 'Previously completed'. When you are done with "
    "the current task, your final assistant message MUST be a 1-3 sentence "
    "concise summary of WHAT you did and the KEY result/output. This summary "
    "is the only information that flows to the next step, so make it "
    "self-contained (mention key filenames, values, or findings explicitly) "
    "but keep it brief.\n"
    "If a tool fails repeatedly and the system aborts this step, that is "
    "fine — a Replanner will decide whether to insert a remedy step. Do "
    "not panic and do not chase fixes beyond the reflection budget."
)


def _format_history_brief(history: list[dict]) -> str:
    if not history:
        return "(this is the first step — no prior context)"
    lines: list[str] = []
    for i, entry in enumerate(history, 1):
        marker = "✓" if entry.get("status") == "success" else "✗"
        task = entry.get("task", "(missing task)")
        summary = entry.get("summary", "(no summary)")
        lines.append(f"{i}. [{marker}] {task}\n   → {summary}")
    return "\n".join(lines)


def _build_executor_messages(
    current_task: str,
    history: list[dict],
    base_system_prompt: str,
) -> list[dict[str, Any]]:
    history_brief = _format_history_brief(history)
    return [
        {
            "role": "system",
            "content": base_system_prompt + _EXECUTOR_ADDENDUM,
        },
        {
            "role": "user",
            "content": (
                f"Previously completed steps:\n{history_brief}\n\n"
                f"Your current task:\n{current_task}\n\n"
                "When you are done, your final reply must be a 1-3 sentence "
                "concise summary of what you did and the key result."
            ),
        },
    ]


def executor_node(state: dict) -> dict:
    plan: list[str] = state.get("plan") or []
    history: list[dict] = state.get("history") or []

    if not plan:
        # Defensive: routing should never send us here with an empty plan.
        return {}

    current_task = plan[0]
    step_num = len(history) + 1
    total = step_num + len(plan) - 1

    _console.print(
        f"[bold cyan]▶ Step {step_num}/{total}:[/bold cyan] [dim]{current_task}[/dim]"
    )

    # Deferred import to avoid circular: cli → builder → executor → cli.
    from baicode.cli import _build_system_prompt

    base_system = _build_system_prompt()
    executor_messages = _build_executor_messages(current_task, history, base_system)

    try:
        result_messages = _run_micro(
            executor_messages,
            retry_limit=state["retry_limit"],
            max_tool_calls=state["max_tool_calls"],
        )
        summary = (result_messages[-1].get("content") or "").strip() or "(empty)"
        status = "success"
    except (ReflectionRetriesExceeded, ToolCallBudgetExceeded) as exc:
        summary = f"Step aborted: {type(exc).__name__} — {exc}"
        status = "failed"

    new_history = list(history) + [
        {"task": current_task, "summary": summary, "status": status}
    ]
    new_plan = list(plan)[1:]

    return {
        "history": new_history,
        "plan": new_plan,
        "error_count": 0,
        "tool_calls_count": 0,
    }
