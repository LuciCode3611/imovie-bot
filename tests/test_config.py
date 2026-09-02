import pytest
from pydantic import ValidationError

from src.models.config import Config


def _base_env() -> dict[str, str]:
    return {"bot_token": "1:abc", "zarfilm_username": "u", "zarfilm_password": "p"}


def test_minimal_config() -> None:
    cfg = Config(_env_file=None, **_base_env())
    assert cfg.allowed_user_ids == []
    assert cfg.search_ttl == 3600 and cfg.page_ttl == 21600 and cfg.state_ttl == 3600


def test_comma_separated_ids() -> None:
    env = _base_env() | {"allowed_user_ids": " 111, 222 ,333"}
    cfg = Config(_env_file=None, **env)
    assert cfg.allowed_user_ids == [111, 222, 333]


def test_emoji_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMOJI", '{"dub": "5368385512908012910"}')
    cfg = Config(_env_file=None, **_base_env())
    assert cfg.emoji["dub"] == "5368385512908012910"


def test_missing_token_rejected() -> None:
    with pytest.raises(ValidationError):
        Config(_env_file=None, zarfilm_username="u", zarfilm_password="p")


def test_empty_env_ids_fall_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    cfg = Config(_env_file=None, **_base_env())
    assert cfg.allowed_user_ids == []


def test_comma_separated_ids_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_USER_IDS", "111,222")
    cfg = Config(_env_file=None, **_base_env())
    assert cfg.allowed_user_ids == [111, 222]
