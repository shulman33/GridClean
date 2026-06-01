"""Insight narration — compute-then-narrate.

All statistics are computed deterministically in Python; the LLM only writes
prose over those numbers and is instructed to cite nothing else. This is the
discipline that keeps the feature from hallucinating figures.
"""

from collections.abc import Awaitable, Callable

import anthropic
import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import CarbonIntensityHourly, Region

Narrator = Callable[[dict], Awaitable[str]]


async def compute_stats(session: AsyncSession, region_code: str, hours: int) -> dict:
    rows = (
        await session.execute(
            select(CarbonIntensityHourly.period, CarbonIntensityHourly.gco2_per_kwh,
                   CarbonIntensityHourly.renewable_share)
            .where(CarbonIntensityHourly.region_code == region_code)
            .order_by(CarbonIntensityHourly.period.desc())
            .limit(hours)
        )
    ).all()
    if len(rows) < 6:
        raise HTTPException(
            status_code=503, detail=f"Not enough data for '{region_code}' to summarize."
        )

    rows = list(reversed(rows))  # oldest -> newest
    gco2 = np.array([float(r[1]) for r in rows])
    renew = np.array([float(r[2]) for r in rows])
    half = len(gco2) // 2
    first_mean = float(gco2[:half].mean())
    second_mean = float(gco2[half:].mean())
    min_i, max_i = int(gco2.argmin()), int(gco2.argmax())
    corr = float(np.corrcoef(renew, gco2)[0, 1]) if renew.std() > 0 else 0.0

    return {
        "region_code": region_code,
        "window_hours": len(gco2),
        "mean_gco2_per_kwh": round(float(gco2.mean()), 1),
        "min_gco2_per_kwh": round(float(gco2.min()), 1),
        "min_period": rows[min_i][0].isoformat(),
        "max_gco2_per_kwh": round(float(gco2.max()), 1),
        "max_period": rows[max_i][0].isoformat(),
        "first_half_mean": round(first_mean, 1),
        "second_half_mean": round(second_mean, 1),
        "trend_delta": round(second_mean - first_mean, 1),
        "mean_renewable_share": round(float(renew.mean()), 3),
        "renewable_intensity_correlation": round(corr, 2),
    }


async def default_narrator(stats: dict) -> str:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=settings.ai_model,
        max_tokens=400,
        system=[{
            "type": "text",
            "cache_control": {"type": "ephemeral"},
            "text": (
                "You are a grid-carbon analyst. Write 2-3 sentences summarizing the "
                "provided statistics for a region's recent carbon intensity. Use ONLY "
                "the numbers given — never invent or estimate figures. Mention the "
                "trend, the cleanest/dirtiest hours, and what the renewable correlation "
                "implies. Be concrete and concise."
            ),
        }],
        messages=[{"role": "user", "content": f"Statistics (JSON):\n{stats}"}],
    )
    return next((b.text for b in message.content if b.type == "text"), "")


async def build_insights(
    session: AsyncSession, region_row: Region, hours: int, narrator: Narrator
) -> dict:
    stats = await compute_stats(session, region_row.code, hours)
    narrative = await narrator(stats)
    return {
        "region_code": region_row.code,
        "region_name": region_row.name,
        "window_hours": stats["window_hours"],
        "stats": stats,
        "narrative": narrative,
        "caveats": [
            "Statistics computed in code; the model only narrates them.",
            "Average (not marginal) emissions over ingested hours.",
        ],
    }
