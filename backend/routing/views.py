import logging
import uuid

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import ForecastSerializer, HeatmapRequestSerializer, PlanRequestSerializer
from .services import geo, geocoding
from .services.heatmap import prepare_heatmap, score_heatmap
from .services.http import ExternalServiceError
from .services.planner import prepare_plan, score_plan
from .services.risk import rules_payload
from .services.weather import InvalidWeatherData

# Prepared plans/heatmaps wait in the cache while the browser fetches weather.
STAGE_TTL_SECONDS = 60 * 60
EXPIRED = "This plan has expired. Please plan the trip again."

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
    return Response(
        {
            "rules": rules_payload(),
            "truck_max_speed_mph": settings.TRUCK_MAX_SPEED_MPH,
            "basemap": {"url": settings.BASEMAP_URL, "labels_url": settings.BASEMAP_LABELS_URL},
        }
    )


@api_view(["GET"])
def geocode(request):
    try:
        return Response({"results": geocoding.search(request.query_params.get("q", ""))})
    except ExternalServiceError as exc:
        return _error(str(exc), status.HTTP_502_BAD_GATEWAY)


def _stash(kind: str, value) -> str:
    key = uuid.uuid4().hex
    cache.set(f"{kind}:{key}", value, STAGE_TTL_SECONDS)
    return key


@api_view(["POST"])
def plan(request):
    """Stage 1: routes, ETAs and checkpoints, plus the forecasts to fetch."""
    serializer = PlanRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return _error(_first_error(serializer.errors))
    data = serializer.validated_data
    try:
        origin = _resolve(data["origin"])
        destination = _resolve(data["destination"])
        if geo.haversine_mi(origin["lat"], origin["lon"], destination["lat"], destination["lon"]) < 1:
            return _error("Origin and destination must be at least a mile apart.")
        prepared = prepare_plan(
            origin=origin,
            destination=destination,
            departure=data["departure"],
            load_lb=data["load_weight_lb"],
            interval_mi=int(data["interval_mi"]),
        )
    except ExternalServiceError as exc:
        return _error(str(exc), status.HTTP_502_BAD_GATEWAY)
    return Response({"plan_id": _stash("plan", prepared), "weather": prepared.weather.spec()})


@api_view(["POST"])
def plan_score(request, plan_id: str):
    """Stage 2: forecasts from the browser → risk, recommendation, full plan."""
    prepared = cache.get(f"plan:{plan_id}")
    if prepared is None:
        return _error(EXPIRED, status.HTTP_404_NOT_FOUND)
    serializer = ForecastSerializer(data=request.data)
    if not serializer.is_valid():
        return _error(_first_error(serializer.errors))
    try:
        result = score_plan(prepared, serializer.validated_data["hourly"])
    except InvalidWeatherData as exc:
        return _error(f"Invalid forecast data: {exc}")
    return Response({"plan_id": plan_id, **result})


@api_view(["POST"])
def heatmap(request):
    """Stage 1: corridor grid around a prepared plan's routes, plus forecasts to fetch."""
    serializer = HeatmapRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return _error(_first_error(serializer.errors))
    prepared_plan = cache.get(f"plan:{serializer.validated_data['plan_id']}")
    if prepared_plan is None:
        return _error(EXPIRED, status.HTTP_404_NOT_FOUND)
    prepared = prepare_heatmap(
        [r.coords for r in prepared_plan.routes], prepared_plan.departure, prepared_plan.load_lb
    )
    return Response({"heatmap_id": _stash("heatmap", prepared), "weather": prepared.weather.spec()})


@api_view(["POST"])
def heatmap_score(request, heatmap_id: str):
    """Stage 2: forecasts from the browser → hourly corridor risk layers."""
    prepared = cache.get(f"heatmap:{heatmap_id}")
    if prepared is None:
        return _error(EXPIRED, status.HTTP_404_NOT_FOUND)
    serializer = ForecastSerializer(data=request.data)
    if not serializer.is_valid():
        return _error(_first_error(serializer.errors))
    try:
        result = score_heatmap(prepared, serializer.validated_data["hourly"])
    except InvalidWeatherData as exc:
        return _error(f"Invalid forecast data: {exc}")
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
