import logging

import numpy as np
from django.conf import settings
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import HeatmapRequestSerializer, PlanRequestSerializer
from .services import geo, geocoding
from .services.heatmap import build_heatmap
from .services.http import ExternalServiceError
from .services.planner import plan_trip
from .services.risk import rules_payload

log = logging.getLogger(__name__)


def _error(message: str, code=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": message}, status=code)


def _first_error(errors) -> str:
    """Flatten DRF's nested error dict into one readable message."""
    if isinstance(errors, dict):
        field, value = next(iter(errors.items()))
        prefix = "" if field == "non_field_errors" else f"{field.replace('_', ' ')}: "
        return prefix + _first_error(value)
    if isinstance(errors, list):
        return _first_error(errors[0])
    return str(errors)


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
def meta(request):
    return Response({"rules": rules_payload(), "truck_max_speed_mph": settings.TRUCK_MAX_SPEED_MPH})


@api_view(["GET"])
def geocode(request):
    try:
        return Response({"results": geocoding.search(request.query_params.get("q", ""))})
    except ExternalServiceError as exc:
        return _error(str(exc), status.HTTP_502_BAD_GATEWAY)


@api_view(["POST"])
def plan(request):
    serializer = PlanRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return _error(_first_error(serializer.errors))
    data = serializer.validated_data
    try:
        origin = _resolve(data["origin"])
        destination = _resolve(data["destination"])
        if geo.haversine_mi(origin["lat"], origin["lon"], destination["lat"], destination["lon"]) < 1:
            return _error("Origin and destination must be at least a mile apart.")
        result = plan_trip(
            origin=origin,
            destination=destination,
            departure=data["departure"],
            load_lb=data["load_weight_lb"],
            interval_mi=int(data["interval_mi"]),
        )
    except ExternalServiceError as exc:
        return _error(str(exc), status.HTTP_502_BAD_GATEWAY)
    return Response(result)


@api_view(["POST"])
def heatmap(request):
    serializer = HeatmapRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return _error(_first_error(serializer.errors))
    data = serializer.validated_data
    try:
        result = build_heatmap(
            [np.asarray(p, dtype=float) for p in data["paths"]],
            data["departure"],
            data["load_weight_lb"],
        )
    except ExternalServiceError as exc:
        return _error(str(exc), status.HTTP_502_BAD_GATEWAY)
    return Response(result)


def _resolve(place: dict) -> dict:
    if "lat" in place:
        return {"label": place["label"], "lat": place["lat"], "lon": place["lon"]}
    found = geocoding.resolve(place["label"])
    return {"label": found["label"], "lat": found["lat"], "lon": found["lon"]}


def spa_index(request):
    index = settings.FRONTEND_DIST / "index.html"
    if index.exists():
        return HttpResponse(index.read_bytes(), content_type="text/html")
    return HttpResponse(
        "Frontend not built. Run `npm run build` in frontend/ or use the Vite dev server.",
        content_type="text/plain",
        status=404,
    )
