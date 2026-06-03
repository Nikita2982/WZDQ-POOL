from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from telethon import TelegramClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from database.crud import list_tracks_missing_storage
from database.db import SessionLocal, close_db, init_db
from database.models import Track
from storage import ObjectStorageService

logger = logging.getLogger(__name__)


def normalized_source_chat(source_chat: str | int) -> str | int:
    if isinstance(source_chat, str):
        value = source_chat.strip()
        if value and value.lstrip("-").isdigit():
            return int(value)
        return value
    return source_chat


def prepare_runtime_session() -> Path:
    settings = get_settings()
    sessions_dir = Path(".sessions")
    sessions_dir.mkdir(parents=True, exist_ok=True)
    base_candidates = [
        sessions_dir / f"{settings.telethon_session_name}.session",
        sessions_dir / f"{settings.telethon_session_name}_scan.session",
    ]
    runtime_session = sessions_dir / f"{settings.telethon_session_name}_backfill_{uuid.uuid4().hex}.session"
    for candidate in base_candidates:
        if candidate.exists():
            shutil.copy2(candidate, runtime_session)
            return runtime_session
    return runtime_session


def cleanup_runtime_session(session_path: Path) -> None:
    session_path.unlink(missing_ok=True)
    Path(f"{session_path}-journal").unlink(missing_ok=True)


def find_cached_track_file(track: Track, temp_audio_dir: Path) -> Path | None:
    for path in temp_audio_dir.glob(f"{track.telegram_message_id}_*"):
        if path.is_file():
            return path
    return None


async def upload_existing_tracks(limit: int | None = None) -> tuple[int, int, int]:
    settings = get_settings()
    storage = ObjectStorageService()
    if not storage.enabled:
        raise RuntimeError("Storage is not enabled. Fill STORAGE_* in .env first.")

    source = normalized_source_chat(settings.source_chat)
    session_path = prepare_runtime_session()
    uploaded = skipped = failed = 0

    try:
        async with TelegramClient(
            session_path.as_posix(),
            settings.telegram_api_id,
            settings.telegram_api_hash,
        ) as client:
            entity = await client.get_entity(source)
            async with SessionLocal() as db_session:
                tracks = await list_tracks_missing_storage(db_session, limit=limit)
                logger.info("Found %s tracks without storage", len(tracks))

                for index, track in enumerate(tracks, start=1):
                    temp_path = find_cached_track_file(track, settings.temp_audio_dir)
                    downloaded_for_backfill = False
                    try:
                        if temp_path is None:
                            message = await client.get_messages(entity, ids=track.telegram_message_id)
                            if not message or not message.file:
                                logger.warning("Skipping track without source message: track_id=%s", track.id)
                                skipped += 1
                                continue
                            temp_file = await client.download_media(
                                message,
                                file=settings.temp_audio_dir / f"backfill_{track.telegram_message_id}_{uuid.uuid4().hex}.mp3",
                            )
                            if temp_file is None:
                                logger.warning("Skipping track download failure: track_id=%s", track.id)
                                skipped += 1
                                continue
                            temp_path = Path(temp_file)
                            downloaded_for_backfill = True

                        raw_metadata = track.raw_metadata or {}
                        content_type = raw_metadata.get("mime_type") if isinstance(raw_metadata, dict) else None
                        original_file_name = raw_metadata.get("file_name") if isinstance(raw_metadata, dict) else None
                        storage_info = storage.upload_track(
                            temp_path,
                            file_hash=track.file_hash,
                            original_file_name=original_file_name,
                            content_type=content_type,
                        )
                        if storage_info is None:
                            raise RuntimeError("Storage upload returned no result.")

                        track.storage_bucket, track.storage_key = storage_info
                        await db_session.commit()
                        uploaded += 1

                        temp_path.unlink(missing_ok=True)
                    except Exception:
                        await db_session.rollback()
                        failed += 1
                        logger.warning(
                            "Backfill failed for track_id=%s message_id=%s",
                            track.id,
                            track.telegram_message_id,
                            exc_info=True,
                        )
                    finally:
                        if downloaded_for_backfill and temp_path is not None:
                            temp_path.unlink(missing_ok=True)

                    if index % 50 == 0:
                        logger.info(
                            "Backfill progress: processed=%s uploaded=%s skipped=%s failed=%s",
                            index,
                            uploaded,
                            skipped,
                            failed,
                        )
    finally:
        cleanup_runtime_session(session_path)

    return uploaded, skipped, failed


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    await init_db()
    try:
        uploaded, skipped, failed = await upload_existing_tracks(limit=limit)
        print(f"UPLOADED {uploaded}")
        print(f"SKIPPED {skipped}")
        print(f"FAILED {failed}")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
