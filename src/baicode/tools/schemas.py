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

ALL_SCHEMAS: list[dict] = [PYTHON_EXEC_SCHEMA, WEB_SEARCH_SCHEMA]
