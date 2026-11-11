from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit

import aiofiles
import aiohttp
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.enums import ChatAction
from aiogram.types import FSInputFile
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from api.miniapp_auth import TelegramUser, current_user
from config.settings import get_settings

router = APIRouter(prefix="/miniapp-api/spotify", tags=["spotify"])
logger = logging.getLogger(__name__)
SPOTIFY_TYPES = {"track", "album", "playlist"}
SPOTIFY_ID_RE = re.compile(r"^[A-Za-z0-9]{22}$")
AUDIO_BITRATE = "320"
AUDIO_FORMAT = "mp3"
UPSTREAM_AUDIO_FORMAT = "mp3"
AUDIO_LINK_TTL = 15 * 60
STREAM_CHUNK_SIZE = 64 * 1024


class SpotifyUrlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class SpotifyDeliveryTrack(BaseModel):
    track_id: str = Field(pattern=r"^[A-Za-z0-9]{22}$")
    title: str = Field(min_length=1, max_length=300)
    performer: str = Field(default="", max_length=300)


class SpotifyDeliveryRequest(BaseModel):
    tracks: list[SpotifyDeliveryTrack] = Field(min_length=1, max_length=100)


def canonical_spotify_url(value: str) -> tuple[str, str, str]:
    try:
        parsed = urlsplit(value.strip())
        if (parsed.scheme.lower() != "https" or parsed.hostname not in {"open.spotify.com", "www.open.spotify.com"}
                or parsed.username or parsed.password or parsed.port):
            raise ValueError
        parts = [part for part in parsed.path.split("/") if part and not part.startswith("intl-")]
        for index in range(len(parts) - 1):
            media_type, media_id = parts[index], parts[index + 1]
            if media_type in SPOTIFY_TYPES and SPOTIFY_ID_RE.fullmatch(media_id):
                return f"https://open.spotify.com/{media_type}/{media_id}", media_type, media_id
    except ValueError:
        pass
    raise HTTPException(400, "Пришли ссылку Spotify на трек, альбом или плейлист.")


def _api_key() -> str:
    key = get_settings().spotify_api_key.strip()
    if not key:
        raise HTTPException(503, "Интеграция Spotify ожидает API-ключ сервиса.")
    return key


