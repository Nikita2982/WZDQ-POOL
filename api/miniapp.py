from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, model_validator
from sqlalchemy import func, select, update

from api.miniapp_auth import TelegramUser, current_user
from bot.services.audio_delivery import AudioDeliveryService
from bot.services.playlist_generator import generate_dj_playlist
from config.settings import get_settings
from database.crud import get_tracks_for_genre
from database.db import SessionLocal
from api.miniapp_models import MiniAppSet
from api.miniapp_profile import remember_member
from database.models import Track

router = APIRouter(prefix="/miniapp-api")
logger = logging.getLogger(__name__)
RAP_RANGES = {
    "low_double": [(70, 76), (140, 152)],
    "mid_low": [(95, 103)],
    "mid": [(107, 117)],
    "mid_high": [(123, 130)],
}
GENRES = ("electronic", "house", "rap")


class GenerateRequest(BaseModel):
    genre: Literal["electronic", "house", "rap"]
    duration: Literal[30, 60]
    bpm_bucket: Literal["low_double", "mid_low", "mid", "mid_high"] | None = None
    previous_set_id: str | None = None

    @model_validator(mode="after")
    def rap_requires_bucket(self):
        if self.genre == "rap" and not self.bpm_bucket:
            raise ValueError("Выбери BPM-диапазон для Rap")
        if self.genre != "rap" and self.bpm_bucket:
            raise ValueError("BPM-диапазон доступен только для Rap")
        return self


class FavoriteRequest(BaseModel):
    favorite: bool


