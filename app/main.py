"""GridClean FastAPI application entrypoint."""

from fastapi import FastAPI

from app import __version__
from app.api.v1.router import api_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Live carbon intensity of electricity by location.",
)

app.include_router(api_router)


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "health": "/v1/health",
    }
