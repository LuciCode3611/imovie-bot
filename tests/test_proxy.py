from aiogram.client.session.aiohttp import AiohttpSession

from src.main import create_bot
from src.models.config import Config


def _config(proxy_url: str | None) -> Config:
    return Config(
        _env_file=None,
        bot_token="1:abc",
        allowed_user_ids=[42],
        proxy_url=proxy_url,
    )


def test_config_parses_proxy_url() -> None:
    cfg = Config(_env_file=None, bot_token="1:x", proxy_url="socks5://127.0.0.1:10808")
    assert cfg.proxy_url == "socks5://127.0.0.1:10808"


def test_config_defaults_to_no_proxy() -> None:
    cfg = Config(_env_file=None, bot_token="1:x")
    assert cfg.proxy_url is None


def test_create_bot_routes_through_proxy() -> None:
    bot = create_bot(_config("socks5://127.0.0.1:10808"))
    assert isinstance(bot.session, AiohttpSession)
    assert bot.session.proxy == "socks5://127.0.0.1:10808"


def test_create_bot_without_proxy_keeps_default_session() -> None:
    bot = create_bot(_config(None))
    assert isinstance(bot.session, AiohttpSession)
    assert bot.session.proxy is None
