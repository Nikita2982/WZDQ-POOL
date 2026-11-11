from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import time
from collections.abc import Iterator

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from api.miniapp_auth import TelegramUser, current_user
from config.settings import get_settings
from database.db import SessionLocal
from database.models import Track
from storage.object_storage import ObjectStorageService

router = APIRouter(prefix="/miniapp-api")
PREVIEW_URL_TTL = 15 * 60
STREAM_CHUNK_SIZE = 64 * 1024


def preview_signature(track_id: int, user_id: int, expires: int) -> str:
    message = f"miniapp-audio:{track_id}:{user_id}:{expires}".encode()
    return hmac.new(get_settings().telegram_bot_token.encode(), message, hashlib.sha256).hexdigest()


@router.get("/tracks/{track_id}/audio-url")
async def create_audio_url(track_id: int, user: TelegramUser = Depends(current_user)):
    storage = ObjectStorageService()
    if not storage.enabled:
        raise HTTPException(503, "Прослушивание аудио сейчас недоступно.")
    async with SessionLocal() as session:
        track = await session.get(Track, track_id)
        if track is None or not track.storage_key:
            raise HTTPException(404, "Аудиофайл этого трека не найден.")
    expires = int(time.time()) + PREVIEW_URL_TTL
    signature = preview_signature(track_id, user.id, expires)
    return {
        "url": f"/miniapp-api/audio/{track_id}?user_id={user.id}&expires={expires}&signature={signature}",
        "expires": expires,
    }


def _parse_range(value: str | None, size: int) -> tuple[int, int, bool]:
    if size <= 0:
        raise ValueError
    if not value:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError
    first, last = match.groups()
    if not first:
        suffix_length = int(last)
        if suffix_length <= 0:
            raise ValueError
        start, end = max(0, size - suffix_length), size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError
    return start, end, True


@router.api_route("/audio/{track_id}", methods=["GET", "HEAD"])
async def stream_track_preview(
    track_id: int,
    user_id: int,
    expires: int,
    signature: str,
    request: Request,
    range_header: str | None = Header(default=None, alias="Range"),
):
    if (
        user_id < 0
        or not re.fullmatch(r"[0-9a-f]{64}", signature)
        or not int(time.time()) < expires <= int(time.time()) + PREVIEW_URL_TTL + 30
        or not hmac.compare_digest(signature, preview_signature(track_id, user_id, expires))
    ):
        raise HTTPException(403, "Ссылка на прослушивание истекла. Нажми Play ещё раз.")

    storage = ObjectStorageService()
    if not storage.enabled:
        raise HTTPException(503, "Хранилище аудио сейчас недоступно.")
    async with SessionLocal() as session:
        track = await session.get(Track, track_id)
        if track is None or not track.storage_key:
            raise HTTPException(404, "Аудиофайл этого трека не найден.")
        key = track.storage_key
        bucket = track.storage_bucket or storage.settings.storage_bucket

    try:
        metadata = await asyncio.to_thread(storage.client.head_object, Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            raise HTTPException(404, "Аудиофайл этого трека не найден.") from exc
        raise HTTPException(502, "Не удалось открыть аудиофайл.") from exc

    size = int(metadata.get("ContentLength", 0))
    try:
        start, end, partial = _parse_range(range_header, size)
    except ValueError as exc:
        raise HTTPException(416, "Запрошенный фрагмент аудио недоступен.",
                            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"}) from exc

    content_length = end - start + 1
    content_type = str(metadata.get("ContentType", "audio/mpeg"))
    if not content_type.startswith("audio/"):
        content_type = "audio/mpeg"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": content_type,
        "Cache-Control": "private, no-store",
        "Content-Disposition": f"inline; filename=track-{track_id}.mp3",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    status_code = 206 if partial else 200
    if range_header and partial:
        range_value = f"bytes={start}-{end}"
    else:
        range_value = None
    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers)
    try:
        body_response = await asyncio.to_thread(
            storage.client.get_object,
            **({"Bucket": bucket, "Key": key, "Range": range_value}
               if range_value else {"Bucket": bucket, "Key": key}),
        )
    except ClientError as exc:
        raise HTTPException(502, "Не удалось открыть аудиофайл.") from exc
    body = body_response["Body"]

    def chunks() -> Iterator[bytes]:
        try:
            yield from body.iter_chunks(chunk_size=STREAM_CHUNK_SIZE)
        finally:
            body.close()

    return StreamingResponse(chunks(), status_code=status_code, headers=headers)
