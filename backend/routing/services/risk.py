"""Weather risk classification — a direct encoding of the assessment's rule table.

Condition | Low       | Moderate  | High      | Severe    | No Travel
----------|-----------|-----------|-----------|-----------|----------
Wind      | <25 mph   | 25–34     | 35–44     | 45–54     | ≥55 mph
Rain      | <0.10 in/h| 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00
Snow      | <0.5 in/h | 0.5–1.0   | 1.0–2.0   | 2.0–3.0   | >3.0

Load rules (applied to wind only):
  * ≥55 mph                    → No Travel for any load
  * 45–54 mph and >30,000 lb   → No Travel
  * 35–44 mph and >40,000 lb   → Severe

Boundary interpretation (the table's ranges overlap at their edges):
  * Each band includes its lower bound, e.g. wind 35.0 → High, rain 0.25 → High.
  * Wind's integer bands are treated as continuous: 34.6 mph is still Moderate.
  * "No Travel" for rain/snow is strictly greater than the top value (rain 1.00
    is Severe, 1.01 is No Travel), while wind No Travel is inclusive (≥55).

The overall checkpoint level is the worst of the individual conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def key(self) -> str:
        return self.name.lower()


_LABELS = {
    RiskLevel.LOW: "Low",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.HIGH: "High",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.NO_TRAVEL: "No Travel",
}


@dataclass(frozen=True)
class Thresholds:
    """Lower bounds of Moderate, High, Severe and No Travel."""

    name: str
    unit: str
    moderate: float
    high: float
    severe: float
    no_travel: float
    no_travel_inclusive: bool

    def level(self, value: float) -> RiskLevel:
        if value > self.no_travel or (self.no_travel_inclusive and value >= self.no_travel):
            return RiskLevel.NO_TRAVEL
        if value >= self.severe:
            return RiskLevel.SEVERE
        if value >= self.high:
            return RiskLevel.HIGH
        if value >= self.moderate:
            return RiskLevel.MODERATE
        return RiskLevel.LOW

    def index(self, value: float) -> float:
        """Continuous 0–4 index, linear inside each band (used for heatmaps).

        ``floor(index)`` always equals ``level(value)`` so the smooth heatmap
        never disagrees with the discrete checkpoint classification.
        """
        stops = (0.0, self.moderate, self.high, self.severe, self.no_travel)
        level = self.level(value)
        if level == RiskLevel.NO_TRAVEL:
            return 4.0
        lo, hi = stops[level], stops[level + 1]
        fraction = (value - lo) / (hi - lo) if hi > lo else 0.0
        return level + min(max(fraction, 0.0), 0.999)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "unit": self.unit,
            "moderate": self.moderate,
            "high": self.high,
            "severe": self.severe,
            "no_travel": self.no_travel,
            "no_travel_inclusive": self.no_travel_inclusive,
        }


WIND = Thresholds("wind", "mph", 25, 35, 45, 55, no_travel_inclusive=True)
RAIN = Thresholds("rain", "in/hr", 0.10, 0.25, 0.50, 1.00, no_travel_inclusive=False)
SNOW = Thresholds("snow", "in/hr", 0.5, 1.0, 2.0, 3.0, no_travel_inclusive=False)

# Load rules
HEAVY_LOAD_NO_TRAVEL_LB = 30_000  # with 45–54 mph wind
HEAVY_LOAD_SEVERE_LB = 40_000  # with 35–44 mph wind


@dataclass(frozen=True)
class Conditions:
    wind_mph: float
    rain_in_hr: float
    snow_in_hr: float


@dataclass
class Assessment:
    level: RiskLevel
    index: float  # continuous 0–4, floor(index) == level
    wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel
    factors: list[str] = field(default_factory=list)


def wind_level_for_load(wind_mph: float, load_lb: float) -> tuple[RiskLevel, str | None]:
    """Wind level after applying the load rules, plus the rule that fired."""
    base = WIND.level(wind_mph)
    if base == RiskLevel.SEVERE and load_lb > HEAVY_LOAD_NO_TRAVEL_LB:
        return RiskLevel.NO_TRAVEL, (
            f"45–54 mph wind with load over {HEAVY_LOAD_NO_TRAVEL_LB:,} lb → No Travel"
        )
    if base == RiskLevel.HIGH and load_lb > HEAVY_LOAD_SEVERE_LB:
        return RiskLevel.SEVERE, (
            f"35–44 mph wind with load over {HEAVY_LOAD_SEVERE_LB:,} lb → Severe"
        )
    return base, None


def assess(conditions: Conditions, load_lb: float) -> Assessment:
    wind_level, load_rule = wind_level_for_load(conditions.wind_mph, load_lb)
    rain_level = RAIN.level(conditions.rain_in_hr)
    snow_level = SNOW.level(conditions.snow_in_hr)
    level = max(wind_level, rain_level, snow_level)

    index = max(
        WIND.index(conditions.wind_mph),
        RAIN.index(conditions.rain_in_hr),
        SNOW.index(conditions.snow_in_hr),
    )
    # Load rules can raise the level above what the raw wind index says.
    if level > index:
        index = float(level)
    index = min(index, float(level) + 0.999) if level < RiskLevel.NO_TRAVEL else 4.0

    factors: list[str] = []
    if wind_level > RiskLevel.LOW:
        factors.append(f"Wind {conditions.wind_mph:.0f} mph ({wind_level.label})")
    if load_rule:
        factors.append(load_rule)
    if rain_level > RiskLevel.LOW:
        factors.append(f"Rain {conditions.rain_in_hr:.2f} in/hr ({rain_level.label})")
    if snow_level > RiskLevel.LOW:
        factors.append(f"Snow {conditions.snow_in_hr:.2f} in/hr ({snow_level.label})")

    return Assessment(
        level=level,
        index=round(index, 3),
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        factors=factors,
    )


def rules_payload() -> dict:
    """Rule table for the UI legend, so thresholds live in one place."""
    return {
        "levels": [{"value": int(lvl), "key": lvl.key, "label": lvl.label} for lvl in RiskLevel],
        "conditions": [WIND.as_dict(), RAIN.as_dict(), SNOW.as_dict()],
        "load_rules": [
            {"min_wind_mph": 55, "max_wind_mph": None, "min_load_lb": 0, "level": "no_travel"},
            {"min_wind_mph": 45, "max_wind_mph": 54, "min_load_lb": HEAVY_LOAD_NO_TRAVEL_LB,
             "level": "no_travel"},
            {"min_wind_mph": 35, "max_wind_mph": 44, "min_load_lb": HEAVY_LOAD_SEVERE_LB,
             "level": "severe"},
        ],
    }
