from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import SessionLocal
from database.models import Track


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove tracks from the local database by genre and title/artist substring.",
    )
    parser.add_argument(
        "--genre",
        required=True,
        help="Genre to filter, for example: electronic",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Case-insensitive substring to match in track title or artist, for example: Jamaican",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete matched tracks. Without this flag the script is a dry run.",
    )
    return parser


async def _run(*, genre: str, query: str, apply: bool) -> None:
    normalized_genre = genre.strip().lower()
    normalized_query = f"%{query.strip().lower()}%"

    async with SessionLocal() as session:
        result = await session.execute(
            select(Track)
            .where(
                func.lower(Track.genre) == normalized_genre,
                (
                    func.lower(Track.title).like(normalized_query)
                    | func.lower(func.coalesce(Track.artist, "")).like(normalized_query)
                ),
            )
            .order_by(Track.telegram_message_id.asc())
        )
        rows = list(result.scalars().all())

        print(f"MATCHED_TRACKS {len(rows)}")
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
            delete(Track).where(Track.id.in_([row.id for row in rows]))
        )
        await session.commit()
        print(f"DELETED_ROWS {delete_result.rowcount or 0}")


async def _main() -> None:
    args = _build_parser().parse_args()
    await _run(genre=args.genre, query=args.query, apply=args.apply)


if __name__ == "__main__":
    asyncio.run(_main())
