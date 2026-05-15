from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.live import Live
from rich.text import Text

from .config import MissingAPIKeyError, load_config
from .graph.builder import (
    ReflectionRetriesExceeded,
    ToolCallBudgetExceeded,
    run as graph_run,
)
from .llm import ChatError, FatalAuthError

HISTORY_PATH = str(Path.home() / ".cagent_history")

_SYSTEM_PROMPT_TEMPLATE = (
    "You are cagent, a terminal-native coding assistant.\n"
    "Today is {today}. Your training data is older than this — for ANY question "
    "involving recent events, model releases, version numbers, prices, or dates, "
    "you MUST call web_search first and base your answer ONLY on the tool "
    "results. Do not rely on specific dates, numbers, or product names from "
    "training memory; if the tool result doesn't contain a fact, say so rather "
    "than guessing.\n"
    "\n"
    "Tools available:\n"
    "  - python_exec(code): execute Python in a local subprocess (10s timeout); "
    "use for calculation, file inspection, or any deterministic computation. "
    "Always print() the result you want to observe.\n"
    "  - web_search(query, topic='general'|'news', days=30): fetch top-5 Tavily "
    "results. Set topic='news' for time-sensitive queries (latest releases, "
    "current events) so results are filtered by recency; keep topic='general' "
    "for docs lookup, technical references, error messages.\n"
    "\n"
    "IMPORTANT — web_search limits: it returns news / web-page snippets, NOT a "
    "structured-data API. It CANNOT give you reliable weather forecasts, "
    "real-time stock prices, flight statuses, exchange rates, live sports "
    "scores, or any other realtime structured data. If the user asks for such "
    "information, tell them this is beyond your capability — do NOT loop on "
    "web_search trying different queries; that will just waste their time.\n"
    "\n"
    "Tool-call budget: you may call tools at most 5 times in total per user "
    "message. If you can't answer within that budget, stop and tell the user "
    "what you found and what is still unknown.\n"
    "\n"
    "When a tool call fails, read its stderr carefully, fix the root cause, "
    "and retry — do not loop on the same broken code.\n"
    "Reply concisely. Use Markdown only when it helps readability."
)


def _build_system_prompt() -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(today=date.today().isoformat())


def render_typewriter(
    text: str,
    console: Console,
    style: str = "green",
    delay: float = 0.005,
) -> None:
    rendered = Text("", style=style)
    with Live(rendered, console=console, refresh_per_second=24):
        for ch in text:
            rendered.append(ch)
            time.sleep(delay)


def main() -> None:
    console = Console()

    if not sys.stdin.isatty():
        console.print(
            "[red]cagent 必须在交互式终端中运行（当前 stdin 不是 TTY）。[/red]"
        )
        sys.exit(1)

    try:
        config = load_config()
    except MissingAPIKeyError as e:
        console.print(f"[red]启动失败：{e}[/red]")
        sys.exit(1)

    console.print(
        f"[bold green]cagent[/bold green] ready · model "
        f"[cyan]{config.default_model}[/cyan]"
    )
    console.print(
        "[dim]Alt+Enter 提交  ·  Ctrl+C 退出  ·  history: ~/.cagent_history[/dim]"
    )

    session: PromptSession[str] = PromptSession(
        multiline=True,
        history=FileHistory(HISTORY_PATH),
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _build_system_prompt()}
    ]

    while True:
        try:
            user_input = session.prompt("\nYou ▷ ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]再见。[/dim]")
            return

        text = user_input.strip()
        if not text:
            continue

        messages.append({"role": "user", "content": text})

        try:
            updated_messages = graph_run(messages)
        except FatalAuthError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)
        except ChatError as e:
            console.print(f"[red]{e}[/red]")
            messages.pop()
            continue
        except ReflectionRetriesExceeded as e:
            console.print(f"[red]{e}[/red]")
            messages.pop()
            continue
        except ToolCallBudgetExceeded as e:
            console.print(f"[red]{e}[/red]")
            messages.pop()
            continue
        except KeyboardInterrupt:
            console.print("\n[dim]已中断本次请求。[/dim]")
            messages.pop()
            continue

        messages = updated_messages

        last = messages[-1]
        content = last.get("content") or ""
        if not content:
            console.print("[dim](empty response)[/dim]")
            continue

        try:
            render_typewriter(content, console, style="green")
        except KeyboardInterrupt:
            console.print()


if __name__ == "__main__":
    main()
