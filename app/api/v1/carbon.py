"""Carbon-intensity endpoints: now, history, compare, savings."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.cache import cached_json
from app.core.ratelimit import enforce_rate_limit
from app.db.session import get_session
from app.schemas import (
    CarbonNowOut,
    CleanestHourOut,
    CompareOut,
    ForecastOut,
    HistoryOut,
    SavingsOut,
)
from app.services.forecast import cleanest_hour, forecast_region
from app.services.queries import (
    build_compare,
    build_now,
    compute_savings,
    get_history,
    resolve_region,
)

router = APIRouter(prefix="/carbon", tags=["carbon"])
settings = get_settings()


@router.get("/now", response_model=CarbonNowOut)
async def carbon_now(
    request: Request,
    response: Response,
    zip: str | None = Query(default=None, min_length=5, max_length=5, pattern=r"^\d{5}$"),
    region: str | None = Query(default=None, min_length=2, max_length=8),
    session: AsyncSession = Depends(get_session),
    _=Depends(enforce_rate_limit),
):
    """Most recent carbon intensity for a ZIP's grid region (or a region code)."""
    region_row, zip_confidence = await resolve_region(session, zip, region)

    async def build() -> dict:
        model = await build_now(session, region_row, zip, zip_confidence)
        return model.model_dump(mode="json")

    return await cached_json(
        request=request,
        response=response,
        cache_key=f"now:{region_row.code}:{zip or '-'}",
        ttl=settings.cache_ttl_seconds,
        build=build,
    )


@router.get("/history", response_model=HistoryOut)
async def carbon_history(
    region: str = Query(min_length=2, max_length=8),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _=Depends(enforce_rate_limit),
):
    """Hourly carbon-intensity time series, newest first, cursor-paginated."""
    return await get_history(session, region.upper(), start, end, limit, cursor)


@router.get("/compare", response_model=CompareOut)
async def carbon_compare(
    request: Request,
    response: Response,
    regions: str = Query(description="Comma-separated region codes, e.g. CISO,ERCO,PJM"),
    session: AsyncSession = Depends(get_session),
    _=Depends(enforce_rate_limit),
):
    """Current intensity for several regions, ranked cleanest -> dirtiest."""
    codes = [c.strip().upper() for c in regions.split(",") if c.strip()][:10]

    async def build() -> dict:
        model = await build_compare(session, codes)
        return model.model_dump(mode="json")

    return await cached_json(
        request=request,
        response=response,
        cache_key="compare:" + ",".join(codes),
        ttl=settings.cache_ttl_seconds,
        build=build,
    )


@router.get("/forecast", response_model=ForecastOut)
async def carbon_forecast(
    request: Request,
    response: Response,
    region: str = Query(min_length=2, max_length=8),
    horizon: int = Query(default=24, ge=1, le=72),
    interval: int = Query(default=80, ge=50, le=99, description="Prediction interval %"),
    session: AsyncSession = Depends(get_session),
    _=Depends(enforce_rate_limit),
):
    """Forecast carbon intensity for the next `horizon` hours, with intervals."""
    region_code = region.upper()

    async def build() -> dict:
        model = await forecast_region(session, region_code, horizon, interval)
        return model.model_dump(mode="json")

    # Forecasts are expensive to fit; cache longer than the live endpoints.
    return await cached_json(
        request=request,
        response=response,
        cache_key=f"forecast:{region_code}:{horizon}:{interval}",
        ttl=max(settings.cache_ttl_seconds, 900),
        build=build,
    )


@router.get("/cleanest-hour", response_model=CleanestHourOut)
async def carbon_cleanest_hour(
    request: Request,
    response: Response,
    zip: str | None = Query(default=None, min_length=5, max_length=5, pattern=r"^\d{5}$"),
    region: str | None = Query(default=None, min_length=2, max_length=8),
    horizon: int = Query(default=24, ge=1, le=72),
    session: AsyncSession = Depends(get_session),
    _=Depends(enforce_rate_limit),
):
    """The lowest-carbon upcoming hour(s) to run a load, from the forecast."""
    region_row, _zip_confidence = await resolve_region(session, zip, region)

    async def build() -> dict:
        model = await cleanest_hour(session, region_row, horizon)
        return model.model_dump(mode="json")

    return await cached_json(
        request=request,
        response=response,
        cache_key=f"cleanest:{region_row.code}:{horizon}",
        ttl=max(settings.cache_ttl_seconds, 900),
        build=build,
    )


@router.get("/savings", response_model=SavingsOut)
async def carbon_savings(
    kwh: float = Query(gt=0, le=1_000_000),
    from_hour: int = Query(ge=0, le=23, description="Local hour-of-day to shift FROM"),
    to_hour: int = Query(ge=0, le=23, description="Local hour-of-day to shift TO"),
    zip: str | None = Query(default=None, min_length=5, max_length=5, pattern=r"^\d{5}$"),
    region: str | None = Query(default=None, min_length=2, max_length=8),
    session: AsyncSession = Depends(get_session),
    _=Depends(enforce_rate_limit),
):
    """CO2 saved by shifting a `kwh` load from one local hour to another."""
    region_row, _zip_confidence = await resolve_region(session, zip, region)
    return await compute_savings(session, region_row, kwh, from_hour, to_hour)
