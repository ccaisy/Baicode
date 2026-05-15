from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

DEFAULT_MODEL = "deepseek/deepseek-chat"


class MissingAPIKeyError(Exception):
    def __init__(self, key_name: str) -> None:
        super().__init__(
            f"环境变量 {key_name} 未设置。请在项目根目录的 .env 中补充该 Key。"
        )
        self.key_name = key_name


@dataclass(frozen=True)
class Config:
    deepseek_api_key: str
    tavily_api_key: str
    openai_api_key: str | None
    default_model: str


def load_config() -> Config:
    load_dotenv(find_dotenv(usecwd=True))

    required: dict[str, str | None] = {
        "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY"),
        "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY"),
    }
    for name, val in required.items():
        if not val:
            raise MissingAPIKeyError(name)

    return Config(
        deepseek_api_key=required["DEEPSEEK_API_KEY"],  # type: ignore[arg-type]
        tavily_api_key=required["TAVILY_API_KEY"],  # type: ignore[arg-type]
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        default_model=DEFAULT_MODEL,
    )
