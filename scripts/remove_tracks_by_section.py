from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from telethon import TelegramClient
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from database.db import SessionLocal
from database.models import Track
from scanner.metadata_reader import extract_section_header_tag


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove tracks from the local database by Telegram section header tag.",
    )
    parser.add_argument(
        "section_tag",
        help="Section tag without leading #, for example: billboard_top_10",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete matched tracks. Without this flag the script is a dry run.",
    )
    return parser


async def _collect_section_message_ids(section_tag: str) -> tuple[str, list[int]]:
    settings = get_settings()
    session_path = Path(".sessions") / f"{settings.telethon_session_name}.session"
    source_chat: str | int = settings.source_chat
    if isinstance(source_chat, str):
        value = source_chat.strip()
        if value and value.lstrip("-").isdigit():
            source_chat = int(value)
        else:
            source_chat = value
    async with TelegramClient(
        session_path.as_posix(),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        proxy=settings.telethon_proxy,
    ) as client:
        entity = await client.get_entity(source_chat)
        channel_id = str(getattr(entity, "id", source_chat))
        target_tag = section_tag.lower().lstrip("#")
        current_tag: str | None = None
        matched_ids: list[int] = []

        async for message in client.iter_messages(entity, reverse=True):
            raw_tag = extract_section_header_tag(message.message or "")
            if raw_tag is not None:
                current_tag = raw_tag
                continue
            if current_tag != target_tag:
                continue
            if not message.file or not (message.file.mime_type or "").startswith("audio"):
                continue
            matched_ids.append(message.id)

        return channel_id, matched_ids


async def _delete_tracks(channel_id: str, message_ids: list[int], *, apply: bool) -> None:
    if not message_ids:
        print("MATCHED_SECTION_TRACKS 0")
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(Track)
            .where(
                Track.telegram_channel_id == channel_id,
                Track.telegram_message_id.in_(message_ids),
            )
            .order_by(Track.telegram_message_id.asc())
        )
        rows = list(result.scalars().all())

        print(f"MATCHED_SECTION_TRACKS {len(rows)}")
        for row in rows:
            print(
                (
                    row.id,
                    row.genre,
                    row.artist,
                    row.title,
                    row.telegram_message_id,
                    row.is_suitable,
                )
            )

        if not apply or not rows:
            return

        delete_result = await session.execute(
            delete(Track).where(
                Track.telegram_channel_id == channel_id,
                Track.telegram_message_id.in_(message_ids),
            )
        )
        await session.commit()
        print(f"DELETED_ROWS {delete_result.rowcount or 0}")


async def _main() -> None:
    args = _build_parser().parse_args()
    channel_id, message_ids = await _collect_section_message_ids(args.section_tag)
    await _delete_tracks(channel_id, message_ids, apply=args.apply)


if __name__ == "__main__":
    asyncio.run(_main())
