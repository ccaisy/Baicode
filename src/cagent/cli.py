from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.live import Live
from rich.text import Text

from .config import MissingAPIKeyError, load_config
from .llm import ChatError, FatalAuthError, chat

HISTORY_PATH = str(Path.home() / ".cagent_history")

SYSTEM_PROMPT = (
    "You are cagent, a terminal-native coding assistant. "
    "Reply concisely and clearly. Use Markdown only when it helps readability."
)


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
        {"role": "system", "content": SYSTEM_PROMPT}
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
            with console.status(
                "[dim cyan]thinking...[/dim cyan]",
                spinner="dots",
                spinner_style="cyan",
            ):
                assistant = chat(messages, config=config)
        except FatalAuthError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)
        except ChatError as e:
            console.print(f"[red]{e}[/red]")
            messages.pop()
            continue
        except KeyboardInterrupt:
            console.print("\n[dim]已中断本次请求。[/dim]")
            messages.pop()
            continue

        content = assistant.get("content") or ""
        if not content:
            console.print("[dim](empty response)[/dim]")
            continue

        try:
            render_typewriter(content, console, style="green")
        except KeyboardInterrupt:
            console.print()
        messages.append({"role": "assistant", "content": content})


if __name__ == "__main__":
    main()