async def _partner_json(path: str, params: dict[str, str]) -> dict:
    settings = get_settings()
    key = _api_key()
    base = settings.spotify_api_base_url.rstrip("/")
    timeout = aiohttp.ClientTimeout(total=40, connect=8, sock_read=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.get(
                f"{base}{path}",
                params=params,
                headers={"x-api-key": key, "Accept": "application/json"},
            ) as response:
                if response.status == 400:
                    raise HTTPException(400, "Сервис не распознал ссылку Spotify. Проверь её и попробуй снова.")
                if response.status != 200:
                    raise HTTPException(502, "Сервис загрузки Spotify временно недоступен.")
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise HTTPException(502, "Сервис загрузки вернул некорректный ответ.") from exc
    except HTTPException:
        raise
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise HTTPException(502, "Не удалось связаться с сервисом загрузки Spotify.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(502, "Сервис загрузки вернул некорректный ответ.")
    return payload


def _audio_signature(track_id: str, user_id: int, expires: int) -> str:
    settings = get_settings()
    message = f"spotify-audio:{track_id}:{AUDIO_BITRATE}:{AUDIO_FORMAT}:{user_id}:{expires}".encode()
    return hmac.new(settings.telegram_bot_token.encode(), message, hashlib.sha256).hexdigest()


def _audio_url(track_id: str, user_id: int) -> str:
    expires = int(time.time()) + AUDIO_LINK_TTL
    signature = _audio_signature(track_id, user_id, expires)
    return (f"/miniapp-api/spotify/audio/{track_id}?bitrate={AUDIO_BITRATE}&format={AUDIO_FORMAT}"
            f"&user_id={user_id}&expires={expires}&signature={signature}")


def _attach_audio_links(payload: dict, media_type: str, media_id: str, user_id: int) -> dict:
    result = dict(payload)
    raw_stream = result.pop("stream_url", None)
    if raw_stream and media_type == "track":
        result["audio_url"] = _audio_url(media_id, user_id)
    items = result.get("items")
    if isinstance(items, list):
        converted = []
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            item_stream = item.pop("stream_url", None)
            item_id = item.get("id")
            if item_stream and isinstance(item_id, str) and SPOTIFY_ID_RE.fullmatch(item_id):
                item["audio_url"] = _audio_url(item_id, user_id)
            converted.append(item)
        result["items"] = converted
    return result


@router.get("/status")
async def spotify_status(_: TelegramUser = Depends(current_user)) -> dict[str, bool]:
    return {"available": bool(get_settings().spotify_api_key.strip())}


@router.post("/item")
async def spotify_item(body: SpotifyUrlRequest, _: TelegramUser = Depends(current_user)):
    url, _, _ = canonical_spotify_url(body.url)
    return await _partner_json("/api/v1/wzdq/item", {"url": url})


@router.post("/download")
async def spotify_download(body: SpotifyUrlRequest, user: TelegramUser = Depends(current_user)):
    url, media_type, media_id = canonical_spotify_url(body.url)
    payload = await _partner_json(
        "/api/v1/wzdq/download",
        {"url": url, "audio_bitrate": AUDIO_BITRATE, "audio_format": UPSTREAM_AUDIO_FORMAT},
    )
    if payload.get("success") is False:
        detail = payload.get("detail") or payload.get("message")
        if isinstance(detail, dict):
            detail = detail.get("message")
        raise HTTPException(502, str(detail)[:240] if detail else "Сервис не смог подготовить трек.")
    return _attach_audio_links(payload, media_type, media_id, user.id)


def _safe_audio_filename(title: str, performer: str) -> str:
    raw_name = f"{performer} - {title}" if performer else title
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_name).strip(" .")
    return f"{(safe_name or 'spotify-track')[:140]}.mp3"


async def _download_spotify_file(track_id: str, destination: Path) -> int:
    settings = get_settings()
    key = _api_key()
    url = f"{settings.spotify_api_base_url.rstrip('/')}/api/v1/wzdq/stream/{quote(track_id)}"
    max_bytes = settings.bot_max_audio_upload_bytes
    timeout = aiohttp.ClientTimeout(total=240, connect=8, sock_read=60)
    total = 0
    try:
        async with aiohttp.ClientSession(timeout=timeout, auto_decompress=False) as client:
            async with client.get(
                url,
                params={"audio_bitrate": AUDIO_BITRATE, "audio_format": UPSTREAM_AUDIO_FORMAT},
                headers={"x-api-key": key, "Accept": "audio/*"},
            ) as response:
                if response.status == 404:
                    raise RuntimeError("Аудио пока недоступно у сервиса. Попробуй отправить трек ещё раз через минуту.")
                if response.status != 200:
                    raise RuntimeError("Сервис пока не отдаёт аудиофайл. Попробуй ещё раз позже.")
                content_type = response.headers.get("Content-Type", "")
                if not content_type.startswith("audio/") and content_type != "application/octet-stream":
                    raise RuntimeError("Сервис вернул не аудиофайл. Попробуй ещё раз позже.")
                length = response.headers.get("Content-Length")
                if length and int(length) > max_bytes:
                    raise RuntimeError("Файл слишком большой для отправки через Telegram.")
                async with aiofiles.open(destination, "wb") as output:
                    async for chunk in response.content.iter_chunked(STREAM_CHUNK_SIZE):
                        total += len(chunk)
                        if total > max_bytes:
                            raise RuntimeError("Файл слишком большой для отправки через Telegram.")
                        await output.write(chunk)
        if total == 0:
            raise RuntimeError("Сервис вернул пустой аудиофайл. Попробуй ещё раз.")
        # Partner returns MP3 at the requested bitrate. Keep the original bytes:
        # transcoding it again would waste time and may degrade the audio.
        return total
    except Exception:
        destination.unlink(missing_ok=True)
        raise


async def _animate_delivery_message(bot, chat_id: int, message_id: int, job: dict, stop: asyncio.Event):
    frames = ("◐", "◓", "◑", "◒")
    index = 0
    while not stop.is_set():
        current = job["tracks"][min(job["current_index"], len(job["tracks"]) - 1)]
        if len(job["tracks"]) > 1:
            text = f"{frames[index % len(frames)]} Отправляю трек {job['current_index'] + 1} из {len(job['tracks'])}…\n{current.title}"
        else:
            text = f"{frames[index % len(frames)]} Скачиваю и отправляю трек…\n{current.title}"
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except TelegramAPIError:
            pass
        index += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            continue


async def _send_chat_action(bot, chat_id: int, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        except TelegramAPIError:
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
        except TimeoutError:
            continue


async def _spotify_delivery_worker(app, job_id: str):
    state = app.state
    job = state.spotify_delivery_jobs[job_id]
    chat_id = job["user_id"]
    bot = state.miniapp_bot
    tracks = job["tracks"]
    status_message_id = job["message_id"]
    stop_animation = asyncio.Event()
    animation_task: asyncio.Task | None = None
    try:
        async with state.spotify_delivery_slots:
            job["status"] = "sending"
            animation_task = asyncio.create_task(_animate_delivery_message(
                bot, chat_id, status_message_id, job, stop_animation,
            ))
            settings = get_settings()
            for index, track in enumerate(tracks):
                job["current_index"] = index
                file_path: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        prefix="spotify-", suffix=".mp3", dir=settings.temp_audio_dir, delete=False,
                    ) as temporary:
                        file_path = Path(temporary.name)
                    await _download_spotify_file(track.track_id, file_path)

                    stop_action = asyncio.Event()
                    action_task = asyncio.create_task(_send_chat_action(bot, chat_id, stop_action))
                    try:
                        await bot.send_audio(
                            chat_id=chat_id,
                            audio=FSInputFile(file_path, filename=_safe_audio_filename(track.title, track.performer)),
                            title=track.title,
                            performer=track.performer or None,
                        )
                    finally:
                        stop_action.set()
                        await action_task
                    job["sent_track_ids"].append(track.track_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Spotify playlist item delivery failed: job_id=%s track_id=%s", job_id, track.track_id)
                    job["failed_track_ids"].append(track.track_id)
                finally:
                    if file_path:
                        file_path.unlink(missing_ok=True)

            sent_count = len(job["sent_track_ids"])
            failed_count = len(job["failed_track_ids"])
            job["status"] = "completed" if sent_count == len(tracks) else "partial" if sent_count else "failed"
            if job["status"] == "completed":
                job["message"] = f"Отправлено треков: {sent_count} из {len(tracks)}."
            elif sent_count:
                job["message"] = f"Отправлено треков: {sent_count} из {len(tracks)}. Не удалось отправить: {failed_count}."
            else:
                job["message"] = "Не получилось отправить треки. Попробуй ещё раз из Mini App."
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=status_message_id,
                    text=(f"✅ Отправил в чат {sent_count} из {len(tracks)} треков."
                          if job["status"] == "completed" else
                          f"⚠️ Отправил {sent_count} из {len(tracks)} треков. Не удалось: {failed_count}."),
                )
            except TelegramAPIError:
                pass
    except asyncio.CancelledError:
        job["status"] = "interrupted"
        job["message"] = "Отправка прервалась. Запусти её ещё раз из Mini App."
        raise
    except Exception:
        logger.exception("Spotify track delivery failed: job_id=%s user_id=%s", job_id, chat_id)
        job["status"] = "failed"
        job["message"] = "Не получилось отправить трек. Попробуй ещё раз из Mini App."
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=status_message_id,
                text="⚠️ Не получилось отправить треки. Попробуй ещё раз из Mini App.",
            )
        except TelegramAPIError:
            pass
    finally:
        stop_animation.set()
        if animation_task:
            await asyncio.gather(animation_task, return_exceptions=True)
        state.spotify_delivery_active.pop(chat_id, None)


