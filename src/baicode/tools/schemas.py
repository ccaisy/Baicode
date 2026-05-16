"""OpenAI tools schema definitions for baicode's built-in tools."""

from __future__ import annotations

PYTHON_EXEC_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "python_exec",
        "description": (
            "Execute Python source code in a local subprocess (Python 3.10+, 10s timeout). "
            "Returns stdout, stderr, returncode. Use for calculation, file inspection, "
            "or any deterministic computation. Print results explicitly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source code to execute as a standalone script.",
                }
            },
            "required": ["code"],
        },
    },
}

WEB_SEARCH_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web via Tavily and return the top-5 results' URL + cleaned content "
            "(hard-capped at 4000 chars). Use for docs lookup, unfamiliar error messages, "
            "or current events. **For time-sensitive queries (latest news, recent releases, "
            "what happened this week/month) you MUST set topic='news' so results are "
            "filtered by recency.**"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query keywords.",
                },
                "topic": {
                    "type": "string",
                    "enum": ["general", "news"],
                    "description": (
                        "'general' (default) for docs/wiki/technical content; "
                        "'news' for time-sensitive queries — filters to recent news outlets."
                    ),
                },
                "days": {
                    "type": "integer",
                    "description": (
                        "Only used when topic='news'. Restrict results to the last N days. "
                        "Default 30. Smaller N = stricter recency."
                    ),
                },
            },
            "required": ["query"],
        },
    },
}

SHELL_EXEC_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "shell_exec",
        "description": (
            "Execute a shell command in a local subprocess via /bin/sh (60s timeout). "
            "Supports pipes (|), logical-and (&&), redirection (>, <), env vars, etc. "
            "Returns stdout, stderr, returncode (stdout/stderr each hard-capped at "
            "4000 chars; longer output keeps head 2000 + truncation marker + tail "
            "2000). Use for filesystem inspection (ls, cat, find), git operations, "
            "package management, log inspection — anything you'd type at a terminal. "
            "Each call is an isolated subprocess with no persistent CWD: chain "
            "directory changes with && in a single command (e.g. `cd foo && ls`). "
            "Do NOT invoke interactive tools (vim, less, top, nano, ssh without -o "
            "BatchMode); they will block until timeout. Install/apt/pip commands "
            "MUST be made non-interactive (e.g. `apt-get install -y`, "
            "`pip install --quiet`, `DEBIAN_FRONTEND=noninteractive apt-get ...`)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Full shell command line, as you would type at a terminal. "
                        "Use && / | / > / etc. freely. No persistent CWD between calls."
                    ),
                }
            },
            "required": ["command"],
        },
    },
}

ALL_SCHEMAS: list[dict] = [PYTHON_EXEC_SCHEMA, WEB_SEARCH_SCHEMA, SHELL_EXEC_SCHEMA]
