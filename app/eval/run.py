"""Run the text-to-SQL eval set with execution-match scoring.

    python -m app.eval.run

Calls the real model (uses ANTHROPIC_API_KEY) once per question, runs both the
generated and reference SQL under the read-only role, and compares result sets
(order-insensitive, floats rounded). Prints a per-case table + accuracy.
"""

import asyncio
from decimal import Decimal

from app.db.readonly import run_readonly_query
from app.eval.dataset import EVALS
from app.services.ai.llm import generate_sql
from app.services.ai.sql_guard import validate_and_prepare
from app.services.ai.text_to_sql import answer_question


def _norm_value(v) -> str:
    if isinstance(v, (int, float, Decimal)):
        return f"{float(v):.1f}"
    return str(v)


def _norm_result(rows: list[dict]) -> list[set]:
    # Order-insensitive across rows and columns; each row is a set of values.
    return [set(_norm_value(v) for v in row.values()) for row in rows]


def _matches(got: list[set], expected: list[set]) -> bool:
    """Execution match by containment: same row count, and every expected row's
    values are contained in a distinct model row. Credits correct answers that
    return extra helpful columns (e.g. region_name alongside region_code)."""
    if len(got) != len(expected):
        return False
    used = [False] * len(got)
    for erow in expected:
        for j, grow in enumerate(got):
            if not used[j] and erow <= grow:
                used[j] = True
                break
        else:
            return False
    return True


async def main() -> None:
    passed = 0
    print(f"\nRunning {len(EVALS)} text-to-SQL evals (execution match)\n" + "=" * 60)

    for i, (question, ref_sql) in enumerate(EVALS, 1):
        try:
            result = await answer_question(question, generate_sql)
            got = _norm_result(result["rows"])
            expected = _norm_result(await run_readonly_query(validate_and_prepare(ref_sql)))
            ok = _matches(got, expected)
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"[{i:2}] ERROR: {type(exc).__name__}: {str(exc)[:60]}")
            print(f"     Q: {question}")
            continue

        passed += ok
        print(f"[{i:2}] {'PASS' if ok else 'FAIL'}  {question}")
        if not ok:
            print(f"     got={got}\n     exp={expected}")

    pct = round(100 * passed / len(EVALS), 1)
    print("=" * 60)
    print(f"Accuracy: {passed}/{len(EVALS)} = {pct}% (execution match)\n")


if __name__ == "__main__":
    asyncio.run(main())
