"""Public UI demo only. Deliberately does not import settings, DB or bot code."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


def create_app() -> FastAPI:
    app = FastAPI(title="WZDQ UI Preview", docs_url=None, redoc_url=None, openapi_url=None)
    root = Path(__file__).resolve().parent / "web"
    app.mount("/app/static", StaticFiles(directory=root), name="preview-static")

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    async def index():
        return RedirectResponse("/app/")

    @app.get("/app")
    @app.get("/app/")
    async def preview():
        return FileResponse(root / "index.html")

    @app.get("/miniapp-api/bootstrap")
    async def demo_only():
        # The existing UI enters its explicitly labelled demo mode on this response.
        return JSONResponse({"detail": "Это демонстрация интерфейса без доступа к библиотеке."}, status_code=401)

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": "public-ui-demo"}

    return app
