from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient
from telethon import events
from telethon.tl.custom.message import Message

from config.settings import get_settings
from database.crud import create_scan_job, finish_scan_job, get_max_track_message_id, upsert_track
from database.db import SessionLocal
from scanner.metadata_reader import (
    build_message_link,
    extract_genre_from_text,
    extract_section_header_tag,
    extract_section_header_genre_from_text,
)
from storage import ObjectStorageService

logger = logging.getLogger(__name__)
PROGRESS_LOG_INTERVAL = 50


@dataclass(slots=True)
class ScanSummary:
    processed_messages: int
    created_tracks: int
    updated_tracks: int


@dataclass(slots=True)
class GenreSection:
    genre: str | None
    header_message_id: int
    start_index: int
    end_index: int


class ChannelScanner:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.analyzer = None
        self.storage = ObjectStorageService()

    def _get_analyzer(self):
        if self.analyzer is None:
            from analysis.audio_analyzer import AudioAnalyzer

            self.analyzer = AudioAnalyzer()
        return self.analyzer

    async def scan(
        self,
        source_chat: str | int | None = None,
        limit: int | None = None,
        *,
        resume: bool = True,
    ) -> ScanSummary:
        source = self._normalize_source_chat(source_chat or self.settings.source_chat)
        scan_limit = limit or self.settings.default_scan_limit
        session_name = self._get_scan_session_path()

        async with SessionLocal() as db_session:
            job = await create_scan_job(db_session, str(source))
            processed = created = updated = 0
            error_message: str | None = None
            try:
                async with TelegramClient(
                    session_name.as_posix(),
                    self.settings.telegram_api_id,
                    self.settings.telegram_api_hash,
                    proxy=self.settings.telethon_proxy,
                ) as client:
                    entity = await client.get_entity(source)
                    chat_username = getattr(entity, "username", None)
                    channel_id = str(getattr(entity, "id", self.settings.source_chat))
                    resume_from_message_id = None
                    if resume:
                        resume_from_message_id = await get_max_track_message_id(db_session, channel_id)
                        if resume_from_message_id:
                            logger.info(
                                "Resume enabled: continuing after telegram_message_id=%s",
                                resume_from_message_id,
                            )
                    messages = await self._load_messages(
                        client,
                        entity,
                        limit=scan_limit,
                        resume_from_message_id=resume_from_message_id,
                    )
                    sections = self._build_sections(messages)

                    for section in sections:
                        if not section.genre:
                            continue
                        section_messages = messages[section.start_index + 1 : section.end_index]
                        for message in section_messages:
                            if not self._is_audio_message(message):
                                continue
                            processed += 1
                            try:
                                payload = await self._build_track_payload(
                                    client,
                                    entity,
                                    message,
                                    chat_username,
                                    fallback_genre=section.genre,
                                )
                                if payload is None:
                                    continue
                                _, was_created = await upsert_track(db_session, payload)
                                if was_created:
                                    created += 1
                                else:
                                    updated += 1
                            except Exception:
                                await db_session.rollback()
                                logger.warning(
                                    "Skipping problematic track: message_id=%s genre=%s header_message_id=%s",
                                    message.id,
                                    section.genre,
                                    section.header_message_id,
                                    exc_info=True,
                                )
                                continue
                            if processed % PROGRESS_LOG_INTERVAL == 0:
                                logger.info(
                                    "Scan progress: processed=%s created=%s updated=%s current_genre=%s header_message_id=%s",
                                    processed,
                                    created,
                                    updated,
                                    section.genre,
                                    section.header_message_id,
                                )
            except Exception as exc:
                logger.exception("Channel scan failed")
                error_message = str(exc)
                raise
            finally:
                await finish_scan_job(
                    db_session,
                    job,
                    processed_messages=processed,
                    created_tracks=created,
                    updated_tracks=updated,
                    error_message=error_message,
                )
                self._cleanup_runtime_session(session_name)

        return ScanSummary(processed_messages=processed, created_tracks=created, updated_tracks=updated)

    async def process_message(
        self,
        client: TelegramClient,
        entity,
        message: Message,
        *,
        chat_username: str | None,
        fallback_genre: str | None,
    ) -> bool:
        if not self._is_audio_message(message):
            return False

        payload = await self._build_track_payload(
            client,
            entity,
            message,
            chat_username,
            fallback_genre=fallback_genre,
        )
        if payload is None:
            return False

        async with SessionLocal() as db_session:
            await upsert_track(db_session, payload)
        return True

    async def _load_messages(
        self,
        client: TelegramClient,
        entity,
        *,
        limit: int,
        resume_from_message_id: int | None,
    ) -> list[Message]:
        if not resume_from_message_id:
            return [
                message
                async for message in client.iter_messages(entity, limit=limit, reverse=True)
            ]

        messages = [
            message
            async for message in client.iter_messages(
                entity,
                limit=limit,
                reverse=True,
                min_id=resume_from_message_id,
            )
        ]
        previous_header = await self._find_previous_section_header(
            client,
            entity,
            before_message_id=resume_from_message_id,
        )
        if previous_header:
            messages.insert(0, previous_header)
        return messages

    @staticmethod
    def _normalize_source_chat(source_chat: str | int) -> str | int:
        if isinstance(source_chat, str):
            value = source_chat.strip()
            if value and value.lstrip("-").isdigit():
                return int(value)
            return value
        return source_chat

    def _is_audio_message(self, message: Message) -> bool:
        return bool(message.file and (message.file.mime_type or "").startswith("audio"))

    def _get_scan_session_path(self) -> Path:
        sessions_dir = Path(".sessions")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        base_session = sessions_dir / f"{self.settings.telethon_session_name}.session"
        scan_session = sessions_dir / f"{self.settings.telethon_session_name}_scan_{uuid.uuid4().hex}.session"
        if base_session.exists():
            shutil.copy2(base_session, scan_session)
        return scan_session

    @staticmethod
    def _cleanup_runtime_session(session_path: Path) -> None:
        session_path.unlink(missing_ok=True)
        Path(f"{session_path}-journal").unlink(missing_ok=True)

    def _build_sections(self, messages: list[Message]) -> list[GenreSection]:
        headers: list[tuple[int, str | None, int]] = []
        for index, message in enumerate(messages):
            text = message.message or ""
            raw_tag = extract_section_header_tag(text)
            if raw_tag is None:
                continue
            genre = extract_section_header_genre_from_text(
                text,
                supported_genres=self.settings.supported_genres,
                hashtag_prefix=self.settings.genre_hashtag_prefix,
            )
            headers.append((index, genre, message.id))

        sections: list[GenreSection] = []
        for idx, (start_index, genre, header_message_id) in enumerate(headers):
            end_index = headers[idx + 1][0] if idx + 1 < len(headers) else len(messages)
            sections.append(
                GenreSection(
                    genre=genre,
                    header_message_id=header_message_id,
                    start_index=start_index,
                    end_index=end_index,
                )
            )
        return sections

    async def _find_previous_section_header(
        self,
        client: TelegramClient,
        entity,
        *,
        before_message_id: int,
    ) -> Message | None:
        async for message in client.iter_messages(entity, offset_id=before_message_id):
            genre = extract_section_header_genre_from_text(
                message.message or "",
                supported_genres=self.settings.supported_genres,
                hashtag_prefix=self.settings.genre_hashtag_prefix,
            )
            if genre:
                return message
        return None

    async def get_active_section(
        self,
        client: TelegramClient,
        entity,
        *,
        before_message_id: int | None = None,
    ) -> GenreSection | None:
        async for message in client.iter_messages(entity, offset_id=before_message_id or 0):
            genre = extract_section_header_genre_from_text(
                message.message or "",
                supported_genres=self.settings.supported_genres,
                hashtag_prefix=self.settings.genre_hashtag_prefix,
            )
            if genre:
                return GenreSection(
                    genre=genre,
                    header_message_id=message.id,
                    start_index=0,
                    end_index=0,
                )
            raw_tag = extract_section_header_tag(message.message or "")
            if raw_tag:
                return None
        return None

    async def _build_track_payload(
        self,
        client: TelegramClient,
        entity,
        message: Message,
        chat_username: str | None,
        fallback_genre: str | None,
    ) -> dict | None:
        text = message.message or ""
        genre = extract_genre_from_text(
            text,
            supported_genres=self.settings.supported_genres,
            hashtag_prefix=self.settings.genre_hashtag_prefix,
        )
        genre = genre or fallback_genre
        if not genre:
            return None

        original_name = getattr(message.file, "name", None) or "track.mp3"
        safe_name = "".join("_" if char in '<>:"/\\|?*' else char for char in original_name).strip() or "track.mp3"
        temp_path = await client.download_media(
            message,
            file=self.settings.temp_audio_dir / f"{message.id}_{safe_name}",
        )
        if not temp_path:
            return None

        analysis = self._get_analyzer().analyze_file(temp_path)
        file_id = getattr(message.file, "id", None)
        performer = getattr(message.file, "performer", None)
        title = getattr(message.file, "title", None) or analysis.title
        duration = getattr(message.file, "duration", None) or analysis.duration_sec
        topic_id = getattr(message, "reply_to_top_id", None)
        storage_info = None
        try:
            storage_info = self.storage.upload_track(
                temp_path,
                file_hash=analysis.file_hash,
                original_file_name=getattr(message.file, "name", None),
                content_type=getattr(message.file, "mime_type", None),
            )
        finally:
            if self.storage.enabled:
                Path(temp_path).unlink(missing_ok=True)

        return {
            "telegram_message_id": message.id,
            "telegram_file_id": str(file_id) if file_id else None,
            "telegram_channel_id": str(getattr(entity, "id", self.settings.source_chat)),
            "genre": genre,
            "artist": performer or analysis.artist,
            "title": title,
            "duration_sec": duration,
            "bpm": analysis.bpm,
            "musical_key": analysis.musical_key,
            "camelot_key": analysis.camelot_key,
            "energy_level": analysis.energy_level,
            "file_hash": analysis.file_hash,
            "analyzed_at": analysis.analyzed_at,
            "message_link": build_message_link(chat_username, message.id),
            "source_topic_id": topic_id,
            "is_suitable": True,
            "suitability_score": analysis.energy_level,
            "analysis_notes": analysis.analysis_notes,
            "storage_bucket": storage_info[0] if storage_info else None,
            "storage_key": storage_info[1] if storage_info else None,
            "raw_metadata": {
                "caption": text,
                "file_name": getattr(message.file, "name", None),
                "mime_type": getattr(message.file, "mime_type", None),
            },
        }


