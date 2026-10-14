"""Hourly forecasts from Open-Meteo, batched by location and cached.

Units requested from the API match the risk rules directly: wind in mph,
rain and snowfall in inches. Open-Meteo reports precipitation as the amount
accumulated over the *preceding* hour, so the value stamped HH:00 is the rate
for (HH-1:00, HH:00]. Instantaneous fields (wind, temperature) are linearly
interpolated to the exact ETA.
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from django.conf import settings
from django.core.cache import cache

from .http import ExternalServiceError, session

log = logging.getLogger(__name__)

HOURLY_VARS = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "rain",
    "showers",
    "snowfall",
    "temperature_2m",
    "weather_code",
)
BATCH_SIZE = 100  # locations per request; keeps URLs well under limits
COORD_DECIMALS = 2  # ~1 km; lets overlapping routes share forecasts
MIN_WINDOW_HOURS = 72


@dataclass
class HourlySeries:
    """Hourly forecast for one location, starting at ``start`` (UTC, on the hour)."""

    start: datetime
    wind: np.ndarray
    gust: np.ndarray
    rain: np.ndarray  # rain + showers, in/hr
    snow: np.ndarray  # in/hr
    temp: np.ndarray  # °F
    code: np.ndarray  # WMO weather code

    def _hours(self, when: datetime) -> float:
        return (when - self.start).total_seconds() / 3600

    def _interp(self, values: np.ndarray, when: datetime) -> float:
        h = min(max(self._hours(when), 0.0), len(values) - 1)
        lo = int(math.floor(h))
        hi = min(lo + 1, len(values) - 1)
        return float(values[lo] + (values[hi] - values[lo]) * (h - lo))

    def _bucket(self, values: np.ndarray, when: datetime) -> float:
        # Accumulation stamped at the end of the hour that contains ``when``.
        idx = int(math.floor(self._hours(when))) + 1
        return float(values[min(max(idx, 0), len(values) - 1)])

    def at(self, when: datetime) -> dict:
        return {
            "wind_mph": round(self._interp(self.wind, when), 1),
            "gust_mph": round(self._interp(self.gust, when), 1),
            "rain_in_hr": round(self._bucket(self.rain, when), 3),
            "snow_in_hr": round(self._bucket(self.snow, when), 3),
            "temp_f": round(self._interp(self.temp, when), 1),
            "weather_code": int(self._bucket(self.code, when)),
        }

    def hourly(self, hour_start: datetime) -> dict:
        """Raw values for the hour beginning at ``hour_start`` (on the hour)."""
        idx = int(round(self._hours(hour_start)))
        cur = min(max(idx, 0), len(self.wind) - 1)
        nxt = min(max(idx + 1, 0), len(self.rain) - 1)
        return {
            "wind": float(self.wind[cur]),
            "rain": float(self.rain[nxt]),
            "snow": float(self.snow[nxt]),
        }


def floor_hour(when: datetime) -> datetime:
    return when.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _round(point: tuple[float, float]) -> tuple[float, float]:
    return round(point[0], COORD_DECIMALS), round(point[1], COORD_DECIMALS)


def _cache_key(point: tuple[float, float], start: datetime, hours: int) -> str:
    return f"wx:{point[0]:.2f},{point[1]:.2f}:{start:%Y%m%d%H}:{hours}"


def _clean(values) -> np.ndarray:
    # Open-Meteo uses null for missing hours (e.g. beyond a model's horizon).
    return np.nan_to_num(np.array(values, dtype=float), nan=0.0)


def _fetch_batch(points: list[tuple[float, float]], start: datetime, hours: int) -> list[HourlySeries]:
    end = start + timedelta(hours=hours - 1)
    params = {
        "latitude": ",".join(f"{lat:.2f}" for lat, _ in points),
        "longitude": ",".join(f"{lon:.2f}" for _, lon in points),
        "hourly": ",".join(HOURLY_VARS),
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "temperature_unit": "fahrenheit",
        "timezone": "GMT",
        "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
    }
    if settings.OPEN_METEO_API_KEY:
        params["apikey"] = settings.OPEN_METEO_API_KEY
    try:
        resp = session().get(settings.OPEN_METEO_URL, params=params, timeout=45)
        data = resp.json()
    except requests.exceptions.RetryError as exc:
        raise ExternalServiceError(
            "Weather service rate limit reached (free Open-Meteo tier). Please retry in a minute."
        ) from exc
    except Exception as exc:
        raise ExternalServiceError(f"Weather service unavailable ({exc}).") from exc
    if isinstance(data, dict) and data.get("error"):
        raise ExternalServiceError(f"Weather service error: {data.get('reason')}")
    results = data if isinstance(data, list) else [data]

    series = []
    for item in results:
        h = item["hourly"]
        series.append(
            HourlySeries(
                start=start,
                wind=_clean(h["wind_speed_10m"]),
                gust=_clean(h["wind_gusts_10m"]),
                rain=_clean(h["rain"]) + _clean(h["showers"]),
                snow=_clean(h["snowfall"]),
                temp=_clean(h["temperature_2m"]),
                code=_clean(h["weather_code"]),
            )
        )
    return series


def fetch_window(start: datetime, hours: int) -> tuple[datetime, int]:
    """Widen a request to a cache-friendly window.

    Windows start on a 6-hour boundary and span whole days (at least three),
    so checkpoints, the heatmap and re-plans with a different interval, load
    or nearby departure time all share cached forecasts. This matters because
    the free Open-Meteo tier counts every location as one API call.
    """
    start = floor_hour(start)
    aligned = start.replace(hour=start.hour - start.hour % 6)
    needed = (start - aligned).total_seconds() / 3600 + hours
    return aligned, max(MIN_WINDOW_HOURS, int(math.ceil(needed / 24)) * 24)


def get_hourly(points: list[tuple[float, float]], start: datetime, hours: int) -> list[HourlySeries]:
    """Hourly series for each point covering at least ``[start, start + hours)``.

    Points are rounded and de-duplicated before fetching, and results are
    cached per (location, window), so overlapping routes and repeated
    requests only hit the API once.
    """
    start, hours = fetch_window(start, hours)
    rounded = [_round(p) for p in points]
    unique = list(dict.fromkeys(rounded))

    found: dict[tuple[float, float], HourlySeries] = {}
    keys = {p: _cache_key(p, start, hours) for p in unique}
    cached = cache.get_many(list(keys.values()))
    for p, key in keys.items():
        if key in cached:
            found[p] = cached[key]

    missing = [p for p in unique if p not in found]
    batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
    if batches:
        log.info("Fetching weather for %d locations in %d batches", len(missing), len(batches))
        with ThreadPoolExecutor(max_workers=4) as pool:
            for batch, result in zip(batches, pool.map(lambda b: _fetch_batch(b, start, hours), batches)):
                for p, series in zip(batch, result):
                    found[p] = series
                cache.set_many(
                    {keys[p]: s for p, s in zip(batch, result)}, settings.WEATHER_CACHE_SECONDS
                )

    return [found[p] for p in rounded]


WMO_DESCRIPTIONS = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Freezing fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Heavy freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Heavy showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm, hail",
    99: "Severe thunderstorm, hail",
}


def describe(code: int) -> str:
    return WMO_DESCRIPTIONS.get(code, "Unknown")
