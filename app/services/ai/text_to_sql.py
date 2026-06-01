"""Orchestrates NL->SQL: generate -> validate -> execute, with one repair retry."""

import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException

from app.core.logging import log_event
from app.db.readonly import run_readonly_query
from app.services.ai.sql_guard import SqlGuardError, validate_and_prepare

logger = logging.getLogger("gridclean.ai")

# A generator takes (question, repair_error) and returns {sql, explanation, confidence}.
SqlGenerator = Callable[[str, str | None], Awaitable[dict]]

MAX_ATTEMPTS = 2  # initial + one repair


async def answer_question(question: str, generator: SqlGenerator) -> dict:
    """Return a structured answer, or raise 422 with the attempt trace."""
    attempts: list[dict] = []
    error: str | None = None

    for attempt in range(MAX_ATTEMPTS):
        gen = await generator(question, error)
        raw_sql = gen["sql"]

        try:
            safe_sql = validate_and_prepare(raw_sql)
        except SqlGuardError as exc:
            error = f"validation: {exc}"
            attempts.append({"sql": raw_sql, "error": error})
            continue

        try:
            rows = await run_readonly_query(safe_sql)
        except Exception as exc:  # noqa: BLE001 — feed DB error back for repair
            error = f"execution: {type(exc).__name__}: {exc}"
            attempts.append({"sql": safe_sql, "error": error})
            continue

        log_event(
            logger, "ai_ask_ok",
            question=question, repaired=attempt > 0, rows=len(rows),
        )
        return {
            "question": question,
            "sql": safe_sql,
            "explanation": gen.get("explanation", ""),
            "confidence": gen.get("confidence", "medium"),
            "repaired": attempt > 0,
            "row_count": len(rows),
            "rows": rows,
            "caveats": [
                "SQL is AI-generated; the exact query run is shown above for review.",
                "Read-only query against curated views; results reflect ingested data only.",
            ],
        }

    log_event(logger, "ai_ask_failed", question=question, attempts=len(attempts))
    raise HTTPException(
        status_code=422,
        detail={
            "message": "Could not produce a valid query for that question.",
            "attempts": attempts,
        },
    )
