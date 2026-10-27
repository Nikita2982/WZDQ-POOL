"""Curated video metadata. Access uses the same pool membership as the Mini App."""
import asyncio
import hashlib
import hmac
import shutil
import time
import uuid
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from api.miniapp_models import MiniAppKnowledgeVideo
from database.db import SessionLocal
from config.settings import get_settings
from pydantic import BaseModel, Field, field_validator

from api.miniapp_auth import TelegramUser, current_user

router = APIRouter(prefix="/miniapp-api")
CATALOG = Path(__file__).resolve().parents[1] / "assets/knowledge/catalog.json"
logger = logging.getLogger(__name__)
MEDIA_ROOT = CATALOG.parents[2] / ".data/knowledge/videos"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
RESERVE_BYTES = 256 * 1024 * 1024


def can_upload(user):
    settings = get_settings()
    owners = settings.admin_user_ids
    return not settings.miniapp_local and len(owners) == 1 and user.id in owners


async def upload_owner(user: TelegramUser = Depends(current_user)):
    if not can_upload(user):
        raise HTTPException(403, "Добавлять видео может только владелец приложения.")
    return user


def media_signature(video_id, asset, expires):
    secret = get_settings().telegram_bot_token.encode()
    payload = f"knowledge-media:{video_id}:{asset}:{expires}".encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def media_url(video_id, asset="video"):
    expires = int(time.time()) + 7200
    return f"/miniapp-api/knowledge/videos/{video_id}/{asset}?expires={expires}&signature={media_signature(video_id, asset, expires)}"


async def inspect_video(path):
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    except FileNotFoundError:
        raise HTTPException(503, "Обработка видео пока недоступна.") from None
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 30)
        data = json.loads(output)
        video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
        formats = set(data.get("format", {}).get("format_name", "").split(","))
        if process.returncode or not video or float(data.get("format", {}).get("duration", 0)) <= 0:
            raise ValueError
        if "mp4" in formats and video.get("codec_name") == "h264":
            return ".mp4", "video/mp4", False
        if "mp4" in formats and video.get("codec_name") == "hevc":
            return ".mp4", "video/mp4", True
        if "webm" in formats and video.get("codec_name") in {"vp8", "vp9", "av1"}:
            return ".webm", "video/webm", False
    except (ValueError, KeyError, TypeError):
        pass
    except asyncio.TimeoutError:
        raise HTTPException(422, "Не удалось проверить видео вовремя.") from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    raise HTTPException(422, "Выбери видео MP4, MOV (H.264/HEVC) или WebM. Этот файл не поддерживается.")


async def prepare_video(source, target):
    if shutil.disk_usage(source.parent).free < RESERVE_BYTES + min(MAX_UPLOAD_BYTES, source.stat().st_size * 2):
        raise HTTPException(507, "Недостаточно места для подготовки видео.")
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-c:v", "libx264",
            "-threads", "2", "-preset", "veryfast", "-crf", "20", "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(target),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    except FileNotFoundError:
        raise HTTPException(503, "Подготовка видео временно недоступна.") from None
    started = time.monotonic()
    try:
        while process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), 1)
            except asyncio.TimeoutError:
                if time.monotonic() - started > 600:
                    raise HTTPException(422, "Подготовка заняла слишком много времени. Попробуй более короткое видео.") from None
                if (target.exists() and target.stat().st_size > MAX_UPLOAD_BYTES) or shutil.disk_usage(source.parent).free < RESERVE_BYTES:
                    raise HTTPException(507, "Не хватает места для подготовленного видео. Выбери файл меньшего размера.") from None
        if process.returncode or not target.is_file() or not target.stat().st_size:
            raise HTTPException(422, "Не удалось подготовить видео. Попробуй другой файл.")
        if target.stat().st_size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "После подготовки видео превышает 500 МБ. Выбери более короткое видео.")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def make_thumbnail(path, target):
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(path),
            "-frames:v", "1", "-vf", "scale=720:-2", str(target),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(process.wait(), 30)
    except (OSError, asyncio.TimeoutError):
        target.unlink(missing_ok=True)
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()



class KnowledgeVideo(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(max_length=2048)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="Уроки", max_length=80)
    thumbnail_url: str = Field(default="", max_length=2048)

    @field_validator("url", "thumbnail_url")
    @classmethod
    def safe_url(cls, value, info):
        if info.field_name == "thumbnail_url" and not value:
            return value
        try:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port:
                raise ValueError
        except ValueError:
            raise ValueError("Требуется HTTPS-ссылка без логина и пароля.") from None
        return value


