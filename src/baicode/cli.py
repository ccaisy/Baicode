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
from rich.markdown import Markdown

from .config import MissingAPIKeyError, load_config
from .graph.builder import (
    ReflectionRetriesExceeded,
    ToolCallBudgetExceeded,
    run as graph_run,
)
from .llm import ChatError, FatalAuthError

HISTORY_PATH = str(Path.home() / ".baicode_history")

_BANNER_LINES = (
    " ██████╗  █████╗ ██╗ ██████╗ ██████╗ ██████╗ ███████╗",
    " ██╔══██╗██╔══██╗██║██╔════╝██╔═══██╗██╔══██╗██╔════╝",
    " ██████╔╝███████║██║██║     ██║   ██║██║  ██║█████╗  ",
    " ██╔══██╗██╔══██║██║██║     ██║   ██║██║  ██║██╔══╝  ",
    " ██████╔╝██║  ██║██║╚██████╗╚██████╔╝██████╔╝███████╗",
    " ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝",
)
_BANNER_COLORS = (
    "#5e8bff",
    "#7466ff",
    "#8a41ff",
    "#a02bff",
    "#b620ff",
    "#cc00ff",
)


def _display_cwd() -> str:
    cwd = Path.cwd()
    home = Path.home()
    try:
        rel = cwd.relative_to(home)
    except ValueError:
        return str(cwd)
    return "~" if str(rel) == "." else f"~/{rel}"


def _print_banner(console: Console, model: str) -> None:
    for line, color in zip(_BANNER_LINES, _BANNER_COLORS):
        console.print(line, style=f"bold {color}", highlight=False)
    console.print()
    console.print(
        f"  [dim]model:[/dim] [cyan]{model}[/cyan]  [dim]·[/dim]  "
        f"[dim]cwd:[/dim] [cyan]{_display_cwd()}[/cyan]"
    )
    console.print(
        "  [dim]Alt+Enter to submit  ·  Ctrl+C to exit[/dim]"
    )

if sys.platform == "win32":
    _SHELL_EXEC_SECTION = (
        "  - shell_exec(command): run a shell command via cmd.exe (60s timeout); "
        "use for filesystem inspection (dir, type, where, findstr), git ops, "
        "package management, log inspection — anything you'd type at a Windows "
        "command prompt. Each call is an ISOLATED subprocess: there is NO "
        "persistent CWD between calls, so a standalone `cd foo` is useless; "
        "you MUST chain directory changes with && in a single command "
        "(e.g. `cd foo && dir`, `mkdir x && cd x && echo. > y.txt`). "
        "NEVER invoke interactive tools (vim, nano, less, more, top); "
        "they will block the subprocess until timeout. "
        "Install / package-manager commands MUST be made non-interactive: use "
        "`--quiet` / `-y` / `--yes` flags "
        "(e.g. `pip install --quiet pkg`, "
        "`winget install --silent --accept-package-agreements pkg`).\n"
    )
else:
    _SHELL_EXEC_SECTION = (
        "  - shell_exec(command): run a shell command via /bin/sh (60s timeout); "
        "use for filesystem inspection (ls, cat, find), git ops, package management, "
        "log inspection — anything you'd type at a terminal. Each call is an "
        "ISOLATED subprocess: there is NO persistent CWD between calls, so a "
        "standalone `cd foo` is useless; you MUST chain directory changes with && "
        "in a single command (e.g. `cd foo && ls`, `mkdir -p x && cd x && touch y`). "
        "NEVER invoke interactive tools (vim, nano, less, more, top, htop, ssh "
        "without -o BatchMode=yes); they will block the subprocess until timeout. "
        "Install / package-manager commands MUST be made non-interactive: use "
        "`-y` / `--yes` / `--quiet` flags (e.g. `apt-get install -y pkg`, "
        "`pip install --quiet pkg`, `brew install --quiet pkg`) and where "
        "applicable prefix with `DEBIAN_FRONTEND=noninteractive`.\n"
    )

_SYSTEM_PROMPT_TEMPLATE = (
    "You are baicode, a terminal-native coding assistant.\n"
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
    "{shell_exec_section}"
    "\n"
    "IMPORTANT — web_search / shell_exec limits for realtime structured data:\n"
    "web_search returns news / web-page snippets, NOT a structured-data API. "
    "shell_exec wget/curl against unknown public endpoints typically returns "
    "HTML error pages, not structured data. Neither can reliably provide "
    "weather forecasts, real-time stock prices, flight statuses, exchange "
    "rates, live sports scores, satellite imagery, or any other realtime "
    "structured data.\n"
    "HARD RULE for realtime structured data requests:\n"
    "  1. Do NOT call web_search OR shell_exec (wget/curl) to fetch them — "
    "the calls will not return what the user wants and will waste budget.\n"
    "  2. Immediately tell the user: (a) you cannot reliably provide this "
    "kind of data, (b) why (web_search is web snippets, not an API), "
    "(c) suggest a specialized app or website they can use.\n"
    "  3. If you already called a tool ONCE for a realtime structured-data "
    "query and it did not return structured data, STOP. Do NOT retry with "
    "different queries or different tools — the next call WILL also fail. "
    "Switch to the capability-limited reply in step 2.\n"
    "Examples that fall under this rule: 明天的天气 / 苹果今天的股价 / "
    "实时卫星图像 / 当前汇率 / 航班状态 / 今天的体育比分 / 实时新闻播报.\n"
    "\n"
    "Tool-call budget: you may call tools at most 5 times in total per user "
    "message. If you can't answer within that budget, stop and tell the user "
    "what you found and what is still unknown.\n"
    "\n"
    "When a tool call fails, read its stderr carefully, fix the root cause, "
    "and retry — do not loop on the same broken code.\n"
    "Reply concisely. Use Markdown only when it helps readability.\n"
    "When you output code, always wrap it in fenced code blocks with an "
    "explicit language tag (e.g. ```python …``` or ```bash …```), so the CLI "
    "can syntax-highlight it."
)


def _build_system_prompt() -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        today=date.today().isoformat(),
        shell_exec_section=_SHELL_EXEC_SECTION,
    )


def render_typewriter(
    text: str,
    console: Console,
    style: str | None = None,
    delay: float = 0.005,
) -> None:
    # Since Phase 5 `style` is only a fallback hook; Markdown's own styling
    # (bold, italic, code-block background, link underline) takes precedence.
    # Throttle: per-char sleep keeps the typewriter rhythm, but Markdown
    # re-parse + update only fires on newline / end-of-text so a 4000-char
    # reply doesn't pay 4000× parse cost (Phase 5 Step 12, scheme B).
    buf = ""
    with Live(
        Markdown(buf, code_theme="monokai"),
        console=console,
        refresh_per_second=24,
    ) as live:
        for i, ch in enumerate(text):
            buf += ch
            if ch == "\n" or i == len(text) - 1:
                live.update(Markdown(buf, code_theme="monokai"))
            time.sleep(delay)


def main() -> None:
    console = Console()

    if not sys.stdin.isatty():
        console.print(
            "[red]baicode 必须在交互式终端中运行（当前 stdin 不是 TTY）。[/red]"
        )
        sys.exit(1)

    try:
        config = load_config()
    except MissingAPIKeyError as e:
        console.print(f"[red]启动失败：{e}[/red]")
        sys.exit(1)

    _print_banner(console, config.default_model)

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
            render_typewriter(content, console)
        except KeyboardInterrupt:
            console.print()


if __name__ == "__main__":
    main()
