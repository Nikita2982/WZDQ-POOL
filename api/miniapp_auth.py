"""Verify raw Telegram initData. Never trust a user id supplied by the browser.

Protocol: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, Request

from config.settings import get_settings
from subscription import SubscriptionCheckError, is_subscribed


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str
    username: str | None = None


def validate_init_data(raw: str, token: str, max_age: int = 3600, *, now: int | None = None) -> TelegramUser:
    try:
        if not raw or len(raw) > 16384:
            raise ValueError
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(pairs) != len(data):
            raise ValueError
        received = data.pop("hash")
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            raise ValueError
        age = (int(time.time()) if now is None else now) - int(data["auth_date"])
        if age < -30 or age > max_age:
            raise ValueError
        user = json.loads(data["user"])
        user_id = user["id"]
        if type(user_id) is not int or not 0 < user_id < 2**53:
            raise ValueError
        return TelegramUser(user_id, str(user.get("first_name", "DJ"))[:128], user.get("username"))
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise HTTPException(401, "Открой приложение заново через Telegram.") from exc


async def current_user(request: Request, authorization: str = Header(default="")) -> TelegramUser:
    settings = get_settings()
    if settings.miniapp_local:
        if authorization:
            raise HTTPException(401, "В локальном режиме используется профиль DJ.")
        if (request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}
                and request.url.hostname in {"127.0.0.1", "localhost", "::1", "testserver"}):
            return TelegramUser(0, "DJ")
        raise HTTPException(403, "Локальный режим доступен только на этом компьютере.")
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "tma":
        raise HTTPException(401, "Открой приложение через кнопку в боте.")
    user = validate_init_data(raw, settings.telegram_bot_token, settings.miniapp_auth_max_age)
    try:
        subscribed = await is_subscribed(request.app.state.miniapp_bot, user.id)
    except SubscriptionCheckError as exc:
        raise HTTPException(503, "Не удалось проверить подписку. Попробуй ещё раз.") from exc
    if not subscribed:
        raise HTTPException(403, "Приложение доступно подписчикам WZDQ Pool.")
    return user


async def admin_user(request: Request, authorization: str = Header(default="")) -> TelegramUser:
    user = await current_user(request, authorization)
    if user.id not in get_settings().admin_user_ids:
        raise HTTPException(403, "Требуются права администратора.")
    return user
