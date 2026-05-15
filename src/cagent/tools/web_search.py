"""Web search tool: Tavily Top-3, hard-capped at 4000 chars."""

from __future__ import annotations

from tavily import TavilyClient

from cagent.config import load_config

MAX_CHARS = 4000
TOP_K = 3


def web_search(query: str) -> str:
    config = load_config()
    client = TavilyClient(api_key=config.tavily_api_key)
    resp = client.search(query=query, max_results=TOP_K)

    items = (resp.get("results") or [])[:TOP_K]
    parts: list[str] = []
    for item in items:
        url = item.get("url", "")
        content = item.get("content", "")
        parts.append(f"[{url}]\n{content}\n")

    text = "\n".join(parts)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    return text
