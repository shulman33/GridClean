"""GridClean FastAPI application entrypoint."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1.router import api_router
from app.config import get_settings
from app.core.logging import configure_logging
from app.middleware import logging_middleware

settings = get_settings()
configure_logging("DEBUG" if settings.debug else "INFO")

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Live carbon intensity of electricity by location.",
)

app.middleware("http")(logging_middleware)
app.include_router(api_router)


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "health": "/v1/health",
        "ui": "/app/",
    }


# Interactive demo UI (served at /app/). Mounted last so it can't shadow /v1.
_frontend = Path(__file__).resolve().parent.parent / "frontend"
if _frontend.is_dir():
    app.mount("/app", StaticFiles(directory=_frontend, html=True), name="frontend")
