"""AI layer tests.

SQL-guard unit tests are pure. Endpoint tests inject a FAKE generator/narrator
(dependency overrides) so CI never calls the real model — but the guardrails
and read-only execution path run for real against synthetic data on a 'TST'
region that live ingests never touch.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.api.v1.ai import get_narrator, get_sql_generator
from app.db.session import SessionLocal
from app.main import app
from app.models import CarbonIntensityHourly, Region
from app.services.ai.sql_guard import SqlGuardError, validate_and_prepare

DAY = datetime(2099, 1, 1, tzinfo=UTC)


# --- SQL guard (pure) ----------------------------------------------------


def test_guard_injects_limit():
    out = validate_and_prepare("SELECT region_code FROM ai_carbon_intensity")
    assert "LIMIT 500" in out.upper()


def test_guard_allows_curated_view():
    out = validate_and_prepare("SELECT gco2_per_kwh FROM ai_regions LIMIT 5")
    assert "ai_regions" in out


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM ai_regions",
        "DROP VIEW ai_regions",
        "UPDATE ai_regions SET name='x'",
        "INSERT INTO ai_regions VALUES (1)",
        "SELECT * FROM regions",  # base table, not a view
        "SELECT * FROM pg_catalog.pg_tables",  # system catalog
        "SELECT 1; SELECT 2",  # two statements
        "TRUNCATE ai_regions",
    ],
)
def test_guard_rejects_dangerous_sql(sql):
    with pytest.raises(SqlGuardError):
        validate_and_prepare(sql)


# --- endpoint tests with injected fakes ----------------------------------


@pytest.fixture
async def ai_region():
    from app.seed.load import seed_all

    async with SessionLocal() as session:
        await seed_all(session)
        await session.merge(
            Region(code="TST", name="Test Grid", egrid_subregion="TEST",
                   mapping_confidence="exact", timezone="UTC")
        )
        await session.flush()
        session.add_all([
            CarbonIntensityHourly(
                region_code="TST", period=DAY + timedelta(hours=h),
                gco2_per_kwh=100 + h, total_mwh=1000, renewable_share=0.4,
                carbon_free_share=0.5, low_confidence_share=0.1,
            )
            for h in range(24)
        ])
        await session.commit()
    yield "TST"
    async with SessionLocal() as session:
        await session.execute(
            delete(CarbonIntensityHourly).where(CarbonIntensityHourly.region_code == "TST")
        )
        await session.execute(delete(Region).where(Region.code == "TST"))
        await session.commit()


def _set_generator(fn):
    app.dependency_overrides[get_sql_generator] = lambda: fn


def _clear():
    app.dependency_overrides.pop(get_sql_generator, None)
    app.dependency_overrides.pop(get_narrator, None)


async def test_ask_happy_path(client, ai_region):
    async def fake_gen(question, repair_error):
        return {
            "sql": "SELECT count(*) AS n FROM ai_carbon_intensity WHERE region_code='TST'",
            "explanation": "Counts TST rows.",
            "confidence": "high",
        }

    _set_generator(fake_gen)
    try:
        resp = await client.post("/v1/ai/ask", json={"question": "how many TST rows?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 1
        assert body["rows"][0]["n"] == 24
        assert body["repaired"] is False
        assert "LIMIT" in body["sql"].upper()
    finally:
        _clear()


async def test_ask_repairs_after_bad_sql(client, ai_region):
    calls = {"n": 0}

    async def flaky_gen(question, repair_error):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"sql": "SELECT * FROM regions", "explanation": "x", "confidence": "low"}
        # repair_error should have been passed back
        assert repair_error is not None
        return {
            "sql": "SELECT count(*) AS n FROM ai_carbon_intensity WHERE region_code='TST'",
            "explanation": "fixed", "confidence": "medium",
        }

    _set_generator(flaky_gen)
    try:
        resp = await client.post("/v1/ai/ask", json={"question": "count TST"})
        assert resp.status_code == 200
        assert resp.json()["repaired"] is True
        assert calls["n"] == 2
    finally:
        _clear()


async def test_ask_blocks_dml_then_422(client, ai_region):
    async def evil_gen(question, repair_error):
        return {"sql": "DELETE FROM ai_regions", "explanation": "x", "confidence": "low"}

    _set_generator(evil_gen)
    try:
        resp = await client.post("/v1/ai/ask", json={"question": "delete everything"})
        assert resp.status_code == 422  # guard blocked it; no execution
    finally:
        _clear()


async def test_ask_empty_question_400(client):
    resp = await client.post("/v1/ai/ask", json={"question": "   "})
    assert resp.status_code == 400


async def test_insights_compute_then_narrate(client, ai_region):
    async def fake_narrator(stats):
        return "NARRATIVE"

    app.dependency_overrides[get_narrator] = lambda: fake_narrator
    try:
        resp = await client.get("/v1/ai/insights?region=TST&hours=24")
        assert resp.status_code == 200
        body = resp.json()
        assert body["narrative"] == "NARRATIVE"
        assert body["stats"]["window_hours"] == 24
        # gco2 ran 100..123 -> mean 111.5, min 100, max 123
        assert body["stats"]["mean_gco2_per_kwh"] == pytest.approx(111.5, abs=0.1)
        assert body["stats"]["min_gco2_per_kwh"] == 100.0
        assert body["stats"]["max_gco2_per_kwh"] == 123.0
    finally:
        _clear()


async def test_insights_unknown_region_404(client):
    resp = await client.get("/v1/ai/insights?region=ZZZ")
    assert resp.status_code == 404
