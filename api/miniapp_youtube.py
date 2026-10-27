from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import shutil
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from aiogram.types import BufferedInputFile
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update

from api.miniapp_auth import TelegramUser, current_user
from api.miniapp_models import MiniAppYouTubeJob
from config.settings import get_settings
from database.db import SessionLocal

router = APIRouter(prefix="/miniapp-api/youtube")
logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
AUDIO_ROOT = Path(os.environ.get("MINIAPP_YOUTUBE_AUDIO_DIR", str(ROOT / ".data/youtube-audio")))
AUDIO_TTL = 24 * 3600


def cleanup_audio():
    if AUDIO_ROOT.is_dir():
        for directory in AUDIO_ROOT.iterdir():
            if re.fullmatch(r"[0-9a-f]{32}", directory.name) and directory.is_dir() and not directory.is_symlink():
                if time.time() - directory.stat().st_mtime > AUDIO_TTL:
                    shutil.rmtree(directory)


def audio_path(job_id, audio_id):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id) or not re.fullmatch(r"[0-9a-f]{24}", audio_id):
        raise HTTPException(404, "Аудиофайл не найден.")
    path = AUDIO_ROOT / job_id / (audio_id + ".mp3")
    if not path.is_file() or time.time() - path.stat().st_mtime > AUDIO_TTL:
        raise HTTPException(410, "Срок хранения аудио истёк. Запусти поиск сета заново.")
    return path


def download_signature(job_id, audio_id, expires):
    return hmac.new(get_settings().telegram_bot_token.encode(),
                    f"youtube-audio:{job_id}:{audio_id}:{expires}".encode(), hashlib.sha256).hexdigest()



def normalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password or parsed.port:
            raise ValueError
        host = (parsed.hostname or "").lower()
        parts = parsed.path.strip("/").split("/")
        video = None
        if host == "youtu.be" and len(parts) == 1:
            video = parts[0]
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if parsed.path == "/watch":
                video = parse_qs(parsed.query).get("v", [""])[0]
            elif len(parts) == 2 and parts[0] in {"live", "shorts", "embed"}:
                video = parts[1]
        if not video or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
            raise ValueError
        return "https://www.youtube.com/watch?v=" + video
    except ValueError as exc:
        raise ValueError("Вставь ссылку на одно видео YouTube или youtu.be.") from exc


class AnalyzeRequest(BaseModel):
    url: str = Field(max_length=2048)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        return normalize_url(value)


def engine_paths():
    project = Path(os.environ.get("YOUTUBE_SETLIST_PROJECT", str(ROOT.parent / "youtube_setlist_bot"))).expanduser().resolve()
    interpreter = project / ".venv-shazam/bin/python"
    if not interpreter.is_file() or not (project / "setlist_bot/analyzer.py").is_file() or not shutil.which("ffmpeg"):
        raise HTTPException(503, "Анализатор YouTube пока не настроен на этом компьютере.")
    return project, interpreter


