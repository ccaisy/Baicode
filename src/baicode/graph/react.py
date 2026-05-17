"""React 节点：Planner 判定为 0/1 step 时走的纯 ReAct 路径 (Phase 7 偏离 14)。

设计：
- 用户原始 messages 直接喂给微图 (`_run_micro`)，等价于 Phase 1-6 行为。
- 不包装 `_EXECUTOR_ADDENDUM`、不需要 history brief、不打印 ▶ Step 指示。
- 不捕获 `ReflectionRetriesExceeded` / `ToolCallBudgetExceeded`：让其冒泡到
  cli.py 的既有 except 矩阵（红字 + messages.pop() 回滚 + REPL 继续）。
- 微图返回完整 messages 序列后，只把"末条 assistant content"作为最终回复
  追加到宏图 messages，避免把 tool_call / tool 响应等中间产物带回 CLI。
"""

from __future__ import annotations

from baicode.graph.builder import _run_micro


def react_node(state: dict) -> dict:
    result_messages = _run_micro(
        state["messages"],
        retry_limit=state["retry_limit"],
        max_tool_calls=state["max_tool_calls"],
    )
    last_content = (result_messages[-1].get("content") or "").strip()
    return {
        "messages": list(state["messages"])
        + [{"role": "assistant", "content": last_content}],
    }
