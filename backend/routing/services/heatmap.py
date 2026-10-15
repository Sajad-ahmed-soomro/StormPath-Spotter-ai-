"""Weather heatmap along the trip corridor for the next 0–48 hours.

The corridor is a buffer around all route options. It is covered by a regular
grid that is uniform in *Web Mercator* space, so the browser can draw it as a
single image stretched over the map bounds with no distortion. Only cells
inside the corridor are forecast; each carries an edge weight for a soft
fade-out at the corridor boundary.

Per hour and cell the payload carries the load-adjusted continuous risk index
(0–4, same rules as checkpoints) plus raw wind, rain and snow values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from . import geo, weather
from .risk import Conditions, assess

HOURS = 48
TARGET_CELLS = 200
MAX_CELLS = 280
MIN_SPACING_MI = 3.0


def corridor_grid(paths: list[np.ndarray]) -> dict:
    """Mercator-uniform grid of cells covering a buffer around the paths."""
    samples = np.vstack([geo.resample(p, 2.0) for p in paths])
    lengths = [float(geo.cumulative(geo.segment_lengths_mi(p))[-1]) for p in paths]
    longest = max(lengths)
    buffer_mi = float(np.clip(longest * 0.07, 20.0, 75.0))

    lat_mid = float(np.mean(samples[:, 0]))
    cos_mid = math.cos(math.radians(lat_mid))
    pad_lat = buffer_mi / 69.0 + 0.1
    pad_lon = buffer_mi / (69.17 * cos_mid) + 0.1
    south, north = samples[:, 0].min() - pad_lat, samples[:, 0].max() + pad_lat
    west, east = samples[:, 1].min() - pad_lon, samples[:, 1].max() + pad_lon

    # Corridor area ≈ union length × width; distinct routes add partial length.
    area = (longest + 0.5 * (sum(lengths) - longest)) * 2 * buffer_mi
    spacing = max(math.sqrt(area / TARGET_CELLS), MIN_SPACING_MI)

    for _ in range(4):
        # Radians of longitude; Mercator y uses the same unit, so cells are square on screen.
        step = spacing / (geo.EARTH_RADIUS_MI * cos_mid)
        x0, x1 = math.radians(west), math.radians(east)
        y0, y1 = float(geo.lat_to_mercator_y(south)), float(geo.lat_to_mercator_y(north))
        nx = max(int(math.ceil((x1 - x0) / step)) + 1, 2)
        ny = max(int(math.ceil((y1 - y0) / step)) + 1, 2)
        xs = x0 + np.arange(nx) * step
        ys = y1 - np.arange(ny) * step  # row 0 is the northern edge
        lon_grid = np.degrees(xs)
        lat_grid = geo.mercator_y_to_lat(ys)
        lat2d, lon2d = np.meshgrid(lat_grid, lon_grid, indexing="ij")
        cells = np.column_stack([lat2d.ravel(), lon2d.ravel()])

        dist = geo.min_distance_mi(cells, samples)
        # Full weight inside the buffer, fading to zero over roughly one cell.
        weight = np.clip((buffer_mi + spacing - dist) / (1.5 * spacing), 0.0, 1.0)
        inside = np.flatnonzero(weight > 0)
        if len(inside) <= MAX_CELLS:
            break
        spacing *= math.sqrt(len(inside) / TARGET_CELLS)

    half = step / 2
    return {
        "nx": nx,
        "ny": ny,
        "spacing_mi": round(spacing, 2),
        "buffer_mi": round(buffer_mi, 1),
        # Image edges (cell centres sit half a step inside them).
        "bounds": {
            "west": math.degrees(x0 - half),
            "east": math.degrees(xs[-1] + half),
            "north": float(geo.mercator_y_to_lat(y1 + half)),
            "south": float(geo.mercator_y_to_lat(ys[-1] - half)),
        },
        "cells": inside,
        "weights": weight[inside],
        "points": cells[inside],
    }


@dataclass
class PreparedHeatmap:
    """Corridor grid kept server-side while the browser fetches its forecasts."""

    grid: dict
    load_lb: float
    weather: weather.WeatherRequest


def prepare_heatmap(paths: list[np.ndarray], departure: datetime, load_lb: float) -> PreparedHeatmap:
    grid = corridor_grid(paths)
    # One extra hour: precipitation for hour h is stamped at h+1.
    request = weather.build_request([tuple(p) for p in grid["points"]], departure, HOURS + 2)
    return PreparedHeatmap(grid=grid, load_lb=load_lb, weather=request)


def score_heatmap(prepared: PreparedHeatmap, hourly_by_location: list) -> dict:
    """Hourly risk/wind/rain/snow per corridor cell for hours 0–48.

    Raises ``weather.InvalidWeatherData`` if the forecasts don't match the spec.
    """
    grid, load_lb = prepared.grid, prepared.load_lb
    start = prepared.weather.start
    series = weather.parse(prepared.weather, hourly_by_location)

    risk, wind, rain, snow = [], [], [], []
    for h in range(HOURS + 1):
        hour = start + timedelta(hours=h)
        r_row, w_row, rn_row, s_row = [], [], [], []
        for s in series:
            v = s.hourly(hour)
            r_row.append(round(assess(Conditions(v["wind"], v["rain"], v["snow"]), load_lb).index, 2))
            w_row.append(round(v["wind"], 1))
            rn_row.append(round(v["rain"], 3))
            s_row.append(round(v["snow"], 2))
        risk.append(r_row)
        wind.append(w_row)
        rain.append(rn_row)
        snow.append(s_row)

    return {
        "start": start.isoformat(),
        "hours": [(start + timedelta(hours=h)).isoformat() for h in range(HOURS + 1)],
        "grid": {
            "nx": grid["nx"],
            "ny": grid["ny"],
            "bounds": grid["bounds"],
            "spacing_mi": grid["spacing_mi"],
            "buffer_mi": grid["buffer_mi"],
            "cells": grid["cells"].tolist(),
            "weights": np.round(grid["weights"], 2).tolist(),
        },
        "layers": {"risk": risk, "wind": wind, "rain": rain, "snow": snow},
    }
