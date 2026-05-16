from __future__ import annotations

import os
import time
from typing import Any

os.environ.setdefault("LITELLM_LOG", "ERROR")

import litellm  # noqa: E402

from .config import Config, load_config  # noqa: E402

litellm.suppress_debug_info = True


class ChatError(Exception):
    pass


class FatalAuthError(Exception):
    pass


_AUTH_KEYWORDS = (
    "authentication",
    "unauthorized",
    "invalid api key",
    "invalid_api_key",
    "incorrect api key",
    "api key is invalid",
)


def _looks_like_auth_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in _AUTH_KEYWORDS)


def chat(
    messages: list[dict[str, Any]],
    config: Config | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if config is None:
        config = load_config()

    for attempt in range(2):
        try:
            response = litellm.completion(
                model=config.default_model,
                messages=messages,
                tools=tools,
                stream=False,
                api_key=config.deepseek_api_key,
            )
            msg = response.choices[0].message
            return {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": getattr(msg, "tool_calls", None),
                "reasoning_content": getattr(msg, "reasoning_content", None),
            }
        except litellm.AuthenticationError as e:
            raise FatalAuthError(f"鉴权失败：{e}") from e
        except litellm.RateLimitError as e:
            if attempt == 0:
                time.sleep(2)
                continue
            raise ChatError(f"限流且重试失败：{e}") from e
        except (litellm.APIConnectionError, litellm.Timeout) as e:
            raise ChatError(f"网络异常：{e}") from e
        except Exception as e:
            if _looks_like_auth_error(e):
                raise FatalAuthError(f"鉴权失败：{e}") from e
            raise ChatError(f"模型调用出错（{type(e).__name__}）：{e}") from e

    raise ChatError("无法获取模型响应")
