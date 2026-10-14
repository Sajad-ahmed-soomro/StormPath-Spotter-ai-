"""Trip planning: routes → timed checkpoints → weather at ETA → risk → recommendation."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from django.conf import settings

from . import geo, geocoding, osrm, recommend, weather
from .risk import Conditions, RiskLevel, assess, rules_payload

ROUTE_IDS = "ABC"


@dataclass
class TimedRoute:
    """A route with truck-adjusted cumulative distance and time at every vertex."""

    coords: np.ndarray  # (N, 2) lat/lon
    cum_mi: np.ndarray  # (N,)
    cum_s: np.ndarray  # (N,) seconds after departure
    source: str

    @property
    def distance_mi(self) -> float:
        return float(self.cum_mi[-1])

    @property
    def duration_s(self) -> float:
        return float(self.cum_s[-1])


def truck_timed(raw: osrm.RawRoute, max_speed_mph: float) -> TimedRoute:
    """Apply the truck speed cap to OSRM's (car) segment times."""
    seg_mi = geo.segment_lengths_mi(raw.coords)
    min_seconds = seg_mi / max_speed_mph * 3600
    seg_s = np.maximum(raw.seg_seconds, min_seconds)
    return TimedRoute(
        coords=raw.coords,
        cum_mi=geo.cumulative(seg_mi),
        cum_s=geo.cumulative(seg_s),
        source=raw.source,
    )


def checkpoint_miles(distance_mi: float, interval_mi: float) -> np.ndarray:
    """Origin, every ``interval_mi`` along the route, and the destination."""
    miles = np.arange(0.0, distance_mi, interval_mi) if distance_mi > 0 else np.zeros(1)
    if distance_mi - miles[-1] > 1e-6:
        miles = np.append(miles, distance_mi)
    return miles