def serialize(row):
    tracks = json.loads(json.dumps(row.tracks))
    for track in tracks:
        audio = track.get("audio", {})
        if audio.get("status") == "ready":
            try:
                audio_path(row.id, audio.get("id", ""))
            except HTTPException:
                audio["status"] = "expired"
        elif row.status != "running" and audio.get("status") in {"queued", "searching", "downloading"}:
            audio["status"] = "stopped"
    return {"id": row.id, "url": row.url, "status": row.status, "progress": row.progress,
            "title": row.title, "report": row.report, "tracks": tracks,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def owned_job(session, job_id, user_id):
    row = await session.get(MiniAppYouTubeJob, job_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(404, "Разбор не найден.")
    return row


@router.get("/jobs")
async def history(user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        rows = (await session.scalars(select(MiniAppYouTubeJob).where(MiniAppYouTubeJob.user_id == user.id)
                                      .order_by(MiniAppYouTubeJob.created_at.desc()).limit(30))).all()
    return [serialize(row) for row in rows]


@router.post("/jobs", status_code=202)
async def start(body: AnalyzeRequest, request: Request, user: TelegramUser = Depends(current_user)):
    engine_paths()
    await asyncio.to_thread(cleanup_audio)
    state = request.app.state
    async with state.youtube_lock:
        if state.youtube_tasks:
            raise HTTPException(409, "Сейчас уже разбирается один сет. Дождись завершения и попробуй снова.")
        previous = state.youtube_limits.get(user.id, 0)
        if time.monotonic() - previous < 20:
            raise HTTPException(429, "Подожди немного перед следующим разбором.")
        row = MiniAppYouTubeJob(id=uuid.uuid4().hex, user_id=user.id, url=body.url, status="running",
                               progress="Получаем информацию о видео…", title="DJ-сет с YouTube", report="", tracks=[])
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        state.youtube_limits[user.id] = time.monotonic()
        state.youtube_tasks[row.id] = {"cancelled": False, "task": None}
        state.youtube_tasks[row.id]["task"] = asyncio.create_task(analyze_worker(request.app, row.id, body.url))
        return serialize(row)


@router.get("/jobs/{job_id}")
async def detail(job_id: str, user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        return serialize(await owned_job(session, job_id, user.id))


@router.post("/jobs/{job_id}/cancel")
async def cancel(job_id: str, request: Request, user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        row = await owned_job(session, job_id, user.id)
        item = request.app.state.youtube_tasks.get(job_id)
        if item:
            item["cancelled"] = True
            item["task"].cancel()
            row.status = "cancelled"
            row.progress = "Разбор отменён."
            await session.commit()
        return {"status": "cancelling" if item else row.status}


@router.post("/jobs/{job_id}/send")
async def send_report(job_id: str, request: Request, user: TelegramUser = Depends(current_user)):
    if get_settings().miniapp_local:
        raise HTTPException(403, "Отправка доступна при открытии приложения через Telegram.")
    async with SessionLocal() as session:
        row = await owned_job(session, job_id, user.id)
        if row.status != "completed" or not row.report:
            raise HTTPException(409, "Сначала дождись завершения разбора.")
        report, title = row.report, row.title
    try:
        await request.app.state.miniapp_bot.send_document(
            user.id, BufferedInputFile(report.encode(), filename="youtube-tracklist.txt"),
            caption=("🎧 Треклист: " + title)[:1000], request_timeout=30)
    except Exception as exc:
        logger.warning("YouTube report delivery failed: %s", type(exc).__name__)
        raise HTTPException(502, "Не удалось отправить. Открой чат с ботом, нажми «Начать» и попробуй снова.") from None
    return {"status": "sent"}


async def analyze_worker(app, job_id, url, audio_only=False):
    process = None
    status = "failed"
    message = "Разбор прервался. Попробуй снова."
    try:
        project, interpreter = engine_paths()
        # Use the original analyser's own configuration, not the Mini App bot's env.
        env = {key: value for key, value in os.environ.items() if key in {
            "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}}
        env["PYTHONUNBUFFERED"] = "1"
        process = await asyncio.create_subprocess_exec(
            str(interpreter), str(ROOT / "scripts/miniapp_youtube_worker.py"), str(project), url, str(AUDIO_ROOT / job_id),
            *(["--audio-only"] if audio_only else []),
            cwd=str(ROOT), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=1024 * 1024)
        async with asyncio.timeout(3 * 3600):
            while line := await process.stdout.readline():
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if event.get("type") == "progress":
                    async with SessionLocal() as session:
                        await session.execute(update(MiniAppYouTubeJob).where(MiniAppYouTubeJob.id == job_id)
                                              .values(progress=str(event.get("message", ""))[:6000],
                                                      tracks=event.get("tracks", [])[:1000]))
                        await session.commit()
                elif event.get("type") in {"report", "result"}:
                    async with SessionLocal() as session:
                        await session.execute(update(MiniAppYouTubeJob).where(MiniAppYouTubeJob.id == job_id).values(
                            title=str(event.get("title", "DJ-сет"))[:1000], report=str(event.get("report", ""))[:200000],
                            tracks=event.get("tracks", [])[:1000]))
                        await session.commit()
                    if event.get("type") == "result":
                        status = "completed"
                    report = str(event.get("report", ""))
                    warning = next((line for line in report.splitlines() if line.startswith("⏸")), "")
                    message = warning or "Разбор завершён. Список может быть неполным."
                elif event.get("type") == "error":
                    message = str(event.get("message", message))[:3000]
            await process.wait()
    except asyncio.CancelledError:
        cancelled = app.state.youtube_tasks.get(job_id, {}).get("cancelled", False)
        status = "cancelled" if cancelled else "interrupted"
        message = "Разбор отменён." if cancelled else "Разбор прерван при перезапуске приложения. Запусти его снова."
    except TimeoutError:
        message = "Превышено время анализа. Попробуй более короткую запись."
    except Exception as exc:
        logger.warning("YouTube worker failed: %s", type(exc).__name__)
    finally:
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        async with SessionLocal() as session:
            await session.execute(update(MiniAppYouTubeJob).where(MiniAppYouTubeJob.id == job_id)
                                  .values(status=status, progress=message))
            await session.commit()
        app.state.youtube_tasks.pop(job_id, None)


@router.post("/jobs/{job_id}/audio/{audio_id}/download")
async def prepare_download(job_id: str, audio_id: str, request: Request,
                           user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        row = await owned_job(session, job_id, user.id)
        track = next((track for track in row.tracks if track.get("audio", {}).get("id") == audio_id), None)
        if not track or track["audio"].get("status") != "ready":
            raise HTTPException(409, "Этот аудиофайл ещё не готов к скачиванию.")
        audio_path(job_id, audio_id)
        expires = int(time.time()) + 600
        signature = download_signature(job_id, audio_id, expires)
        path = f"/miniapp-api/youtube/files/{job_id}/{audio_id}?expires={expires}&signature={signature}"
        return {"url": path, "filename": track["audio"].get("filename", "track.mp3")}


@router.api_route("/files/{job_id}/{audio_id}", methods=["GET", "HEAD"])
async def download_audio_file(job_id: str, audio_id: str, expires: int = 0, signature: str = ""):
    if not re.fullmatch(r"[0-9a-f]{64}", signature) or not int(time.time()) < expires <= int(time.time()) + 610:
        raise HTTPException(403, "Ссылка истекла. Нажми «Скачать» ещё раз.")
    if not hmac.compare_digest(signature, download_signature(job_id, audio_id, expires)):
        raise HTTPException(403, "Нет доступа к аудиофайлу.")
    path = audio_path(job_id, audio_id)
    async with SessionLocal() as session:
        row = await session.get(MiniAppYouTubeJob, job_id)
        track = next((track for track in row.tracks if track.get("audio", {}).get("id") == audio_id), None) if row else None
        if not track or track["audio"].get("status") != "ready":
            raise HTTPException(404, "Аудиофайл не найден.")
        return FileResponse(path, media_type="audio/mpeg", filename=track["audio"].get("filename", "track.mp3"),
                            headers={"Cache-Control": "private, no-store",
                                     "Access-Control-Allow-Origin": "https://web.telegram.org",
                                     "Access-Control-Expose-Headers": "Content-Disposition"})


@router.post("/jobs/{job_id}/audio", status_code=202)
async def find_existing_audio(job_id: str, request: Request, user: TelegramUser = Depends(current_user)):
    engine_paths()
    state = request.app.state
    async with state.youtube_lock:
        if state.youtube_tasks:
            raise HTTPException(409, "Дождись завершения текущего поиска.")
        if time.monotonic() - state.youtube_limits.get(user.id, 0) < 20:
            raise HTTPException(429, "Подожди немного перед следующим поиском.")
        async with SessionLocal() as session:
            row = await owned_job(session, job_id, user.id)
            if row.status == "running" or not row.tracks:
                raise HTTPException(409, "Сначала дождись появления треклиста.")
            tracks = serialize(row)["tracks"]
            directory = AUDIO_ROOT / row.id
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "input.json").write_text(json.dumps({"tracks": tracks, "report": row.report, "title": row.title}))
            row.status, row.progress = "running", "Ищем и скачиваем аудиофайлы найденных треков…"
            await session.commit()
            state.youtube_limits[user.id] = time.monotonic()
            state.youtube_tasks[row.id] = {"cancelled": False, "task": None}
            state.youtube_tasks[row.id]["task"] = asyncio.create_task(analyze_worker(request.app, row.id, row.url, True))
            return serialize(row)
