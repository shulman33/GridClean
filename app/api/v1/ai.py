"""AI layer: guardrailed text-to-SQL and compute-then-narrate insights."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import enforce_rate_limit
from app.db.session import get_session
from app.models import Region
from app.schemas import AskIn, AskOut, InsightsOut
from app.services.ai.insights import build_insights, default_narrator
from app.services.ai.llm import generate_sql
from app.services.ai.text_to_sql import answer_question

router = APIRouter(prefix="/ai", tags=["ai"])


# Injected so tests can substitute fakes (no live API calls in CI).
def get_sql_generator():
    return generate_sql


def get_narrator():
    return default_narrator


@router.post("/ask", response_model=AskOut)
async def ai_ask(
    body: AskIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(enforce_rate_limit),
    generator=Depends(get_sql_generator),
):
    """Answer a natural-language question by generating + running guardrailed SQL."""
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    return await answer_question(body.question, generator)


@router.get("/insights", response_model=InsightsOut)
async def ai_insights(
    region: str = Query(min_length=2, max_length=8),
    hours: int = Query(default=168, ge=6, le=720),
    session: AsyncSession = Depends(get_session),
    _=Depends(enforce_rate_limit),
    narrator=Depends(get_narrator),
):
    """Narrate notable patterns in a region's recent carbon intensity."""
    region_row = await session.get(Region, region.upper())
    if region_row is None:
        raise HTTPException(status_code=404, detail=f"Unknown region '{region}'.")
    return await build_insights(session, region_row, hours, narrator)
