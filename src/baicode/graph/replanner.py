"""Replanner 节点：失败时决定补救或放弃 (Phase 7 §3)."""

from __future__ import annotations

import json
from typing import Any

from rich.panel import Panel

from baicode.graph.executor import _format_history_brief
from baicode.graph.nodes import _console
from baicode.llm import chat

REPLAN_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "submit_replan",
        "description": (
            "Decide how to recover from a step failure. Either insert "
            "fix-up tasks at the head of the remaining plan, or abort "
            "the whole task. Always call this tool exactly once."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["insert_remedy", "abort"],
                    "description": (
                        "'insert_remedy': add fix-up steps before retrying "
                        "the failed work. 'abort': give up the whole task "
                        "(use only when no realistic remedy exists)."
                    ),
                },
                "new_plan": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "When action='insert_remedy', this is the COMPLETE "
                        "new remaining plan: remedy step(s) FIRST, then the "
                        "original remaining steps (possibly amended). "
                        "When action='abort', use an empty array []."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": "One short sentence explaining the choice.",
                },
            },
            "required": ["action", "new_plan"],
        },
    },
}


_REPLANNER_PROMPT = (
    "You are the Replanner of a multi-step coding agent. The Executor "
    "just reported that a step FAILED. You must decide whether the "
    "overall task can be salvaged by inserting fix-up steps at the head "
    "of the remaining plan, or whether the whole task must abort.\n"
    "\n"
    "Rules:\n"
    "- ALWAYS call the submit_replan tool exactly once. Never write "
    "  free-form text.\n"
    "- Prefer 'insert_remedy' when the failure looks recoverable: missing "
    "  dependency (`pip install ...`), missing file/directory, wrong cwd, "
    "  needs a different approach for the same outcome, etc. Put the "
    "  remedy step(s) FIRST, then include the still-pending original "
    "  steps (you may amend their wording).\n"
    "- Use 'abort' only when no realistic remedy exists (e.g. the "
    "  failed step depends on something fundamentally unavailable, or "
    "  the user's request itself was impossible). On abort the system "
    "  will report partial progress to the user.\n"
    "- The originally failed step is NOT in the remaining plan anymore "
    "  (it was already popped). If you want to retry it, include a "
    "  reworded version of it in new_plan after any remedy steps.\n"
    "- Keep new_plan ≤ 6 steps total. Do not add a final \"summarize\" "
    "  step — the Finalizer handles that."
)


def _extract_replan(raw: dict) -> dict | None:
    """从 chat() 返回中提取 submit_replan 的 action + new_plan。

    返回 None 表示解析失败。
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
    if name != "submit_replan":
        return None
    try:
        args = json.loads(args_str)
    except json.JSONDecodeError:
        return None
    action = args.get("action")
    new_plan = args.get("new_plan")
    if action not in ("insert_remedy", "abort"):
        return None
    if not isinstance(new_plan, list):
        return None
    cleaned: list[str] = [str(s).strip() for s in new_plan if str(s).strip()]
    return {"action": action, "new_plan": cleaned}


def _render_new_plan_panel(new_plan: list[str]) -> None:
    if not new_plan:
        _console.print("[yellow]Replanner aborted: no recovery possible.[/yellow]")
        return
    body_lines = [f"{i}. {step}" for i, step in enumerate(new_plan, 1)]
    body = "\n".join(body_lines)
    _console.print(
        Panel(
            body,
            title="[bold yellow]🔄 Revised Plan[/bold yellow]",
            border_style="yellow",
        )
    )


def replanner_node(state: dict) -> dict:
    history: list[dict] = state.get("history") or []
    remaining_plan: list[str] = state.get("plan") or []
    replan_count: int = int(state.get("replan_count") or 0)

    # Pull the original user request and the failed step's summary.
    user_request = ""
    for msg in state.get("messages") or []:
        if msg.get("role") == "user":
            user_request = msg.get("content", "")
            break

    failed_entry = history[-1] if history else {}
    failed_task = failed_entry.get("task", "(unknown)")
    failed_summary = failed_entry.get("summary", "(no summary)")
    history_brief = _format_history_brief(history)
    remaining_brief = (
        "\n".join(f"- {s}" for s in remaining_plan) if remaining_plan else "(none)"
    )

    _console.print("[yellow]🔄 Replanning...[/yellow]")

    replanner_messages: list[dict[str, Any]] = [
        {"role": "system", "content": _REPLANNER_PROMPT},
        {
            "role": "user",
            "content": (
                f"Original user request:\n{user_request}\n\n"
                f"Full execution history so far:\n{history_brief}\n\n"
                f"The most recent step FAILED:\n"
                f"  task: {failed_task}\n  summary: {failed_summary}\n\n"
                f"Remaining steps (the failed step is NOT in this list):\n"
                f"{remaining_brief}\n\n"
                "Decide: insert_remedy (and provide the new full remaining "
                "plan) or abort (with new_plan=[])."
            ),
        },
    ]

    with _console.status(
        "[dim yellow]replanning...[/dim yellow]",
        spinner="dots",
        spinner_style="yellow",
    ):
        raw = chat(replanner_messages, tools=[REPLAN_SCHEMA])

    parsed = _extract_replan(raw)
    if parsed is None:
        # Conservative: bad output → abort.
        parsed = {"action": "abort", "new_plan": []}

    new_plan = parsed["new_plan"] if parsed["action"] == "insert_remedy" else []
    _render_new_plan_panel(new_plan)

    return {
        "plan": new_plan,
        "replan_count": replan_count + 1,
    }
