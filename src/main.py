import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from src.handlers import admin, card, common, requests, search
from src.handlers.middleware import AllowlistMiddleware, SearchLockMiddleware
from src.models.config import Config, resolve_owner
from src.repos.cache import TTLCache
from src.repos.db import Database
from src.repos.state import CallbackState
from src.services.zarfilm import ZarfilmClient


def build_dispatcher(config: Config) -> tuple[Dispatcher, ZarfilmClient]:
    dp = Dispatcher(storage=MemoryStorage())
    zarfilm = ZarfilmClient(config)
    cache = TTLCache()
    card_state = CallbackState(ttl=config.state_ttl)
    db = Database(config.db_path)

    allowed = set(config.allowed_user_ids or [])
    if not allowed:
        logging.info("ALLOWED_USER_IDS is empty — the bot is OPEN TO EVERY user")
    if resolve_owner(config) is None:
        logging.warning("no owner configured — /login and session-expiry alerts are disabled")
    dp.message.middleware(AllowlistMiddleware(allowed, db))
    dp.callback_query.middleware(AllowlistMiddleware(allowed, db))
    search.router.message.middleware(SearchLockMiddleware())

    deps = {
        "cfg": config,
        "zarfilm": zarfilm,
        "cache": cache,
        "card_state": card_state,
        "db": db,
    }
    dp.include_router(admin.router)
    dp.include_router(common.router)
    dp.include_router(requests.router)
    dp.include_router(search.router)
    dp.include_router(card.router)
    dp.workflow_data.update(deps)
    return dp, zarfilm


USER_COMMANDS = [
    BotCommand(command="start", description="شروع و منوی اصلی"),
    BotCommand(command="search", description="جستجوی فیلم، سریال یا انیمه"),
]
OWNER_COMMANDS = [
    *USER_COMMANDS,
    BotCommand(command="login", description="ثبت کوکی ورود"),
    BotCommand(command="status", description="وضعیت ربات"),
]


async def setup_commands(bot: Bot, config: Config) -> None:
    """Publish the command menu so users tap instead of typing."""
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    owner = resolve_owner(config)
    if owner is not None:
        await bot.set_my_commands(OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=owner))


def create_bot(config: Config) -> Bot:
    if config.proxy_url is None:
        return Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return Bot(
        config.bot_token,
        session=AiohttpSession(proxy=config.proxy_url),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = Config()
    dp, zarfilm = build_dispatcher(config)
    bot = create_bot(config)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await setup_commands(bot, config)
        await dp.start_polling(bot)
    finally:
        await zarfilm.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
