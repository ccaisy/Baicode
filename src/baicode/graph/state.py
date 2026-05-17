"""AgentState definition (implement_plan §0.3 + Phase 7 §0)."""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict):
    messages: list
    error_count: int
    retry_limit: int
    tool_calls_count: int
    max_tool_calls: int
    # Phase 7 macro-graph fields
    plan: list[str]
    history: list[dict]
    replan_count: int
    max_replans: int
