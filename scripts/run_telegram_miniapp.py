"""Run a computer-hosted Mini App for pool members with a temporary bot menu."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import GetChatMenuButton, SetChatMenuButton
from aiogram.types import MenuButtonWebApp, WebAppInfo


def tunnel_origin(output: str) -> str | None:
    match = re.search(r"https://[a-zA-Z0-9.-]+\.(?:lhr\.life|free\.pinggy\.net|run\.pinggy-free\.link)(?=[/\s]|$)", output)
    return match.group() if match else None


def tunnel_command(port: int, provider: str) -> list[str]:
    options = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
               "-o", "ServerAliveCountMax=3", "-o", "StrictHostKeyChecking=accept-new",
               "-o", "IdentityAgent=none"]
    if provider == "pinggy":
        return options + ["-p", "443", "-o", "UserKnownHostsFile=/tmp/wzdq-pinggy-known-hosts",
                          "-o", "IdentitiesOnly=yes", "-i", str(ROOT / ".sessions/miniapp_tunnel_ed25519"),
                          "-R", f"0:127.0.0.1:{port}", "free.pinggy.io"]
    if provider == "localhost":
        return options + ["-o", "UserKnownHostsFile=/tmp/wzdq-app-known-hosts",
                          "-o", "IdentityFile=none", "-R", f"80:127.0.0.1:{port}", "nokey@localhost.run"]
    raise ValueError("Unknown tunnel provider")


def external_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError("MINIAPP_PUBLIC_ORIGIN должен содержать только HTTPS-адрес без пути.")
    return value.rstrip("/")


def check_public_app(origin: str) -> None:
    # Use a browser UA so interstitial pages cannot pass a non-browser probe.
    headers = {"Cache-Control": "no-cache", "User-Agent": "Mozilla/5.0 (WZDQ Mini App probe)"}
    request = urllib.request.Request(origin + "/app/?probe=" + str(time.time_ns()), headers=headers)
    with urllib.request.urlopen(request, timeout=8) as response:
        if b"telegram-web-app.js" not in response.read():
            raise ConnectionError("Вместо приложения открывается служебная страница туннеля.")
    for path, body in [("/miniapp-api/tracks", None),
                       ("/miniapp-api/youtube/jobs/00000000000000000000000000000000/audio", b"{}")]:
        request = urllib.request.Request(origin + path, data=body,
                                         headers={**headers, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=8):
                pass
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                continue
            raise
        raise RuntimeError("API вернул неподходящий ответ без авторизации.")


async def menu_request(bot, method):
    session = await bot.session.create_session()
    endpoint = bot.session.api.api_url(bot.token, method.__api_method__.lower())
    # Bot API supports GET for these menu methods. JSON POST acknowledged the
    # shared menu update here without returning the changed default afterwards;
    # query parameters were verified against both shared and scoped menus.
    params = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
              for key, value in method.model_dump(mode="json", exclude_none=True).items()}
    params["_wzdq_request"] = str(time.time_ns())
    async with session.get(endpoint, params=params,
                            headers={"Cache-Control": "no-cache"}, timeout=20) as response:
        return bot.session.check_response(bot=bot, method=method, status_code=response.status,
                                          content=await response.text()).result


async def get_menu(bot: Bot, chat_id: int | None = None):
    return await menu_request(bot, GetChatMenuButton(chat_id=chat_id))


async def set_menu(bot: Bot, chat_id: int | None, menu) -> None:
    await menu_request(bot, SetChatMenuButton(chat_id=chat_id, menu_button=menu))


async def ensure_menu_current(bot: Bot, targets: list, url: str) -> None:
    """Keep the shared menu and known per-chat overrides on the active address."""
    for chat_id in targets:
        current = await get_menu(bot, chat_id)
        current_url = getattr(getattr(current, "web_app", None), "url", None)
        if current_url != url or getattr(current, "text", None) != "Открыть приложение":
            await set_menu(bot, chat_id, MenuButtonWebApp(
                text="Открыть приложение", web_app=WebAppInfo(url=url)))
            print("Обновлена общая кнопка приложения." if chat_id is None else "Обновлена персональная кнопка приложения.", flush=True)


async def main():
    os.chdir(ROOT)
    os.environ["MINIAPP_LOCAL"] = "false"
    os.environ["MINIAPP_DELIVERY_ENABLED"] = "true"
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///dj_ai_bot_miniapp.db"
    from config.settings import get_settings
    settings = get_settings()
    if not settings.admin_user_ids:
        raise RuntimeError("Укажи ADMIN_USER_IDS для проверки подключения к пулу.")
    port = int(os.environ.get("MINIAPP_TELEGRAM_PORT", "8082"))
    saved_origin_path = ROOT / ".sessions/miniapp-public-origin"
    saved_origin = saved_origin_path.read_text().strip() if saved_origin_path.exists() else ""
    configured_origin = os.environ.get("MINIAPP_PUBLIC_ORIGIN", saved_origin)
    provider = os.environ.get("MINIAPP_TUNNEL_PROVIDER", "external" if configured_origin else "localhost")
    origin_override = external_origin(configured_origin) if provider == "external" else None
    command = tunnel_command(port, provider) if origin_override is None else None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    children = []
    previous = {}
    bot = Bot(settings.telegram_bot_token,
              session=AiohttpSession(proxy=settings.outbound_proxy_url or None, timeout=20))
    try:
        me = await bot.get_me()
        # Verify that the existing bot can actually check the private pool.
        from subscription import CHANNEL_ID, _normalize_channel_id
        member = await bot.get_chat_member(_normalize_channel_id(CHANNEL_ID), me.id)
        if member.status not in {"administrator", "creator"}:
            raise RuntimeError("Бот должен быть администратором пула для проверки участников.")
        allowed = []
        from subscription import is_subscribed
        for user_id in sorted(settings.admin_user_ids):
            if await is_subscribed(bot, user_id):
                allowed.append(user_id)
        if not allowed:
            raise RuntimeError("Администраторы из ADMIN_USER_IDS не состоят в пуле.")
        if provider == "pinggy":
            identity = ROOT / ".sessions/miniapp_tunnel_ed25519"
            identity.parent.mkdir(exist_ok=True)
            if not identity.exists():
                keygen = await asyncio.create_subprocess_exec(
                    "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "wzdq-local-preview", "-f", str(identity))
                if await keygen.wait():
                    raise RuntimeError("Не удалось создать отдельный ключ тестового туннеля.")
        prep = await asyncio.create_subprocess_exec(sys.executable, "scripts/prepare_miniapp_db.py")
        if await prep.wait():
            raise RuntimeError("Не удалось подготовить локальную базу.")
        server = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn", "api.miniapp_app:create_app", "--factory",
            "--host", "127.0.0.1", "--port", str(port), "--no-proxy-headers")
        children.append(server)
        def health():
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                    return json.load(response).get("status") == "ok"
            except (OSError, ValueError):
                return False
        for _ in range(100):
            if server.returncode is not None:
                raise RuntimeError("Сервер приложения остановился; проверь порт.")
            if await asyncio.to_thread(health):
                break
            await asyncio.sleep(.1)
        else:
            raise RuntimeError("Локальное приложение не запустилось.")
        # The default menu reaches members who have no per-chat override.
        # Keep the known admin overrides in sync with the same current tunnel URL.
        menu_targets = [None, *allowed]
        for user_id in menu_targets:
            previous[user_id] = await get_menu(bot, user_id)
        if origin_override:
            # Funnel owns the public endpoint independently of this API process.
            # Preserve its address through reconnects; never rotate the Telegram URL.
            url = f"{origin_override}/app/"
            announced = False
            while not stop.is_set():
                if server.returncode is not None:
                    raise RuntimeError("Локальный сервер остановился.")
                try:
                    await asyncio.to_thread(check_public_app, origin_override)
                    await ensure_menu_current(bot, menu_targets, url)
                    if not announced:
                        print(f"ГОТОВО: https://t.me/{me.username}\nHTTPS: {url}", flush=True)
                        announced = True
                except Exception as exc:
                    print(f"Ожидаем внешний HTTPS-адрес: {type(exc).__name__}", flush=True)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=15)
                except asyncio.TimeoutError:
                    pass
            return
        retry_delay = 2
        while not stop.is_set():
            tunnel = None
            reader = None
            try:
                tunnel = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                children.append(tunnel)
                addresses = asyncio.Queue()
                async def read_addresses():
                    selected = None
                    while line := await tunnel.stdout.readline():
                        origin = tunnel_origin(line.decode(errors="replace"))
                        # Pinggy announces two aliases for one tunnel; choose the first once.
                        if origin and (provider == "localhost" or selected is None):
                            selected = origin
                            await addresses.put(origin)
                reader = asyncio.create_task(read_addresses())
                print("Подключаем HTTPS-туннель…", flush=True)
                origin = await asyncio.wait_for(addresses.get(), timeout=45)
                while True:
                    # A rotating tunnel can announce a replacement domain on the same SSH connection.
                    await asyncio.to_thread(check_public_app, origin)
                    url = f"{origin}/app/?launch={time.time_ns()}"
                    await ensure_menu_current(bot, menu_targets, url)
                    print(f"ГОТОВО: https://t.me/{me.username}", flush=True)
                    print(f"HTTPS: {url}", flush=True)
                    print("Участники пула: откройте бота и нажмите «Открыть приложение».", flush=True)
                    if provider == "pinggy":
                        print("Pinggy Free: сессия до 60 минут. При первом входе посетитель подтверждает Enter site.", flush=True)
                    retry_delay = 2
                    failures = 0
                    while not stop.is_set():
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=15)
                            break
                        except asyncio.TimeoutError:
                            pass
                        if server.returncode is not None:
                            raise RuntimeError("Локальный сервер остановился.")
                        if tunnel.returncode is not None or reader.done():
                            raise ConnectionError("Туннель отключился.")
                        if not addresses.empty():
                            replacement = addresses.get_nowait()
                            if replacement != origin:
                                origin = replacement
                                break
                        try:
                            await asyncio.to_thread(check_public_app, origin)
                            await ensure_menu_current(bot, menu_targets, url)
                            failures = 0
                        except Exception:
                            failures += 1
                            if failures >= 2:
                                raise ConnectionError("HTTPS-адрес перестал отвечать.")
                    if stop.is_set():
                        break
            except Exception as exc:
                print(f"Переподключаем туннель: {type(exc).__name__}", flush=True)
                if server.returncode is not None:
                    raise RuntimeError("Локальный сервер остановился.") from None
            finally:
                if reader:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                if tunnel and tunnel.returncode is None:
                    tunnel.terminate()
                    try:
                        await asyncio.wait_for(tunnel.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        tunnel.kill()
                        await tunnel.wait()
                if tunnel in children:
                    children.remove(tunnel)
            if not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=retry_delay)
                except asyncio.TimeoutError:
                    pass
                retry_delay = min(30, retry_delay * 2)
    finally:
        for user_id, menu in previous.items():
            try:
                await set_menu(bot, user_id, menu)
            except Exception as exc:
                print(f"Не удалось восстановить меню: {type(exc).__name__}. Повтори запуск.", flush=True)
        for process in reversed(children):
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # Network exceptions can contain bot-token URLs; do not dump those.
        print(f"Запуск не завершён: {type(exc).__name__}", file=sys.stderr)
        if isinstance(exc, RuntimeError):
            print(str(exc), file=sys.stderr)
        sys.exit(1)
