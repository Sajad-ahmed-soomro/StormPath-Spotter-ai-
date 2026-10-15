from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

INTERVAL_CHOICES = (10, 25, 50)
MAX_DEPARTURE_DAYS = 7
MAX_LOAD_LB = 120_000


class PlaceSerializer(serializers.Serializer):
    """A place picked from autocomplete (with coordinates) or free text to geocode."""

    label = serializers.CharField(max_length=200)
    lat = serializers.FloatField(min_value=-90, max_value=90, required=False)
    lon = serializers.FloatField(min_value=-180, max_value=180, required=False)

    def validate(self, attrs):
        if ("lat" in attrs) != ("lon" in attrs):
            raise serializers.ValidationError("Provide both lat and lon, or neither.")
        return attrs


def validate_departure(value):
    now = timezone.now()
    if value < now - timedelta(hours=1):
        raise serializers.ValidationError("Departure time cannot be in the past.")
    if value > now + timedelta(days=MAX_DEPARTURE_DAYS):
        raise serializers.ValidationError(
            f"Departure must be within the next {MAX_DEPARTURE_DAYS} days (forecast range)."
        )
    return value


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.DateTimeField(validators=[validate_departure])
    load_weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    interval_mi = serializers.ChoiceField(choices=INTERVAL_CHOICES, default=25)


class HeatmapRequestSerializer(serializers.Serializer):
    plan_id = serializers.CharField(max_length=64)


class ForecastSerializer(serializers.Serializer):
    """Open-Meteo ``hourly`` objects in the order of the spec's locations.

    Their contents are validated by ``weather.parse`` against the spec.
    """

    hourly = serializers.ListField(child=serializers.DictField(), min_length=1, max_length=5000)
