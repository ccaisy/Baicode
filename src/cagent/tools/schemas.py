"""OpenAI tools schema definitions for cagent's built-in tools."""

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
            "Search the web via Tavily and return the top-3 results' URL + cleaned content "
            "(hard-capped at 4000 chars). Use for current events, docs lookup, or error "
            "messages that may have known fixes online."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query keywords.",
                }
            },
            "required": ["query"],
        },
    },
}

ALL_SCHEMAS: list[dict] = [PYTHON_EXEC_SCHEMA, WEB_SEARCH_SCHEMA]
