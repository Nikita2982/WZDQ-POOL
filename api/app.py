from __future__ import annotations

from fastapi import FastAPI, HTTPException

from database.crud import list_tracks
from database.db import SessionLocal
from scanner.scan_tracks import ChannelScanner


def create_app() -> FastAPI:
    app = FastAPI(title="DJ AI Bot API", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/tracks")
    async def tracks(limit: int = 100) -> list[dict]:
        async with SessionLocal() as session:
            rows = await list_tracks(session, limit=limit)
        return [
            {
                "id": row.id,
                "genre": row.genre,
                "artist": row.artist,
                "title": row.title,
                "bpm": row.bpm,
                "camelot_key": row.camelot_key,
                "energy_level": row.energy_level,
                "message_link": row.message_link,
            }
            for row in rows
        ]

    @app.post("/admin/scan")
    async def scan(limit: int | None = None) -> dict:
        try:
            summary = await ChannelScanner().scan(limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {
            "processed_messages": summary.processed_messages,
            "created_tracks": summary.created_tracks,
            "updated_tracks": summary.updated_tracks,
        }

    return app
