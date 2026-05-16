"""Web search tool: Tavily Top-5, hard-capped at 4000 chars."""

from __future__ import annotations

from tavily import TavilyClient

from baicode.config import load_config

MAX_CHARS = 4000
TOP_K = 5


def web_search(query: str, topic: str = "general", days: int = 30) -> str:
    config = load_config()
    client = TavilyClient(api_key=config.tavily_api_key)

    kwargs: dict = {"query": query, "max_results": TOP_K}
    if topic == "news":
        kwargs["topic"] = "news"
        kwargs["days"] = days
    resp = client.search(**kwargs)

    items = (resp.get("results") or [])[:TOP_K]
    parts: list[str] = []
    for item in items:
        url = item.get("url", "")
        content = item.get("content", "")
        published = item.get("published_date", "")
        head = f"[{url}]" + (f" ({published})" if published else "")
        parts.append(f"{head}\n{content}\n")

    text = "\n".join(parts)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    return text
