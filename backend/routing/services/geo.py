"""Small, dependency-light geometry helpers (lat/lon in degrees, distances in miles)."""

from __future__ import annotations

import math

import numpy as np

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344


def decode_polyline(encoded: str, precision: int = 6) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline (OSRM ``polyline6``) into (lat, lon) pairs."""
    coords: list[tuple[float, float]] = []
    index = lat = lon = 0
    factor = 10**precision
    length = len(encoded)
    while index < length:
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        coords.append((lat / factor, lon / factor))
    return coords


def haversine_mi(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles; works on scalars or numpy arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MI * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def segment_lengths_mi(coords: np.ndarray) -> np.ndarray:
    """Length of each consecutive segment of an (N, 2) lat/lon array."""
    return haversine_mi(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1])


def cumulative(values: np.ndarray) -> np.ndarray:
    """Prefix sum with a leading zero (N-1 segment values -> N vertex values)."""
    return np.concatenate([[0.0], np.cumsum(values)])


def interpolate_along(cum_mi: np.ndarray, coords: np.ndarray, miles: np.ndarray) -> np.ndarray:
    """Positions (lat, lon) at the given distances along a polyline."""
    lat = np.interp(miles, cum_mi, coords[:, 0])
    lon = np.interp(miles, cum_mi, coords[:, 1])
    return np.column_stack([lat, lon])


def slice_line(cum_mi: np.ndarray, coords: np.ndarray, start_mi: float, end_mi: float) -> np.ndarray:
    """Sub-polyline between two distances, with interpolated end points."""
    inner = (cum_mi > start_mi) & (cum_mi < end_mi)
    ends = interpolate_along(cum_mi, coords, np.array([start_mi, end_mi]))
    return np.vstack([ends[:1], coords[inner], ends[1:]])


def simplify(coords: np.ndarray, tolerance_deg: float) -> np.ndarray:
    """Ramer–Douglas–Peucker; returns the indices of the vertices to keep."""
    n = len(coords)
    if n < 3:
        return np.arange(n)
    # Work in a locally equirectangular plane so tolerance is roughly isotropic.
    scale = math.cos(math.radians(float(np.mean(coords[:, 0]))))
    pts = np.column_stack([coords[:, 1] * scale, coords[:, 0]])
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        a, b = pts[first], pts[last]
        seg = pts[first + 1 : last]
        ab = b - a
        denom = float(np.hypot(*ab))
        if denom == 0:
            dists = np.hypot(*(seg - a).T)
        else:
            dists = np.abs(ab[0] * (seg[:, 1] - a[1]) - ab[1] * (seg[:, 0] - a[0])) / denom
        i = int(np.argmax(dists))
        if dists[i] > tolerance_deg:
            split = first + 1 + i
            keep[split] = True
            stack.append((first, split))
            stack.append((split, last))
    return np.flatnonzero(keep)


def resample(coords: np.ndarray, spacing_mi: float) -> np.ndarray:
    """Points every ``spacing_mi`` along a polyline (end point included)."""
    cum = cumulative(segment_lengths_mi(coords))
    total = float(cum[-1])
    if total == 0:
        return coords[:1].copy()
    miles = np.append(np.arange(0.0, total, spacing_mi), total)
    return interpolate_along(cum, coords, miles)


def destination_point(lat: float, lon: float, bearing_deg: float, distance_mi: float) -> tuple[float, float]:
    """Point reached travelling ``distance_mi`` from (lat, lon) on a bearing."""
    d = distance_mi / EARTH_RADIUS_MI
    brg = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(brg))
    l2 = l1 + math.atan2(
        math.sin(brg) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2)
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def min_distance_mi(points: np.ndarray, targets: np.ndarray, chunk: int = 2048) -> np.ndarray:
    """For each point, the distance to the nearest target point (both (N, 2) lat/lon)."""
    out = np.empty(len(points))
    t_lat, t_lon = targets[:, 0][None, :], targets[:, 1][None, :]
    for start in range(0, len(points), chunk):
        p = points[start : start + chunk]
        d = haversine_mi(p[:, 0][:, None], p[:, 1][:, None], t_lat, t_lon)
        out[start : start + chunk] = d.min(axis=1)
    return out


def lat_to_mercator_y(lat):
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def mercator_y_to_lat(y):
    return np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)
