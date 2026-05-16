"""agent_node / tool_node (手写 ReAct + Reflection, 禁用 prebuilt ToolNode)."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console

from baicode.llm import chat
from baicode.tools.python_exec import run_python
from baicode.tools.schemas import ALL_SCHEMAS
from baicode.tools.shell_exec import run_shell
from baicode.tools.web_search import web_search

_console = Console()


def _normalize_tool_calls(tool_calls: Any) -> list[dict] | None:
    if not tool_calls:
        return None
    out: list[dict] = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            out.append(
                {
                    "id": tc.get("id"),
                    "type": tc.get("type", "function"),
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
            )
        else:
            out.append(
                {
                    "id": tc.id,
                    "type": getattr(tc, "type", "function"),
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
            )
    return out


def agent_node(state: dict) -> dict:
    with _console.status(
        "[dim cyan]thinking...[/dim cyan]",
        spinner="dots",
        spinner_style="cyan",
    ):
        raw = chat(state["messages"], tools=ALL_SCHEMAS)

    msg: dict[str, Any] = {
        "role": "assistant",
        "content": raw.get("content") or "",
    }
    tcs = _normalize_tool_calls(raw.get("tool_calls"))
    if tcs:
        msg["tool_calls"] = tcs
    rc = raw.get("reasoning_content")
    if rc:
        msg["reasoning_content"] = rc

    return {"messages": state["messages"] + [msg]}


def _format_python_failure(code: str, result: dict) -> str:
    return (
        f"Execution failed (returncode={result['returncode']}).\n"
        f"Code:\n```python\n{code}\n```\n"
        f"Stderr:\n{result['stderr']}\n"
        f"Stdout:\n{result['stdout']}\n"
    )


def _format_python_success(result: dict) -> str:
    return (
        f"Execution succeeded (returncode={result['returncode']}).\n"
        f"Stdout:\n{result['stdout']}\n"
    )


def _format_shell_result(command: str, result: dict) -> str:
    return (
        f"Shell command (returncode={result['returncode']}).\n"
        f"Command:\n```bash\n{command}\n```\n"
        f"Stdout:\n{result['stdout']}\n"
        f"Stderr:\n{result['stderr']}\n"
    )


def _format_shell_timeout(command: str, result: dict) -> str:
    return (
        f"Shell command timed out (returncode={result['returncode']}).\n"
        f"Command:\n```bash\n{command}\n```\n"
        f"Stderr:\n{result['stderr']}\n"
        f"Stdout:\n{result['stdout']}\n"
        f"Hint: this command exceeded the 60s budget. Make sure it is "
        f"non-interactive and not running a foreground long-lived process."
    )


def tool_node(state: dict) -> dict:
    last = state["messages"][-1]
    tool_calls = last.get("tool_calls") or []

    new_messages: list[dict] = list(state["messages"])
    new_error_count: int = state["error_count"]

    with _console.status(
        "[yellow]Running tool...[/yellow]",
        spinner="dots",
        spinner_style="yellow",
    ):
        for i, tc in enumerate(tool_calls):
            tool_id = tc["id"]
            name = tc["function"]["name"]
            args_str = tc["function"]["arguments"] or "{}"

            try:
                args = json.loads(args_str)
            except json.JSONDecodeError as exc:
                new_error_count += 1
                new_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "name": name,
                        "content": (
                            f"Failed to parse arguments JSON: {exc}\nRaw: {args_str}"
                        ),
                    }
                )
                continue

            try:
                if name == "python_exec":
                    code = args.get("code", "")
                    result = run_python(code)
                    if result["stderr"]:
                        new_error_count += 1
                        content = _format_python_failure(code, result)
                    else:
                        content = _format_python_success(result)
                elif name == "web_search":
                    content = web_search(
                        args.get("query", ""),
                        topic=args.get("topic", "general"),
                        days=args.get("days", 30),
                    )
                elif name == "shell_exec":
                    command = args.get("command", "")
                    result = run_shell(command)
                    if result["returncode"] == -1:
                        new_error_count += 1
                        content = _format_shell_timeout(command, result)
                    else:
                        content = _format_shell_result(command, result)
                else:
                    new_error_count += 1
                    content = f"Unknown tool: {name}"
            except KeyboardInterrupt:
                # subprocess.run 在 KeyboardInterrupt 时已 kill 子进程
                new_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "name": name,
                        "content": "Tool execution interrupted by user.",
                    }
                )
                for remaining in tool_calls[i + 1 :]:
                    new_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": remaining["id"],
                            "name": remaining["function"]["name"],
                            "content": "Tool execution skipped due to earlier interrupt.",
                        }
                    )
                break
            except Exception as exc:
                new_error_count += 1
                content = f"Tool '{name}' raised {type(exc).__name__}: {exc}"

            new_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": name,
                    "content": content,
                }
            )

    return {
        "messages": new_messages,
        "error_count": new_error_count,
        "tool_calls_count": state["tool_calls_count"] + 1,
    }
