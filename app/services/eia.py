"""Client for the EIA-930 hourly fuel-type generation API.

Endpoint: /v2/electricity/rto/fuel-type-data/. Returns hourly MWh of
generation per balancing authority (`respondent`) per fuel type. Periods are
hourly UTC strings like "2026-06-01T06"; values may be negative or zero.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.config import get_settings

EIA_BASE = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"

# Fuel codes EIA reports in this dataset. Anything outside this set falls
# through to "OTH" handling at compute time.
KNOWN_FUELS = {"COL", "NG", "NUC", "OIL", "WAT", "WND", "SUN", "GEO", "OTH"}


@dataclass(frozen=True)
class GenerationPoint:
    region_code: str
    period: datetime  # tz-aware UTC
    fuel_code: str
    mwh: float


def _parse_period(raw: str) -> datetime:
    """Parse an EIA hourly period like '2026-06-01T06' into UTC-aware dt."""
    return datetime.strptime(raw, "%Y-%m-%dT%H").replace(tzinfo=UTC)


class EIAClient:
    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or get_settings().eia_api_key
        if not self.api_key:
            raise RuntimeError("EIA_API_KEY is not set")
        self.timeout = timeout

    # EIA caps `length` at 5000 rows per request.
    MAX_PAGE = 5000

    async def fetch_fuel_type(
        self, region_code: str, hours: int = 48
    ) -> list[GenerationPoint]:
        """Fetch the most recent `hours` of fuel-type generation for a BA.

        EIA returns one row per (period, fuel) — ~9 fuels/hour. We page through
        results (newest first, 5000/request) until we've covered `hours` of
        history, so large backfills (weeks) work despite the per-request cap.
        """
        target_rows = hours * 12  # headroom over ~9 fuels/hour
        points: list[GenerationPoint] = []
        offset = 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while len(points) < target_rows:
                length = min(self.MAX_PAGE, target_rows - len(points))
                params = {
                    "api_key": self.api_key,
                    "frequency": "hourly",
                    "data[0]": "value",
                    "facets[respondent][]": region_code,
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "offset": offset,
                    "length": length,
                }
                resp = await client.get(EIA_BASE, params=params)
                resp.raise_for_status()
                rows = resp.json().get("response", {}).get("data", [])
                if not rows:
                    break

                for row in rows:
                    value = row.get("value")
                    if value is None:
                        continue
                    fuel = row.get("fueltype")
                    fuel = fuel if fuel in KNOWN_FUELS else "OTH"
                    points.append(
                        GenerationPoint(
                            region_code=row["respondent"],
                            period=_parse_period(row["period"]),
                            fuel_code=fuel,
                            mwh=float(value),
                        )
                    )

                offset += len(rows)
                if len(rows) < length:  # last page
                    break
        return points
