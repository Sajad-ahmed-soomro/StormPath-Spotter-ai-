"""Staged plan/heatmap API flow with routing and reverse geocoding stubbed out."""

from datetime import datetime, timedelta
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from routing.services import geo, osrm, weather


def fake_routes(origin, destination):
    """Three straight-ish routes between the endpoints at ~60 mph."""
    routes = []
    for bend in (0.0, 0.3, -0.3):
        lat = np.linspace(origin[0], destination[0], 60)
        lon = np.linspace(origin[1], destination[1], 60)
        lat = lat + bend * np.sin(np.linspace(0, np.pi, 60))
        coords = np.column_stack([lat, lon])
        miles = geo.segment_lengths_mi(coords)
        routes.append(osrm.RawRoute(coords, miles / 60 * 3600, miles.sum(), miles.sum() * 60, "osrm"))
    return routes


def forecasts(spec: dict, wind: float = 10.0) -> list[dict]:
    params = spec["params"]
    span = datetime.fromisoformat(params["end_hour"]) - datetime.fromisoformat(params["start_hour"])
    hours = int(span.total_seconds() // 3600) + 1
    hourly = {name: [0.0] * hours for name in weather.HOURLY_VARS}
    hourly["wind_speed_10m"] = [wind] * hours
    return [hourly for _ in spec["locations"]]


@override_settings(ALLOWED_HOSTS=["testserver"])
@mock.patch("routing.services.planner._route_names", lambda routes: [None] * len(routes))
@mock.patch("routing.services.osrm.get_routes", side_effect=fake_routes)
class StagedFlowTests(SimpleTestCase):
    def plan_body(self, **overrides):
        body = {
            "origin": {"label": "Denver", "lat": 39.74, "lon": -104.99},
            "destination": {"label": "Kansas City", "lat": 39.10, "lon": -94.58},
            "departure": (timezone.now() + timedelta(hours=2)).isoformat(),
            "load_weight_lb": 42_000,
            "interval_mi": 50,
        }
        return {**body, **overrides}

    def test_plan_then_score_then_heatmap(self, _routes):
        stage1 = self.client.post("/api/plan/", self.plan_body(), content_type="application/json")
        self.assertEqual(stage1.status_code, 200, stage1.content)
        spec = stage1.json()["weather"]
        self.assertTrue(spec["url"].startswith("http"))
        self.assertGreater(len(spec["locations"]), 3)

        # 38 mph wind with a 42,000 lb load → Severe everywhere (load rule).
        stage2 = self.client.post(
            f"/api/plan/{stage1.json()['plan_id']}/score/",
            {"hourly": forecasts(spec, wind=38)},
            content_type="application/json",
        )
        self.assertEqual(stage2.status_code, 200, stage2.content)
        plan = stage2.json()
        self.assertEqual(len(plan["routes"]), 3)
        best = next(r for r in plan["routes"] if r["recommended"])
        self.assertEqual(best["id"], "A")  # all equally risky → fastest wins
        self.assertTrue(all(cp["level_label"] == "Severe" for cp in best["checkpoints"]))
        self.assertIn("Severe", plan["recommendation"]["warning"])

        heat1 = self.client.post("/api/heatmap/", {"plan_id": plan["plan_id"]}, content_type="application/json")
        self.assertEqual(heat1.status_code, 200, heat1.content)
        heat2 = self.client.post(
            f"/api/heatmap/{heat1.json()['heatmap_id']}/score/",
            {"hourly": forecasts(heat1.json()["weather"])},
            content_type="application/json",
        )
        self.assertEqual(heat2.status_code, 200, heat2.content)
        self.assertEqual(len(heat2.json()["layers"]["risk"]), 49)

    def test_rejects_mismatched_forecasts_and_unknown_plans(self, _routes):
        stage1 = self.client.post("/api/plan/", self.plan_body(), content_type="application/json").json()
        bad = self.client.post(
            f"/api/plan/{stage1['plan_id']}/score/",
            {"hourly": forecasts(stage1["weather"])[:-1]},
            content_type="application/json",
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Expected forecasts", bad.json()["error"])
        missing = self.client.post("/api/plan/deadbeef/score/", {"hourly": [{}]}, content_type="application/json")
        self.assertEqual(missing.status_code, 404)
