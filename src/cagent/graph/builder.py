"""LangGraph 图构建 + 条件边路由 (implement_plan Step 6-8)."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from cagent.graph.nodes import agent_node, tool_node
from cagent.graph.state import AgentState


class ReflectionRetriesExceeded(RuntimeError):
    """工具失败次数达到 retry_limit；上层 REPL 捕获后回到输入提示符。"""


class ToolCallBudgetExceeded(RuntimeError):
    """单轮 user request 内工具调用总次数超过 max_tool_calls。"""


_RECURSION_LIMIT = 50
_DEFAULT_RETRY_LIMIT = 3
_DEFAULT_MAX_TOOL_CALLS = 5


def _route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if last.get("tool_calls"):
        if state["tool_calls_count"] >= state["max_tool_calls"]:
            return "exceeded"
        return "tool"
    return "end"


def _route_after_tool(state: AgentState) -> str:
    if state["error_count"] >= state["retry_limit"]:
        return "exceeded"
    return "agent"


def build_graph():
    g: StateGraph = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tool", tool_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges(
        "agent",
        _route_after_agent,
        {"tool": "tool", "end": END, "exceeded": END},
    )
    g.add_conditional_edges(
        "tool",
        _route_after_tool,
        {"agent": "agent", "exceeded": END},
    )
    return g.compile()


def run(
    messages: list[dict],
    retry_limit: int = _DEFAULT_RETRY_LIMIT,
    max_tool_calls: int = _DEFAULT_MAX_TOOL_CALLS,
) -> list[dict]:
    """REPL 入口：跑一次完整图，返回更新后的 messages。

    - 工具失败次数达到 retry_limit → 抛 ReflectionRetriesExceeded。
    - 工具调用总次数达到 max_tool_calls 且模型仍想继续调 → 抛 ToolCallBudgetExceeded。
    """
    graph = build_graph()
    final_state: AgentState = graph.invoke(
        {
            "messages": messages,
            "error_count": 0,
            "retry_limit": retry_limit,
            "tool_calls_count": 0,
            "max_tool_calls": max_tool_calls,
        },
        config={"recursion_limit": _RECURSION_LIMIT},
    )

    if final_state["error_count"] >= final_state["retry_limit"]:
        raise ReflectionRetriesExceeded(
            f"Reflection retries exceeded ({final_state['error_count']}/{final_state['retry_limit']})"
        )

    last = final_state["messages"][-1]
    if (
        final_state["tool_calls_count"] >= final_state["max_tool_calls"]
        and last.get("role") == "assistant"
        and last.get("tool_calls")
    ):
        raise ToolCallBudgetExceeded(
            f"Tool-call budget exceeded "
            f"({final_state['tool_calls_count']}/{final_state['max_tool_calls']}). "
            f"Model is still trying to call tools instead of answering."
        )

    return final_state["messages"]
