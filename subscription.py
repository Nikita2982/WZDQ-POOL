from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Private channel that grants access to the bot.
CHANNEL_ID: str | int = settings.subscription_channel_id or settings.source_chat
CHECK_SUBSCRIPTION_CALLBACK = "check_subscription"
ALLOWED_STATUSES = {"member", "administrator", "creator"}
DENIED_STATUSES = {"left", "kicked", "restricted"}

SUBSCRIPTION_REQUIRED_TEXT = (
    "❌ Доступ к боту доступен только подписчикам канала WZDQ'S Pool 😔\n"
    "Приобрести подписку можно по <a href=\"https://t.me/wzdq_pool_pay_bot\">ссылке</a>."
)
SUBSCRIPTION_ERROR_TEXT = "⚠️ Не удалось проверить подписку. Попробуйте позже."
SUBSCRIPTION_IMAGE_PATH = "/Users/admin/Desktop/subscribe.png"


class SubscriptionCheckError(RuntimeError):
    """Raised when Telegram API cannot confirm channel membership."""


def _normalize_channel_id(channel_id: str | int) -> str | int:
    if isinstance(channel_id, str):
        value = channel_id.strip()
        if value and value.lstrip("-").isdigit():
            return int(value)
        return value
    return channel_id


def _subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Проверить подписку ✅", callback_data=CHECK_SUBSCRIPTION_CALLBACK)]
        ]
    )


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """Return True only for users who are active members of the private channel."""
    try:
        chat_member = await bot.get_chat_member(
            chat_id=_normalize_channel_id(CHANNEL_ID),
            user_id=user_id,
        )
    except TelegramAPIError as exc:
        logger.exception("Subscription check failed for user_id=%s in channel=%s", user_id, CHANNEL_ID)
        raise SubscriptionCheckError from exc

    status = getattr(chat_member, "status", "")
    if status in ALLOWED_STATUSES:
        return True
    if status in DENIED_STATUSES:
        return False
    return False


async def require_subscription(bot: Bot, event: Message | CallbackQuery, user_id: int) -> bool:
    """
    Check membership and show a consistent response for denied/error cases.

    Returns True when access is allowed and False otherwise.
    """
    try:
        subscribed = await is_subscribed(bot, user_id)
    except SubscriptionCheckError:
        await _notify_subscription_problem(event, SUBSCRIPTION_ERROR_TEXT, with_button=False)
        return False

    if subscribed:
        return True

    await _notify_subscription_problem(event, SUBSCRIPTION_REQUIRED_TEXT, with_button=True)
    return False


async def _notify_subscription_problem(
    event: Message | CallbackQuery,
    text: str,
    *,
    with_button: bool,
) -> None:
    reply_markup = _subscription_keyboard() if with_button else None

    async def send_with_fallback(bot: Bot, chat_id: int) -> None:
        if with_button:
            try:
                photo_bytes = open(SUBSCRIPTION_IMAGE_PATH, "rb").read()
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=BufferedInputFile(photo_bytes, filename="subscribe.png"),
                    caption=text,
                    reply_markup=reply_markup,
                )
                return
            except TelegramAPIError:
                logger.exception("Failed to send subscription photo, falling back to text only")
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await send_with_fallback(event.bot, event.message.chat.id)
        return

    await send_with_fallback(event.bot, event.chat.id)


class SubscriptionRequiredMiddleware(BaseMiddleware):
    """Protect all message/callback handlers with a single subscription check."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        if isinstance(event, CallbackQuery) and event.data == CHECK_SUBSCRIPTION_CALLBACK:
            return await handler(event, data)

        bot = data.get("bot") or getattr(event, "bot", None)
        if bot is None:
            logger.error("Subscription middleware could not resolve bot instance for event=%s", type(event).__name__)
            return None

        if await require_subscription(bot, event, user.id):
            return await handler(event, data)
        return None
