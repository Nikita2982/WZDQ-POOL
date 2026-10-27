"""Copy only the track catalogue, once; never write to the bot's original DB."""
import sqlite3
from pathlib import Path

target = Path("dj_ai_bot_miniapp.db")
source = Path("dj_ai_bot.db")
if not target.exists() and source.exists():
    source_conn = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        schema = source_conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tracks'").fetchone()
        if schema:
            destination.execute(schema[0])
            cursor = source_conn.execute("SELECT * FROM tracks")
            placeholders = ",".join("?" for _ in cursor.description)
            destination.executemany(f"INSERT INTO tracks VALUES ({placeholders})", cursor)
            destination.commit()
            print("Локальная копия каталога готова. Исходная база не изменена.")
    finally:
        destination.close()
        source_conn.close()
