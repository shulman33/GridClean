"""Aggregates all v1 routers under a single prefix."""

from fastapi import APIRouter

from app.api.v1 import carbon, health, regions

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(regions.router)
api_router.include_router(carbon.router)
