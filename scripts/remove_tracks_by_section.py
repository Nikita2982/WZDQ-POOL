from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

from telethon import TelegramClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
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
    async with TelegramClient(
        settings.telethon_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
        proxy=settings.telethon_proxy,
    ) as client:
        entity = await client.get_entity(settings.source_chat)
        channel_id = str(getattr(entity, "id", settings.source_chat))
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


def _delete_tracks(channel_id: str, message_ids: list[int], *, apply: bool) -> None:
    settings = get_settings()
    database_url = settings.database_url
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("This script currently supports sqlite DATABASE_URL only")

    db_path = database_url.removeprefix("sqlite:///")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    if not message_ids:
        print("MATCHED_SECTION_TRACKS 0")
        connection.close()
        return

    placeholders = ",".join("?" for _ in message_ids)
    rows = cursor.execute(
        f"""
        SELECT id, genre, artist, title, telegram_message_id, is_suitable
        FROM tracks
        WHERE telegram_channel_id = ?
          AND telegram_message_id IN ({placeholders})
        ORDER BY telegram_message_id ASC
        """,
        [channel_id, *message_ids],
    ).fetchall()

    print(f"MATCHED_SECTION_TRACKS {len(rows)}")
    for row in rows:
        print(row)

    if not apply or not rows:
        connection.close()
        return

    cursor.execute(
        f"""
        DELETE FROM tracks
        WHERE telegram_channel_id = ?
          AND telegram_message_id IN ({placeholders})
        """,
        [channel_id, *message_ids],
    )
    deleted_rows = cursor.rowcount
    connection.commit()
    connection.close()
    print(f"DELETED_ROWS {deleted_rows}")


async def _main() -> None:
    args = _build_parser().parse_args()
    channel_id, message_ids = await _collect_section_message_ids(args.section_tag)
    _delete_tracks(channel_id, message_ids, apply=args.apply)


if __name__ == "__main__":
    asyncio.run(_main())
