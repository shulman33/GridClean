"""ORM models. Importing this package registers all models on Base.metadata."""

from app.models.generation import CarbonIntensityHourly, GenerationHourly
from app.models.reference import EmissionFactor, Region, ZipRegion

__all__ = [
    "Region",
    "EmissionFactor",
    "ZipRegion",
    "GenerationHourly",
    "CarbonIntensityHourly",
]
