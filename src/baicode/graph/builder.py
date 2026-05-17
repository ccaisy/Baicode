"""LangGraph 图构建 + 条件边路由 (Phase 1-6 微图 + Phase 7 宏图)."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from baicode.graph.nodes import agent_node, tool_node
from baicode.graph.state import AgentState


class ReflectionRetriesExceeded(RuntimeError):
    """工具失败次数达到 retry_limit；上层 REPL 捕获后回到输入提示符。"""


class ToolCallBudgetExceeded(RuntimeError):
    """单轮 user request 内工具调用总次数超过 max_tool_calls。"""


_RECURSION_LIMIT = 50
_DEFAULT_RETRY_LIMIT = 3
_DEFAULT_MAX_TOOL_CALLS = 5
_DEFAULT_MAX_REPLANS = 3


# ---------------------------------------------------------------------------
# 微图 (Phase 1-6 ReAct + Reflection)
# ---------------------------------------------------------------------------


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


def _build_micro_graph():
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


def _run_micro(
    messages: list[dict],
    retry_limit: int = _DEFAULT_RETRY_LIMIT,
    max_tool_calls: int = _DEFAULT_MAX_TOOL_CALLS,
) -> list[dict]:
    """跑一次微图 ReAct 循环，返回更新后的 messages。

    - 工具失败次数达到 retry_limit → 抛 ReflectionRetriesExceeded。
    - 工具调用总次数达到 max_tool_calls 且模型仍想继续调 → 抛 ToolCallBudgetExceeded。

    Phase 7 起，本函数仅被 executor_node 内部调用，每次注入"全新 executor_messages"
    (一段隔离的单步对话)；macro state 中的 plan/history/replan_count 在此函数内
    被填默认值，不会影响外层宏图。
    """
    graph = _build_micro_graph()
    final_state: AgentState = graph.invoke(
        {
            "messages": messages,
            "error_count": 0,
            "retry_limit": retry_limit,
            "tool_calls_count": 0,
            "max_tool_calls": max_tool_calls,
            "plan": [],
            "history": [],
            "replan_count": 0,
            "max_replans": 0,
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


# ---------------------------------------------------------------------------
# 宏图 (Phase 7 Plan-and-Execute)
# ---------------------------------------------------------------------------


def _route_after_planner(state: AgentState) -> str:
    # Phase 7 偏离 14：仅 2+ step 走 plan 路径；0/1 step（含解析失败兜底）
    # 走 react 路径，保留 Phase 1-6 的 ReAct 视觉与多轮上下文契约。
    if len(state.get("plan") or []) >= 2:
        return "executor"
    return "react"


def _route_after_executor(state: AgentState) -> str:
    history = state.get("history") or []
    last = history[-1] if history else {}
    if (
        last.get("status") == "failed"
        and int(state.get("replan_count") or 0) < int(state.get("max_replans") or 0)
    ):
        return "replanner"
    if not state.get("plan"):
        return "finalizer"
    return "executor"


def _route_after_replanner(state: AgentState) -> str:
    if not state.get("plan"):
        return "finalizer"
    return "executor"


def _build_macro_graph():
    # Deferred imports to break the macro-layer dependency cycle:
    # planner / executor / replanner / finalizer / react all live alongside builder.
    from baicode.graph.executor import executor_node
    from baicode.graph.finalizer import finalizer_node
    from baicode.graph.planner import planner_node
    from baicode.graph.react import react_node
    from baicode.graph.replanner import replanner_node

    g: StateGraph = StateGraph(AgentState)
    g.add_node("planner", planner_node)
    g.add_node("react", react_node)
    g.add_node("executor", executor_node)
    g.add_node("replanner", replanner_node)
    g.add_node("finalizer", finalizer_node)
    g.add_edge(START, "planner")
    g.add_conditional_edges(
        "planner",
        _route_after_planner,
        {"react": "react", "executor": "executor"},
    )
    g.add_edge("react", END)
    g.add_conditional_edges(
        "executor",
        _route_after_executor,
        {
            "executor": "executor",
            "replanner": "replanner",
            "finalizer": "finalizer",
        },
    )
    g.add_conditional_edges(
        "replanner",
        _route_after_replanner,
        {"executor": "executor", "finalizer": "finalizer"},
    )
    g.add_edge("finalizer", END)
    return g.compile()


def run(
    messages: list[dict],
    retry_limit: int = _DEFAULT_RETRY_LIMIT,
    max_tool_calls: int = _DEFAULT_MAX_TOOL_CALLS,
    max_replans: int = _DEFAULT_MAX_REPLANS,
) -> list[dict]:
    """REPL 入口：跑一次完整宏图，返回更新后的 messages。

    宏图层捕获 Executor 内部的 ReflectionRetriesExceeded / ToolCallBudgetExceeded
    并转成 history 的 failed 条目，因此本函数正常路径下不再抛出这两个异常；
    保留导出仅作防御兜底（CLI 仍 import 它们以匹配 Phase 1-6 行为）。

    Args:
        messages: 截至本次 user input 的完整对话序列（含 system / 历史轮）。
        retry_limit: 每个 Executor 单步内部的反思上限，默认 3。
        max_tool_calls: 每个 Executor 单步内部的工具调用上限，默认 5。
        max_replans: 整轮宏任务允许的重规划次数上限，默认 3。
    """
    graph = _build_macro_graph()
    final_state: AgentState = graph.invoke(
        {
            "messages": messages,
            "error_count": 0,
            "retry_limit": retry_limit,
            "tool_calls_count": 0,
            "max_tool_calls": max_tool_calls,
            "plan": [],
            "history": [],
            "replan_count": 0,
            "max_replans": max_replans,
        },
        config={"recursion_limit": _RECURSION_LIMIT},
    )
    return final_state["messages"]