class ChannelLiveMonitor:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.scanner = ChannelScanner()
        self.current_section_genre: str | None = None
        self.current_header_message_id: int | None = None

    async def run(self) -> None:
        source = self.scanner._normalize_source_chat(self.settings.source_chat)

        await self.scanner.scan(source_chat=source, resume=True)

        session_path = self._get_live_session_path()
        try:
            async with TelegramClient(
                session_path.as_posix(),
                self.settings.telegram_api_id,
                self.settings.telegram_api_hash,
                proxy=self.settings.telethon_proxy,
            ) as client:
                entity = await client.get_entity(source)
                chat_username = getattr(entity, "username", None)

                active_section = await self.scanner.get_active_section(client, entity)
                if active_section:
                    self.current_section_genre = active_section.genre
                    self.current_header_message_id = active_section.header_message_id
                    logger.info(
                        "Live monitor active section: genre=%s header_message_id=%s",
                        self.current_section_genre,
                        self.current_header_message_id,
                    )
                else:
                    self.current_section_genre = None
                    self.current_header_message_id = None
                    logger.info("Live monitor started without active supported section")

                @client.on(events.NewMessage(chats=entity))
                async def handle_new_message(event) -> None:
                    message = event.message
                    text = message.message or ""

                    header_tag = extract_section_header_tag(text)
                    if header_tag is not None:
                        genre = extract_section_header_genre_from_text(
                            text,
                            supported_genres=self.settings.supported_genres,
                            hashtag_prefix=self.settings.genre_hashtag_prefix,
                        )
                        self.current_section_genre = genre
                        self.current_header_message_id = message.id if genre else None
                        logger.info(
                            "Live section switched: raw_tag=%s canonical_genre=%s header_message_id=%s",
                            header_tag,
                            genre,
                            message.id,
                        )
                        return

                    if not self.scanner._is_audio_message(message):
                        return

                    try:
                        stored = await self.scanner.process_message(
                            client,
                            entity,
                            message,
                            chat_username=chat_username,
                            fallback_genre=self.current_section_genre,
                        )
                        if stored:
                            logger.info(
                                "Live track stored: message_id=%s genre=%s header_message_id=%s",
                                message.id,
                                self.current_section_genre,
                                self.current_header_message_id,
                            )
                        else:
                            logger.info(
                                "Live track skipped: message_id=%s no matching supported genre",
                                message.id,
                            )
                    except Exception:
                        logger.warning(
                            "Live track processing failed: message_id=%s genre=%s",
                            message.id,
                            self.current_section_genre,
                            exc_info=True,
                        )

                logger.info("Live channel monitor started for source_chat=%s", source)
                await client.run_until_disconnected()
        finally:
            self.scanner._cleanup_runtime_session(session_path)

    def _get_live_session_path(self) -> Path:
        sessions_dir = Path(".sessions")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        base_session = sessions_dir / f"{self.settings.telethon_session_name}.session"
        live_session = sessions_dir / f"{self.settings.telethon_session_name}_live_{uuid.uuid4().hex}.session"
        if base_session.exists():
            shutil.copy2(base_session, live_session)
        return live_session
