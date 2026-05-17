"""React 节点：Planner 判定为 0/1 step 时走的纯 ReAct 路径 (Phase 7 偏离 14)。

设计：
- 用户原始 messages 直接喂给微图 (`_run_micro`)，等价于 Phase 1-6 行为。
- 不包装 `_EXECUTOR_ADDENDUM`、不需要 history brief、不打印 ▶ Step 指示。
- 微图返回完整 messages 序列后，只把"末条 assistant content"作为最终回复
  追加到宏图 messages，避免把 tool_call / tool 响应等中间产物带回 CLI。

异常处理（Phase 7 fix-up，2026-05-17 偏离 15）：
- `ToolCallBudgetExceeded`：**捕获并转友好降级回复**。E-02 / H-01 之类模型
  对实时结构化数据请求烧光工具预算的场景，原行为是红字穿透到 CLI；现在
  改成 fail-soft，给用户一段说明工具预算用尽 + 提示是否为实时结构化数据 +
  给替代建议的 markdown 回复。
- `ReflectionRetriesExceeded`：**仍照常冒泡**到 cli.py 红字 + messages.pop()。
  这是确定性的 3 次工具失败（语法/类型/网络等真错误），保留红字让用户知道。
"""

from __future__ import annotations

from baicode.graph.builder import ToolCallBudgetExceeded, _run_micro


_BUDGET_EXCEEDED_FALLBACK = (
    "抱歉，我没能完成这个请求 —— 工具调用预算（单次对话上限 5 次）已耗尽。\n\n"
    "如果你查询的是**实时结构化数据**（比如：天气预报、股价、航班状态、"
    "卫星实时图像、实时汇率、体育比分），这类问题超出了我的能力范围："
    "`web_search` 返回的是网页摘要而不是结构化 API 数据，"
    "`shell_exec` 拿 wget/curl 抓未知端点通常只会拿到 HTML 错误页。\n\n"
    "建议改用专用渠道：\n"
    "- **天气**：墨迹天气、彩云天气、Weather.com、Ventusky\n"
    "- **股价**：富途、雪球、Yahoo Finance、各券商 App\n"
    "- **卫星图像**：直接访问 NASA / ESA / Sentinel Hub 官网\n"
    "- **汇率 / 航班 / 比分**：对应的官方 App 或数据 API\n\n"
    "如果你的请求**不是**实时结构化数据，请把它拆得更具体一点、"
    "或换个角度重新提问，我再试一次。"
)


def react_node(state: dict) -> dict:
    try:
        result_messages = _run_micro(
            state["messages"],
            retry_limit=state["retry_limit"],
            max_tool_calls=state["max_tool_calls"],
        )
        last_content = (result_messages[-1].get("content") or "").strip()
    except ToolCallBudgetExceeded:
        last_content = _BUDGET_EXCEEDED_FALLBACK
    return {
        "messages": list(state["messages"])
        + [{"role": "assistant", "content": last_content}],
    }
