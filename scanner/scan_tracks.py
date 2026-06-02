from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.custom.message import Message

from config.settings import get_settings
from database.crud import create_scan_job, finish_scan_job, get_max_track_message_id, upsert_track
from database.db import SessionLocal
from scanner.metadata_reader import (
    build_message_link,
    extract_genre_from_text,
    extract_section_header_genre_from_text,
)

logger = logging.getLogger(__name__)
PROGRESS_LOG_INTERVAL = 50


@dataclass(slots=True)
class ScanSummary:
    processed_messages: int
    created_tracks: int
    updated_tracks: int


@dataclass(slots=True)
class GenreSection:
    genre: str
    header_message_id: int
    start_index: int
    end_index: int


class ChannelScanner:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.analyzer = None

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

        return ScanSummary(processed_messages=processed, created_tracks=created, updated_tracks=updated)

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
        scan_session = sessions_dir / f"{self.settings.telethon_session_name}_scan.session"
        if base_session.exists() and not scan_session.exists():
            shutil.copy2(base_session, scan_session)
        return scan_session

    def _build_sections(self, messages: list[Message]) -> list[GenreSection]:
        headers: list[tuple[int, str, int]] = []
        for index, message in enumerate(messages):
            genre = extract_section_header_genre_from_text(
                message.message or "",
                supported_genres=self.settings.supported_genres,
                hashtag_prefix=self.settings.genre_hashtag_prefix,
            )
            if genre:
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

        temp_path = await client.download_media(
            message,
            file=self.settings.temp_audio_dir / f"{message.id}_{message.file.name or 'track'}",
        )
        if not temp_path:
            return None

        analysis = self._get_analyzer().analyze_file(temp_path)
        file_id = getattr(message.file, "id", None)
        performer = getattr(message.file, "performer", None)
        title = getattr(message.file, "title", None) or analysis.title
        duration = getattr(message.file, "duration", None) or analysis.duration_sec
        topic_id = getattr(message, "reply_to_top_id", None)

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
            "raw_metadata": {
                "caption": text,
                "file_name": getattr(message.file, "name", None),
                "mime_type": getattr(message.file, "mime_type", None),
            },
        }
