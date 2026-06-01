"""AST-level validation of AI-generated SQL (the read-allowlist boundary).

A generated query is accepted only if it parses to exactly ONE read-only
SELECT/UNION (optionally with CTEs) that references only the curated `ai_*`
views, and a LIMIT is enforced. Anything else — DML, DDL, multiple statements,
unknown tables, system catalogs — is rejected before execution. We never trust
the model to self-restrict; this runs on every query.
"""

import sqlglot
from sqlglot import exp

# The only objects the AI may read. Curated, documented views (see migration).
ALLOWED_VIEWS = {"ai_carbon_intensity", "ai_regions", "ai_fuel_generation"}
DEFAULT_LIMIT = 500
MAX_LIMIT = 5000

# Expression types that must never appear anywhere in the tree.
_FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.Command, exp.Grant, exp.TruncateTable, exp.Merge,
)


class SqlGuardError(ValueError):
    """Raised when generated SQL fails validation."""


def validate_and_prepare(sql: str) -> str:
    """Validate `sql` and return a safe, LIMIT-enforced statement string."""
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except Exception as exc:  # noqa: BLE001 — surface a clean guard error
        raise SqlGuardError(f"Could not parse SQL: {exc}") from exc

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SqlGuardError("Exactly one statement is allowed.")
    stmt = statements[0]

    if stmt.key not in ("select", "union"):
        raise SqlGuardError("Only SELECT queries are allowed.")

    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN):
            raise SqlGuardError("Only read-only SELECT queries are allowed.")

    referenced = {t.name.lower() for t in stmt.find_all(exp.Table)}
    disallowed = referenced - ALLOWED_VIEWS
    if disallowed:
        raise SqlGuardError(
            f"Query references disallowed objects: {sorted(disallowed)}. "
            f"Allowed views: {sorted(ALLOWED_VIEWS)}."
        )

    # Enforce / cap LIMIT (only meaningful on a top-level SELECT).
    if isinstance(stmt, exp.Select):
        limit = stmt.args.get("limit")
        if limit is None:
            stmt = stmt.limit(DEFAULT_LIMIT)
        else:
            try:
                value = int(limit.expression.name)
                if value > MAX_LIMIT:
                    stmt = stmt.limit(MAX_LIMIT)
            except (AttributeError, ValueError):
                stmt = stmt.limit(DEFAULT_LIMIT)
    else:  # UNION — wrap isn't necessary; append a LIMIT to the whole thing
        stmt = stmt.limit(DEFAULT_LIMIT)

    return stmt.sql(dialect="postgres")
