"""Finalizer 节点：综合 history 生成用户友好的最终回复 (Phase 7 §4)."""

from __future__ import annotations

from typing import Any

from baicode.graph.executor import _format_history_brief
from baicode.graph.nodes import _console
from baicode.llm import chat

_FINALIZER_ADDENDUM = (
    "\n\n--- FINALIZER MODE ---\n"
    "You are wrapping up a multi-step task on the user's behalf. The "
    "system already executed (or attempted) the plan and gave you a "
    "history of what happened. Your job is to produce ONE final reply to "
    "the user.\n"
    "\n"
    "Rules:\n"
    "- Address the user's ORIGINAL request directly. Speak to them, not "
    "  about the system.\n"
    "- Use user-facing language. Do NOT echo raw stdout, returncodes, or "
    "  internal step summaries verbatim. Translate machine output into "
    "  what the user actually wanted to know.\n"
    "- If steps failed AND were remedied successfully, you may briefly "
    "  mention the detour (one short phrase) but the focus is the final "
    "  result.\n"
    "- If the task was partially completed or aborted, clearly tell the "
    "  user what got done, what did NOT get done, and (if helpful) what "
    "  they could try next.\n"
    "- Reply concisely. Use Markdown only where it helps readability — "
    "  fenced code blocks for code, bullets for short enumerations, bold "
    "  for key results."
)


def finalizer_node(state: dict) -> dict:
    messages: list[dict[str, Any]] = list(state.get("messages") or [])
    history: list[dict] = state.get("history") or []

    # The last user message in the macro-level messages is the original request
    # for this turn.
    user_request = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_request = msg.get("content", "")
            break

    # Deferred import to avoid circular: cli → builder → finalizer → cli.
    from baicode.cli import _build_system_prompt

    base_system = _build_system_prompt()

    if not history:
        # Chitchat / empty-plan path: just answer the user normally.
        finalizer_messages: list[dict[str, Any]] = [
            {"role": "system", "content": base_system},
            {"role": "user", "content": user_request},
        ]
    else:
        history_brief = _format_history_brief(history)
        finalizer_messages = [
            {"role": "system", "content": base_system + _FINALIZER_ADDENDUM},
            {
                "role": "user",
                "content": (
                    f"My original request was:\n{user_request}\n\n"
                    f"The system executed the following plan on my behalf:\n"
                    f"{history_brief}\n\n"
                    "Please give me a single, friendly, concise final "
                    "response that addresses my original request. Reference "
                    "what was done in user-facing language (not raw "
                    "execution logs). If any steps failed and could not be "
                    "remedied, acknowledge that. Use Markdown formatting "
                    "where appropriate."
                ),
            },
        ]

    with _console.status(
        "[dim cyan]wrapping up...[/dim cyan]",
        spinner="dots",
        spinner_style="cyan",
    ):
        raw = chat(finalizer_messages, tools=None)

    content = raw.get("content") or ""

    return {
        "messages": messages + [{"role": "assistant", "content": content}],
    }
