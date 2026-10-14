"""Place search and reverse lookup via Photon (OpenStreetMap data, no key)."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

from .http import ExternalServiceError, session

log = logging.getLogger(__name__)

US_STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}


def _label(props: dict) -> str:
    state = props.get("state")
    state = US_STATE_ABBR.get(state, state) if props.get("countrycode") == "US" else state
    parts = [props.get("name"), props.get("city"), state]
    if props.get("countrycode") not in (None, "US"):
        parts.append(props.get("country"))
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def search(query: str, limit: int = 6) -> list[dict]:
    query = query.strip()
    if len(query) < 2:
        return []
    key = f"geo:{query.lower()}:{limit}"
    if (hit := cache.get(key)) is not None:
        return hit
    try:
        resp = session().get(
            f"{settings.PHOTON_URL}/api/",
            params={"q": query, "limit": limit, "lang": "en"},
            timeout=10,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except Exception as exc:
        raise ExternalServiceError(f"Geocoding service unavailable ({exc}).") from exc

    results, labels = [], set()
    for f in features:
        lon, lat = f["geometry"]["coordinates"]
        label = _label(f["properties"])
        if label in labels:
            continue
        labels.add(label)
        results.append({"label": label, "lat": lat, "lon": lon, "type": f["properties"].get("type")})
    cache.set(key, results, 24 * 3600)
    return results


def resolve(query: str) -> dict:
    results = search(query, limit=1)
    if not results:
        raise ExternalServiceError(f'Could not find a location matching "{query}".')
    return results[0]


def place_name(lat: float, lon: float) -> str | None:
    """Nearest town/city name for a point, or None if lookup fails."""
    key = f"rev:{lat:.2f},{lon:.2f}"
    if (hit := cache.get(key)) is not None:
        return hit or None
    try:
        resp = session().get(
            f"{settings.PHOTON_URL}/reverse",
            params={"lat": lat, "lon": lon, "lang": "en", "limit": 1},
            timeout=8,
        )
        props = resp.json()["features"][0]["properties"]
    except Exception as exc:
        log.info("Reverse geocode failed: %s", exc)
        return None
    town = props.get("city") or props.get("county") or props.get("name")
    state = props.get("state")
    if props.get("countrycode") == "US":
        state = US_STATE_ABBR.get(state, state)
    name = ", ".join(p for p in (town, state) if p) or ""
    cache.set(key, name, 24 * 3600)
    return name or None