@router.post("/deliver", status_code=202)
async def deliver_spotify_track(
    body: SpotifyDeliveryRequest,
    request: Request,
    user: TelegramUser = Depends(current_user),
):
    state = request.app.state
    now = time.time()
    for old_job_id, old_job in list(state.spotify_delivery_jobs.items()):
        if old_job["status"] in {"completed", "partial", "failed", "interrupted"} and now - old_job["created_at"] > 3600:
            state.spotify_delivery_jobs.pop(old_job_id, None)
    if user.id in state.spotify_delivery_active:
        raise HTTPException(409, "Дождись отправки предыдущего трека в Telegram.")
    if len(state.spotify_delivery_active) >= 8:
        raise HTTPException(429, "Сейчас отправляется много треков. Попробуй ещё раз через минуту.")

    tracks = [track.model_copy(update={"title": track.title.strip(), "performer": track.performer.strip()})
              for track in body.tracks]
    if any(not track.title for track in tracks):
        raise HTTPException(422, "У трека должно быть название.")
    first_title = tracks[0].title
    status_text = (f"⏳ Подготавливаю {len(tracks)} треков для отправки в чат:\n{first_title}"
                   if len(tracks) > 1 else f"⏳ Подготавливаю трек для отправки в чат:\n{first_title}")
    state.spotify_delivery_active[user.id] = "starting"
    try:
        status_message = await state.miniapp_bot.send_message(
            chat_id=user.id,
            text=status_text,
        )
    except asyncio.CancelledError:
        state.spotify_delivery_active.pop(user.id, None)
        raise
    except TelegramForbiddenError as exc:
        state.spotify_delivery_active.pop(user.id, None)
        raise HTTPException(403, "Открой чат с ботом и нажми Start, затем повтори отправку.") from exc
    except TelegramAPIError as exc:
        state.spotify_delivery_active.pop(user.id, None)
        if "chat not found" in str(exc).lower() or "can't initiate conversation" in str(exc).lower():
            raise HTTPException(403, "Открой чат с ботом и нажми Start, затем повтори отправку.") from exc
        logger.warning("Could not start Spotify delivery message: %s", type(exc).__name__)
        raise HTTPException(502, "Не получилось написать в чат с ботом. Открой бота и попробуй ещё раз.") from exc
    except Exception as exc:
        state.spotify_delivery_active.pop(user.id, None)
        logger.warning("Could not start Spotify delivery message: %s", type(exc).__name__)
        raise HTTPException(502, "Не получилось написать в чат с ботом. Открой бота и попробуй ещё раз.") from exc

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "user_id": user.id,
        "tracks": tracks,
        "current_index": 0,
        "sent_track_ids": [],
        "failed_track_ids": [],
        "message_id": status_message.message_id,
        "status": "queued",
        "message": (f"Готовлю {len(tracks)} треков и отправлю их по очереди в чат."
                    if len(tracks) > 1 else "Готовлю трек и отправлю его следующим сообщением."),
        "created_at": time.time(),
    }
    state.spotify_delivery_jobs[job_id] = job
    state.spotify_delivery_active[user.id] = job_id
    task = asyncio.create_task(_spotify_delivery_worker(request.app, job_id))
    state.spotify_delivery_tasks.add(task)
    task.add_done_callback(state.spotify_delivery_tasks.discard)
    return {"job_id": job_id, "status": job["status"]}