def serialize_set(row: MiniAppSet) -> dict:
    return {
        "id": row.id, "genre": row.genre, "duration": row.duration,
        "bpm_bucket": row.bpm_bucket, "tracks": row.tracks,
        "total_duration_sec": row.total_duration_sec,
        "actual_duration_sec": row.actual_duration_sec,
        "favorite": row.favorite, "status": row.status, "sent_count": row.sent_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def owned_set(session, set_id: str, user_id: int) -> MiniAppSet:
    row = await session.get(MiniAppSet, set_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(404, "Сет не найден.")
    return row


@router.get("/bootstrap")
async def bootstrap(user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        result = await session.execute(
            select(Track.genre, func.count()).where(
                Track.genre.in_(GENRES), Track.is_suitable.is_(True),
                Track.bpm.is_not(None), Track.camelot_key.is_not(None), Track.duration_sec > 0,
                ~func.lower(Track.title).like("%acapella%"),
                ~func.lower(Track.title).like("%scratch%"),
                ~func.lower(Track.title).like("%sample%"),
            ).group_by(Track.genre)
        )
        counts = dict(result.all())
        await remember_member(session, user)
        await session.commit()
    return {"local": get_settings().miniapp_local,
            "delivery_enabled": not get_settings().miniapp_local and get_settings().miniapp_delivery_enabled,
            "user": {"id": user.id, "first_name": user.first_name},
            "genres": [{"id": genre, "count": counts.get(genre, 0)} for genre in GENRES]}


@router.get("/sets")
async def history(user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        rows = (await session.scalars(select(MiniAppSet).where(MiniAppSet.user_id == user.id)
                                      .order_by(MiniAppSet.created_at.desc()).limit(100))).all()
        return [serialize_set(row) for row in rows]


@router.get("/tracks")
async def catalogue(
    user: TelegramUser = Depends(current_user),
    q: str = Query(default="", max_length=200),
    genre: str = Query(default="", max_length=100),
    bpm_min: float | None = Query(default=None, ge=0, le=400),
    bpm_max: float | None = Query(default=None, ge=0, le=400),
    key: str = Query(default="", pattern=r"^(?:[1-9]|1[0-2])[AB]$|^$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=100),
):
    if bpm_min is not None and bpm_max is not None and bpm_min > bpm_max:
        raise HTTPException(422, "Минимальный BPM должен быть меньше максимального.")
    conditions = []
    if q.strip():
        # Literal search: SQL wildcard characters in titles have no special meaning.
        conditions.append((Track.title.icontains(q.strip(), autoescape=True)) |
                          (Track.artist.icontains(q.strip(), autoescape=True)))
    if genre:
        conditions.append(Track.genre == genre)
    if bpm_min is not None:
        conditions.append(Track.bpm >= bpm_min)
    if bpm_max is not None:
        conditions.append(Track.bpm <= bpm_max)
    if key:
        conditions.append(Track.camelot_key == key)
    async with SessionLocal() as session:
        genres = (await session.execute(select(Track.genre, func.count()).group_by(Track.genre)
                                        .order_by(Track.genre))).all()
        total = await session.scalar(select(func.count()).select_from(Track).where(*conditions))
        rows = (await session.scalars(select(Track).where(*conditions)
                                     .order_by(Track.created_at.desc(), Track.id.desc())
                                     .offset(offset).limit(limit))).all()
    return {"total": total, "offset": offset,
            "genres": [{"id": name, "count": count} for name, count in genres],
            "tracks": [{"id": t.id, "title": t.title, "artist": t.artist,
                        "genre": t.genre, "bpm": t.bpm, "camelot_key": t.camelot_key,
                        "duration_sec": t.duration_sec} for t in rows]}


@router.post("/sets", status_code=201)
async def generate(body: GenerateRequest, request: Request, user: TelegramUser = Depends(current_user)):
    # Bounded per-process admission control; production runs one API worker.
    limits = request.app.state.generation_limits
    now = time.monotonic()
    for key in list(limits):
        if not limits[key] or now - limits[key][-1] > 60:
            del limits[key]
    timestamps = limits.setdefault(user.id, deque())
    while timestamps and now - timestamps[0] > 60:
        timestamps.popleft()
    if len(timestamps) >= 8:
        raise HTTPException(429, "Дай нам минуту — затем можно собрать новый сет.")
    timestamps.append(now)
    async with SessionLocal() as session:
        excluded = set()
        if body.previous_set_id:
            previous = await owned_set(session, body.previous_set_id, user.id)
            if previous.genre == body.genre and previous.bpm_bucket == body.bpm_bucket:
                excluded = {track["id"] for track in previous.tracks}
        tracks = await get_tracks_for_genre(session, body.genre)
        tracks = [track for track in tracks if track.id not in excluded]
        if body.bpm_bucket:
            ranges = RAP_RANGES[body.bpm_bucket]
            tracks = [track for track in tracks if track.bpm is not None and
                      any(start <= track.bpm <= end for start, end in ranges)]
        result = await asyncio.to_thread(generate_dj_playlist, tracks, body.duration,
                                         strict_key_progression=bool(excluded))
        if not result.tracks:
            raise HTTPException(409, "В этом диапазоне пока не хватает треков. Выбери другой или создай сет заново.")
        row = MiniAppSet(
            id=uuid.uuid4().hex, user_id=user.id, genre=body.genre, duration=body.duration,
            bpm_bucket=body.bpm_bucket, total_duration_sec=result.total_duration_sec,
            actual_duration_sec=result.actual_duration_sec,
            tracks=[{"id": t.id, "title": t.title, "artist": t.artist, "bpm": t.bpm,
                     "camelot_key": t.camelot_key, "duration_sec": t.duration_sec}
                    for t in result.tracks],
        )
        session.add(row)
        await remember_member(session, user)
        await session.commit()
        await session.refresh(row)
        return serialize_set(row)


@router.get("/sets/{set_id}")
async def detail(set_id: str, user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        return serialize_set(await owned_set(session, set_id, user.id))


@router.patch("/sets/{set_id}/favorite")
async def favorite(set_id: str, body: FavoriteRequest, user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        row = await owned_set(session, set_id, user.id)
        row.favorite = body.favorite
        await session.commit()
        return serialize_set(row)


@router.post("/sets/{set_id}/deliver", status_code=202)
async def deliver(set_id: str, request: Request, user: TelegramUser = Depends(current_user)):
    if get_settings().miniapp_local or not get_settings().miniapp_delivery_enabled:
        raise HTTPException(403, "Отправка аудио в этом режиме отключена. Скачай треклист.")
    state = request.app.state
    async with state.delivery_lock:
        if any(item["user_id"] == user.id for item in state.deliveries.values()):
            raise HTTPException(409, "Предыдущий сет ещё отправляется. Дождись завершения.")
        if len(state.deliveries) >= 8:
            raise HTTPException(429, "Все каналы отправки заняты. Попробуй чуть позже.")
        async with SessionLocal() as session:
            row = await owned_set(session, set_id, user.id)
            # Every set can be dispatched once. A timeout may mean Telegram accepted a file.
            if row.status != "ready":
                raise HTTPException(409, "Этот сет уже отправлялся. Проверь статус и сообщения в чате.")
            claimed = await session.execute(update(MiniAppSet).where(
                MiniAppSet.id == set_id, MiniAppSet.status == "ready"
            ).values(status="sending"))
            if claimed.rowcount != 1:
                raise HTTPException(409, "Сет уже отправляется.")
            await session.commit()
        item = {"user_id": user.id, "cancelled": False, "task": None}
        state.deliveries[set_id] = item
        item["task"] = asyncio.create_task(delivery_worker(request.app, set_id, user.id))
    return {"status": "sending"}


@router.post("/sets/{set_id}/cancel")
async def cancel(set_id: str, request: Request, user: TelegramUser = Depends(current_user)):
    async with SessionLocal() as session:
        await owned_set(session, set_id, user.id)
    item = request.app.state.deliveries.get(set_id)
    if item:
        item["cancelled"] = True
    return {"status": "cancelling" if item else "idle"}


async def delivery_worker(app, set_id: str, user_id: int):
    sent = 0
    status = "failed"
    async def progress(count):
        nonlocal sent
        sent = count
        async with SessionLocal() as session:
            await session.execute(update(MiniAppSet).where(MiniAppSet.id == set_id).values(sent_count=count))
            await session.commit()
    try:
        async with app.state.delivery_slots:
            async with SessionLocal() as session:
                row = await session.get(MiniAppSet, set_id)
                ids = [track["id"] for track in row.tracks]
                found = (await session.scalars(select(Track).where(Track.id.in_(ids)))).all()
                by_id = {track.id: track for track in found}
                tracks = [by_id[track_id] for track_id in ids if track_id in by_id]
            delivery = AudioDeliveryService()
            send = delivery.send_stored_tracks if delivery.storage.enabled else delivery.send_tracks
            sent, cancelled = await send(
                app.state.miniapp_bot, user_id, tracks,
                should_cancel=lambda: app.state.deliveries[set_id]["cancelled"], on_progress=progress,
            )
            status = "cancelled" if cancelled else "completed" if sent == len(ids) else "partial" if sent else "failed"
    except asyncio.CancelledError:
        status = "interrupted"
        raise
    except Exception:
        logger.exception("Mini App delivery failed for set %s", set_id)
        status = "partial" if sent else "failed"
    finally:
        try:
            async with SessionLocal() as session:
                await session.execute(update(MiniAppSet).where(MiniAppSet.id == set_id)
                                      .values(status=status, sent_count=sent))
                await session.commit()
        finally:
            app.state.deliveries.pop(set_id, None)
