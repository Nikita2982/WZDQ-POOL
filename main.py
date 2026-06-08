import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError
from aiogram.types import BotCommand, BotCommandScopeChat
from uvicorn import Config, Server

from api.app import create_app
from bot.handlers.admin import router as admin_router
from bot.handlers.user import router as user_router
from config.settings import get_settings
from database.db import close_db, init_db
from scanner.scan_tracks import ChannelLiveMonitor
from subscription import SubscriptionRequiredMiddleware


async def run_bot() -> None:
    settings = get_settings()
    session = AiohttpSession(proxy=settings.outbound_proxy_url or None)
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
        session=session,
    )
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(SubscriptionRequiredMiddleware())
    dispatcher.callback_query.outer_middleware(SubscriptionRequiredMiddleware())
    dispatcher.include_router(user_router)
    dispatcher.include_router(admin_router)

    try:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="Открыть бота"),
                ]
            )
            for admin_user_id in settings.admin_user_ids:
                try:
                    await bot.set_my_commands(
                        [
                            BotCommand(command="start", description="Открыть бота"),
                            BotCommand(command="admin_stats", description="Статистика использования"),
                            BotCommand(command="stats", description="Статистика треков"),
                            BotCommand(command="scan_channel", description="Сканировать канал"),
                            BotCommand(command="mark_unsuitable", description="Скрыть трек из выдачи"),
                            BotCommand(command="fix_track", description="Исправить BPM и key"),
                        ],
                        scope=BotCommandScopeChat(chat_id=admin_user_id),
                    )
                except TelegramBadRequest:
                    logging.warning(
                        "Skipped scoped admin commands for chat_id=%s because chat is not available yet",
                        admin_user_id,
                    )
        except TelegramUnauthorizedError as exc:
            env_file = os.getenv("APP_ENV_FILE", ".env")
            logging.error(
                "Telegram rejected bot authorization. Check TELEGRAM_BOT_TOKEN in %s.",
                env_file,
            )
            raise RuntimeError(f"Invalid TELEGRAM_BOT_TOKEN configured in {env_file}") from exc

        live_monitor_task = asyncio.create_task(run_live_monitor())
        try:
            await dispatcher.start_polling(bot)
        finally:
            live_monitor_task.cancel()
            await asyncio.gather(live_monitor_task, return_exceptions=True)
    finally:
        await bot.session.close()


async def run_live_monitor() -> None:
    await ChannelLiveMonitor().run()


async def run_api() -> None:
    settings = get_settings()
    app = create_app()
    server = Server(
        Config(
            app=app,
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
        )
    )
    try:
        await server.serve()
    except BaseException:
        logging.exception("API server stopped unexpectedly; bot will continue running without API")


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    await init_db()
    try:
        if settings.enable_api:
            await asyncio.gather(run_bot(), run_api())
        else:
            logging.info("Built-in API is disabled via ENABLE_API=false")
            await run_bot()
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
