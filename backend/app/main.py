"""Collander FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .auth import require_auth
from .config import get_settings
from .migrate import upgrade_db
from .routers import auth as auth_router
from .routers import imports, recipes, settings, tags
from .routers import queue as queue_router
from .services import images, queue
from .services.importer import mark_interrupted_jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

try:  # Optional HEIC/HEIF support for iPhone photos.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    upgrade_db()
    mark_interrupted_jobs()
    imports.cleanup_uploads()
    queue.start_workers()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Collander", version=__version__, lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=s.get_secret_key(),
        session_cookie="collander_session",
        max_age=s.session_days * 86400,
        same_site="lax",
        https_only=s.secure_cookies,
    )
    for r in (
        auth_router.router,
        recipes.router,
        tags.router,
        imports.router,
        queue_router.router,
        settings.router,
    ):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/images/{name}", dependencies=[Depends(require_auth)])
    def get_image(name: str):
        if not images.is_stored_name(name):
            raise HTTPException(404)
        path = s.images_dir / name
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    static_dir = s.static_dir
    if static_dir and Path(static_dir).is_dir():
        static_dir = Path(static_dir)
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (static_dir / path).resolve()
            if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
