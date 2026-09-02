import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.handlers import admin, card, common, search
from src.handlers.middleware import AllowlistMiddleware, SearchLockMiddleware
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState
from src.services.zarfilm import ZarfilmClient


def build_dispatcher(config: Config) -> tuple[Dispatcher, ZarfilmClient]:
    dp = Dispatcher(storage=MemoryStorage())
    zarfilm = ZarfilmClient(config)
    cache = TTLCache()
    card_state = CallbackState(ttl=config.state_ttl)

    allowed = set(config.allowed_user_ids or [])
    dp.message.middleware(AllowlistMiddleware(allowed))
    dp.message.middleware(SearchLockMiddleware())
    dp.callback_query.middleware(AllowlistMiddleware(allowed))

    deps = {"cfg": config, "zarfilm": zarfilm, "cache": cache, "card_state": card_state}
    dp.include_router(common.router)
    dp.include_router(search.router)
    dp.include_router(card.router)
    dp.include_router(admin.router)
    dp.workflow_data.update(deps)
    return dp, zarfilm


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = Config()
    dp, zarfilm = build_dispatcher(config)
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await zarfilm.close()


if __name__ == "__main__":
    asyncio.run(main())