@router.get("/deliver/{job_id}")
async def spotify_delivery_status(job_id: str, request: Request, user: TelegramUser = Depends(current_user)):
    job = request.app.state.spotify_delivery_jobs.get(job_id)
    if not job or job["user_id"] != user.id:
        raise HTTPException(404, "Отправка не найдена.")
    return {
        "job_id": job_id,
        "status": job["status"],
        "message": job["message"],
        "sent_track_ids": job["sent_track_ids"],
        "failed_track_ids": job["failed_track_ids"],
    }


@router.get("/audio/{track_id}")
async def spotify_audio(
    track_id: str,
    user_id: int,
    expires: int,
    signature: str,
    bitrate: str = AUDIO_BITRATE,
    media_format: str = Query(default=AUDIO_FORMAT, alias="format"),
):
    now = int(time.time())
    if (
        not SPOTIFY_ID_RE.fullmatch(track_id)
        or bitrate != AUDIO_BITRATE
        or media_format != AUDIO_FORMAT
        or not now < expires <= now + AUDIO_LINK_TTL + 30
        or not re.fullmatch(r"[0-9a-f]{64}", signature)
        or not hmac.compare_digest(signature, _audio_signature(track_id, user_id, expires))
    ):
        raise HTTPException(403, "Ссылка на файл истекла. Запусти загрузку ещё раз.")

    settings = get_settings()
    try:
        with tempfile.NamedTemporaryFile(
            prefix="spotify-audio-", suffix=".mp3", dir=settings.temp_audio_dir, delete=False,
        ) as output:
            output_path = Path(output.name)
    except OSError as exc:
        raise HTTPException(503, "Не удалось подготовить MP3-файл. Попробуй позже.") from exc
    try:
        try:
            await _download_spotify_file(track_id, output_path)
        except RuntimeError as exc:
            status = 404 if "недоступно" in str(exc).lower() else 502
            raise HTTPException(status, str(exc)) from exc
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise HTTPException(502, "Не удалось получить аудио для преобразования в MP3.") from exc
        download_name = f"spotify-{track_id}.mp3"
        return FileResponse(
            output_path,
            media_type="audio/mpeg",
            filename=download_name,
            headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"},
            background=BackgroundTask(output_path.unlink, missing_ok=True),
        )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
