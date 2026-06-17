from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.metadata_reader import GENRE_ALIAS_MAP

IGNORED_GENRES = (
    "acapella",
    "samples",
    "scratch",
    "en_intro",
    "tools",
    "beatport_top_10",
    "billboard_top_10",
    "soundcloud_reels",
    "weekly_update_electronic",
)


def main() -> None:
    connection = sqlite3.connect("dj_ai_bot.db")
    cursor = connection.cursor()

    updated_rows = 0
    for source_genre, target_genre in GENRE_ALIAS_MAP.items():
        cursor.execute(
            "UPDATE tracks SET genre = ? WHERE genre = ?",
            (target_genre, source_genre),
        )
        updated_rows += cursor.rowcount

    cursor.execute(
        f"DELETE FROM tracks WHERE genre IN ({','.join('?' for _ in IGNORED_GENRES)})",
        IGNORED_GENRES,
    )
    deleted_rows = cursor.rowcount

    connection.commit()
    connection.close()
    print(f"UPDATED_ROWS {updated_rows}")
    print(f"DELETED_ROWS {deleted_rows}")


if __name__ == "__main__":
    main()
