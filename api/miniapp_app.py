from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update

from api.miniapp import router as miniapp_router
from api.miniapp_youtube import router as youtube_router, cleanup_audio
from api.miniapp_profile import router as profile_router
from api.miniapp_knowledge import router as knowledge_router
from config.settings import get_settings

from database.db import SessionLocal, close_db, init_db
from api.miniapp_models import MiniAppSet, MiniAppYouTubeJob


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    await asyncio.to_thread(cleanup_audio)
    app.state.miniapp_bot = Bot(token=settings.telegram_bot_token,
                               session=AiohttpSession(proxy=settings.outbound_proxy_url or None))
    app.state.deliveries = {}
    app.state.delivery_lock = asyncio.Lock()
    app.state.delivery_slots = asyncio.Semaphore(2)
    app.state.generation_limits = {}
    app.state.youtube_tasks = {}
    app.state.youtube_lock = asyncio.Lock()
    app.state.youtube_limits = {}
    async with SessionLocal() as session:
        await session.execute(update(MiniAppSet).where(MiniAppSet.status == "sending").values(status="interrupted"))
        await session.execute(update(MiniAppYouTubeJob).where(MiniAppYouTubeJob.status == "running").values(
            status="interrupted", progress="Разбор прерван при перезапуске. Запусти его снова."))
        await session.commit()
    try:
        yield
    finally:
        tasks = [item["task"] for item in list(app.state.deliveries.values())]
        tasks += [item["task"] for item in list(app.state.youtube_tasks.values())]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await app.state.miniapp_bot.session.close()
        await close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="WZDQ Pool API", version="0.2.0", lifespan=lifespan)
    app.include_router(miniapp_router)
    app.include_router(youtube_router)
    app.include_router(profile_router)
    app.include_router(knowledge_router)
    web_root = Path(__file__).resolve().parents[1] / "web"
    app.mount("/app/static", StaticFiles(directory=web_root), name="miniapp-static")

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/miniapp-api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/app", include_in_schema=False)
    @app.get("/app/", include_in_schema=False)
    async def miniapp_index():
        return FileResponse(web_root / "index.html", headers={"Cache-Control": "no-store, max-age=0"})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
