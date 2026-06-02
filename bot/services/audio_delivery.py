from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile
from telethon import TelegramClient

from config.settings import get_settings


SECTION_ORDER = ["electronic", "house", "rap", "dance_pop"]
logger = logging.getLogger(__name__)


class AudioDeliveryService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def send_tracks(self, bot: Bot, chat_id: int, tracks: list, *, should_cancel=None) -> tuple[int, bool]:
        sent_count = 0
        cancelled = False
        session_path = self._prepare_runtime_delivery_session()
        try:
            async with TelegramClient(
                session_path.as_posix(),
                self.settings.telegram_api_id,
                self.settings.telegram_api_hash,
            ) as client:
                entity = await client.get_entity(self._normalized_source_chat())
                for track in tracks:
                    if should_cancel and should_cancel():
                        cancelled = True
                        break
                    message = await client.get_messages(entity, ids=track.telegram_message_id)
                    if not message or not message.file:
                        logger.warning(
                            "Source message for delivery is unavailable: message_id=%s",
                            track.telegram_message_id,
                        )
                        continue
                    cached_result = self._get_cached_track_file(track)
                    from_cache = cached_result is not None
                    download_result = cached_result or await self._download_track_file(
                        client,
                        message,
                        track,
                    )
                    if download_result is None:
                        logger.warning(
                            "Track file could not be downloaded for delivery: message_id=%s",
                            track.telegram_message_id,
                        )
                        continue
                    temp_path, original_filename = download_result
                    try:
                        if should_cancel and should_cancel():
                            cancelled = True
                            break
                        audio_bytes = Path(temp_path).read_bytes()
                        thumbnail = await self._build_thumbnail_input(client, message, track.telegram_message_id)
                        await bot.send_audio(
                            chat_id=chat_id,
                            audio=BufferedInputFile(audio_bytes, filename=original_filename),
                            thumbnail=thumbnail,
                            duration=getattr(track, "duration_sec", None),
                            performer=(getattr(track, "artist", None) or None),
                            title=(getattr(track, "title", None) or None),
                        )
                        sent_count += 1
                    except Exception:
                        logger.warning(
                            "Bot audio upload failed: message_id=%s",
                            track.telegram_message_id,
                            exc_info=True,
                        )
                        continue
                    finally:
                        if not from_cache:
                            Path(temp_path).unlink(missing_ok=True)
        finally:
            self._cleanup_runtime_delivery_session(session_path)
        return sent_count, cancelled

    def _normalized_source_chat(self) -> str | int:
        source = self.settings.source_chat
        if isinstance(source, str):
            value = source.strip()
            if value and value.lstrip("-").isdigit():
                return int(value)
            return value
        return source

    def _prepare_runtime_delivery_session(self) -> Path:
        sessions_dir = Path(".sessions")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        base_candidates = [
            sessions_dir / f"{self.settings.telethon_session_name}.session",
            sessions_dir / f"{self.settings.telethon_session_name}_scan.session",
        ]
        runtime_session = sessions_dir / f"{self.settings.telethon_session_name}_delivery_{uuid.uuid4().hex}.session"
        for candidate in base_candidates:
            if candidate.exists():
                shutil.copy2(candidate, runtime_session)
                return runtime_session
        return runtime_session

    @staticmethod
    def _cleanup_runtime_delivery_session(session_path: Path) -> None:
        session_path.unlink(missing_ok=True)
        Path(f"{session_path}-journal").unlink(missing_ok=True)

    async def _download_track_file(
        self,
        client: TelegramClient,
        message,
        track,
    ) -> tuple[str, str] | None:
        message_id = track.telegram_message_id
        original_filename = self._original_filename(track, message_id, message.file.name)
        temp_path = await client.download_media(
            message,
            file=self.settings.temp_audio_dir / f"bot_{message_id}_{uuid.uuid4().hex}.mp3",
        )
        if temp_path is None:
            return None
        return temp_path, original_filename

    def _get_cached_track_file(self, track) -> tuple[str, str] | None:
        message_id = track.telegram_message_id
        for path in self.settings.temp_audio_dir.glob(f"{message_id}_*"):
            if path.is_file():
                original_filename = self._original_filename(track, message_id, path.name)
                return path.as_posix(), original_filename
        return None

    async def _build_thumbnail_input(self, client: TelegramClient, message, message_id: int) -> BufferedInputFile | None:
        try:
            thumb_bytes = await client.download_media(message, file=bytes, thumb=-1)
        except Exception:
            logger.warning("Thumbnail download failed: message_id=%s", message_id, exc_info=True)
            return None
        if not thumb_bytes:
            return None
        return BufferedInputFile(thumb_bytes, filename=f"thumb_{message_id}.jpg")

    @staticmethod
    def _original_filename(track, message_id: int, fallback_name: str | None) -> str:
        raw_metadata = getattr(track, "raw_metadata", None) or {}
        raw_file_name = (raw_metadata.get("file_name") or "").strip() if isinstance(raw_metadata, dict) else ""
        if raw_file_name:
            base_name = Path(raw_file_name).stem
        else:
            artist = (getattr(track, "artist", None) or "").strip()
            title = (getattr(track, "title", None) or "").strip()
            if title and "_" in title:
                prefix, _, rest = title.partition("_")
                if prefix.isdigit() and rest.strip():
                    title = rest.strip()
            if artist and title:
                base_name = f"{artist} - {title}"
            elif title:
                base_name = title
            elif fallback_name:
                base_name = Path(fallback_name).stem
            else:
                base_name = f"track_{message_id}"
        safe_name = "".join("_" if char in '<>:"/\\\\|?*' else char for char in base_name).strip()
        return f"{safe_name}.mp3"
