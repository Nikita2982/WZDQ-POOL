from __future__ import annotations

import sqlite3

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
    cursor.execute(
        f"DELETE FROM tracks WHERE genre IN ({','.join('?' for _ in IGNORED_GENRES)})",
        IGNORED_GENRES,
    )
    deleted_rows = cursor.rowcount
    connection.commit()
    connection.close()
    print(f"DELETED_ROWS {deleted_rows}")


if __name__ == "__main__":
    main()
