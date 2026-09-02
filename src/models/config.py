import json
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        validate_default=True,
    )

    bot_token: str
    allowed_user_ids: Annotated[list[int] | None, NoDecode] = None
    session_path: Path = Path("session.json")
    search_ttl: int = 3600
    page_ttl: int = 21600
    state_ttl: int = 3600
    emoji: Annotated[dict[str, str] | None, NoDecode] = None

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [int(part) for part in value.replace(" ", "").split(",") if part]
        return value

    @field_validator("emoji", mode="before")
    @classmethod
    def _parse_emoji(cls, value: object) -> object:
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            return json.loads(value)
        return value