def read_catalog():
    try:
        data = json.loads(CATALOG.read_text())
        videos = [KnowledgeVideo.model_validate(row) for row in data["videos"]]
        if len({row.id for row in videos}) != len(videos):
            raise ValueError("Duplicate video IDs")
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Knowledge catalog could not be loaded")
        raise HTTPException(503, "Библиотека временно недоступна. Попробуй позже.") from None
    return videos


@router.get("/knowledge")
async def knowledge(user: TelegramUser = Depends(current_user)):
    videos = read_catalog()
    async with SessionLocal() as session:
        uploaded = (await session.scalars(select(MiniAppKnowledgeVideo)
                                          .order_by(MiniAppKnowledgeVideo.created_at.desc(), MiniAppKnowledgeVideo.id))).all()
    rows = [{"id": row.id, "title": row.title, "url": media_url(row.id), "uploaded": True,
             "description": "", "category": "Уроки",
             "thumbnail_url": media_url(row.id, "thumbnail") if (MEDIA_ROOT / f"{row.id}.jpg").is_file() else ""}
            for row in uploaded]
    return {"videos": rows + [row.model_dump() for row in videos], "can_upload": can_upload(user),
            "max_upload_bytes": MAX_UPLOAD_BYTES}


@router.post("/knowledge/videos", status_code=201)
async def upload_video(request: Request, title: str = Query(min_length=1, max_length=300),
                       user: TelegramUser = Depends(upload_owner)):
    title = title.strip()
    if not title:
        raise HTTPException(422, "Укажи название видео.")
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Видео слишком большое. Максимум — 500 МБ.")
    if shutil.disk_usage(MEDIA_ROOT).free < RESERVE_BYTES + (int(length) if length.isdigit() else MAX_UPLOAD_BYTES):
        raise HTTPException(507, "Недостаточно свободного места для видео.")
    video_id = uuid.uuid4().hex
    temporary = MEDIA_ROOT / f"{video_id}.part"
    saved = None
    thumbnail = MEDIA_ROOT / f"{video_id}.jpg"
    committed = False
    try:
        size = 0
        with temporary.open("xb") as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Видео слишком большое. Максимум — 500 МБ.")
                if shutil.disk_usage(MEDIA_ROOT).free < RESERVE_BYTES + len(chunk):
                    raise HTTPException(507, "Недостаточно свободного места для видео.")
                output.write(chunk)
        if not size:
            raise HTTPException(422, "Выбран пустой файл.")
        extension, media_type, needs_conversion = await inspect_video(temporary)
        saved = MEDIA_ROOT / f"{video_id}{extension}"
        if needs_conversion:
            await prepare_video(temporary, saved)
        else:
            temporary.rename(saved)
        await make_thumbnail(saved, thumbnail)
        async with SessionLocal() as session:
            session.add(MiniAppKnowledgeVideo(id=video_id, title=title, filename=saved.name,
                                              media_type=media_type, uploaded_by=user.id))
            await session.commit()
        committed = True
        return {"id": video_id, "title": title}
    finally:
        temporary.unlink(missing_ok=True)
        if not committed:
            if saved:
                saved.unlink(missing_ok=True)
            thumbnail.unlink(missing_ok=True)


@router.get("/knowledge/videos/{video_id}/{asset}")
async def serve_video(video_id: str, asset: str, expires: int = 0, signature: str = ""):
    if asset not in {"video", "thumbnail"} or not re.fullmatch(r"[0-9a-f]{64}", signature) or expires <= int(time.time()) or expires > int(time.time()) + 7300:
        raise HTTPException(403, "Ссылка истекла. Открой раздел заново.")
    if not hmac.compare_digest(signature, media_signature(video_id, asset, expires)):
        raise HTTPException(403, "Нет доступа к видео.")
    async with SessionLocal() as session:
        row = await session.get(MiniAppKnowledgeVideo, video_id)
        if row is None:
            raise HTTPException(404, "Видео не найдено.")
        path = MEDIA_ROOT / (f"{row.id}.jpg" if asset == "thumbnail" else row.filename)
        if not path.is_file():
            raise HTTPException(404, "Файл не найден.")
        return FileResponse(path, media_type="image/jpeg" if asset == "thumbnail" else row.media_type,
                            headers={"Cache-Control": "private, no-store"})