def coverage(miles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each checkpoint represents the stretch of road closer to it than to its neighbours."""
    mids = (miles[:-1] + miles[1:]) / 2
    starts = np.concatenate([[miles[0]], mids])
    ends = np.concatenate([mids, [miles[-1]]])
    return starts, ends


@dataclass
class Checkpoint:
    mile: float
    lat: float
    lon: float
    eta: datetime
    elapsed_s: float
    covers: tuple[float, float]
    weather: dict | None = None
    level: RiskLevel = RiskLevel.LOW
    index: float = 0.0
    factors: list[str] | None = None


def build_checkpoints(route: TimedRoute, interval_mi: float, departure: datetime) -> list[Checkpoint]:
    miles = checkpoint_miles(route.distance_mi, interval_mi)
    positions = geo.interpolate_along(route.cum_mi, route.coords, miles)
    elapsed = np.interp(miles, route.cum_mi, route.cum_s)
    starts, ends = coverage(miles)
    return [
        Checkpoint(
            mile=float(m),
            lat=float(p[0]),
            lon=float(p[1]),
            eta=departure + timedelta(seconds=float(t)),
            elapsed_s=float(t),
            covers=(float(a), float(b)),
        )
        for m, p, t, a, b in zip(miles, positions, elapsed, starts, ends)
    ]


def risk_miles(checkpoints: list[Checkpoint]) -> dict[RiskLevel, float]:
    out = {level: 0.0 for level in RiskLevel}
    for cp in checkpoints:
        out[cp.level] += cp.covers[1] - cp.covers[0]
    return out


def risk_segments(route: TimedRoute, checkpoints: list[Checkpoint], tolerance: float) -> list[dict]:
    """Route geometry split into runs of equal risk level, for map colouring."""
    runs: list[list] = []
    for cp in checkpoints:
        if runs and runs[-1][0] == cp.level:
            runs[-1][2] = cp.covers[1]
        else:
            runs.append([cp.level, cp.covers[0], cp.covers[1]])
    segments = []
    for level, start, end in runs:
        if end - start <= 0:
            continue
        line = geo.slice_line(route.cum_mi, route.coords, start, end)
        line = line[geo.simplify(line, tolerance)]
        segments.append({"level": int(level), "coords": np.round(line, 5).tolist()})
    return segments


def _distinct_point(route: TimedRoute, others: list[TimedRoute]) -> tuple[float, float]:
    """The point on ``route`` farthest from every other route (for naming it)."""
    samples = geo.resample(route.coords, max(route.distance_mi / 60, 0.5))
    if not others:
        mid = len(samples) // 2
        return float(samples[mid, 0]), float(samples[mid, 1])
    other_pts = np.vstack([geo.resample(o.coords, 2.0) for o in others])
    i = int(np.argmax(geo.min_distance_mi(samples, other_pts)))
    return float(samples[i, 0]), float(samples[i, 1])


def _route_names(routes: list[TimedRoute]) -> list[str | None]:
    points = [_distinct_point(r, [o for o in routes if o is not r]) for r in routes]
    with ThreadPoolExecutor(max_workers=3) as pool:
        names = list(pool.map(lambda p: geocoding.place_name(*p), points))
    # Two routes "via" the same town are not a helpful distinction.
    return [n if names.count(n) == 1 else None for n in names]


def _serialize_checkpoint(i: int, cp: Checkpoint) -> dict:
    return {
        "index": i,
        "mile": round(cp.mile, 1),
        "lat": round(cp.lat, 5),
        "lon": round(cp.lon, 5),
        "eta": cp.eta.isoformat(),
        "elapsed_h": round(cp.elapsed_s / 3600, 2),
        "covers_mi": [round(cp.covers[0], 2), round(cp.covers[1], 2)],
        "weather": cp.weather,
        "level": int(cp.level),
        "level_label": cp.level.label,
        "index_value": cp.index,
        "factors": cp.factors,
    }


def plan_trip(
    origin: dict,
    destination: dict,
    departure: datetime,
    load_lb: float,
    interval_mi: int,
) -> dict:
    raw_routes = osrm.get_routes((origin["lat"], origin["lon"]), (destination["lat"], destination["lon"]))
    routes = [truck_timed(r, settings.TRUCK_MAX_SPEED_MPH) for r in raw_routes]
    all_checkpoints = [build_checkpoints(r, interval_mi, departure) for r in routes]

    # One weather fetch for every checkpoint of every route.
    latest_eta = max(cps[-1].eta for cps in all_checkpoints)
    start = weather.floor_hour(departure)
    hours = math.ceil((latest_eta - start).total_seconds() / 3600) + 2
    flat = [cp for cps in all_checkpoints for cp in cps]
    series = weather.get_hourly([(cp.lat, cp.lon) for cp in flat], start, hours)
    for cp, s in zip(flat, series):
        wx = s.at(cp.eta)
        wx["description"] = weather.describe(wx["weather_code"])
        result = assess(Conditions(wx["wind_mph"], wx["rain_in_hr"], wx["snow_in_hr"]), load_lb)
        cp.weather, cp.level, cp.index, cp.factors = wx, result.level, result.index, result.factors

    names = _route_names(routes)
    fastest = min(r.duration_s for r in routes)
    summaries, payload = [], []
    for route_id, route, checkpoints, name in zip(ROUTE_IDS, routes, all_checkpoints, names):
        by_level = risk_miles(checkpoints)
        total = route.distance_mi or 1.0
        avg = sum(int(lvl) * mi for lvl, mi in by_level.items()) / total
        summaries.append(
            recommend.RiskSummary(
                route_id=route_id,
                no_travel_mi=by_level[RiskLevel.NO_TRAVEL],
                severe_mi=by_level[RiskLevel.SEVERE],
                high_mi=by_level[RiskLevel.HIGH],
                avg_risk=avg,
                duration_s=route.duration_s,
            )
        )
        tolerance = 0.0002 if route.distance_mi < 150 else 0.0006
        keep = geo.simplify(route.coords, tolerance)
        payload.append(
            {
                "id": route_id,
                "name": f"Route {route_id}" + (f" via {name}" if name else ""),
                "via": name,
                "source": route.source,
                "distance_mi": round(route.distance_mi, 1),
                "duration_h": round(route.duration_s / 3600, 2),
                "extra_minutes": round((route.duration_s - fastest) / 60),
                "arrival": (departure + timedelta(seconds=route.duration_s)).isoformat(),
                "risk": {
                    "miles_by_level": {lvl.key: round(mi, 1) for lvl, mi in by_level.items()},
                    "avg_risk": round(avg, 3),
                    "max_level": int(max(cp.level for cp in checkpoints)),
                },
                # Simplified geometry with time-after-departure at each vertex,
                # used by the UI to place the truck on the forecast timeline.
                "path": np.round(route.coords[keep], 5).tolist(),
                "path_elapsed_s": np.round(route.cum_s[keep]).astype(int).tolist(),
                "segments": risk_segments(route, checkpoints, tolerance),
                "checkpoints": [_serialize_checkpoint(i, cp) for i, cp in enumerate(checkpoints)],
            }
        )

    ranked = recommend.rank(summaries)
    rank_of = {s.route_id: i + 1 for i, s in enumerate(ranked)}
    for route in payload:
        route["rank"] = rank_of[route["id"]]
        route["recommended"] = route["rank"] == 1

    return {
        "origin": origin,
        "destination": destination,
        "departure": departure.isoformat(),
        "load_weight_lb": load_lb,
        "interval_mi": interval_mi,
        "truck_max_speed_mph": settings.TRUCK_MAX_SPEED_MPH,
        "routes": payload,
        "recommendation": recommend.explain(ranked),
        "rules": rules_payload(),
    }
