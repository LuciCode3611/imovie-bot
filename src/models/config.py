from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    zarfilm_username: str
    zarfilm_password: str
    allowed_user_ids: list[int] = []
    session_path: Path = Path("session.json")
    search_ttl: int = 3600
    page_ttl: int = 21600
    state_ttl: int = 3600
    emoji: dict[str, str] = {}

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.replace(" ", "").split(",") if part]
        return value
