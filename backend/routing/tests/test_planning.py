from datetime import datetime, timedelta, timezone

import numpy as np
from django.test import SimpleTestCase

from routing.services import geo, heatmap, osrm
from routing.services.planner import (
    TimedRoute,
    build_checkpoints,
    checkpoint_miles,
    coverage,
    risk_miles,
    truck_timed,
)
from routing.services.risk import RiskLevel
from routing.services.weather import HourlySeries, fetch_window

DEPART = datetime(2026, 1, 5, 8, 30, tzinfo=timezone.utc)


def straight_route(miles: float, mph: float = 60.0) -> TimedRoute:
    """A due-east route along the equator (1° lon ≈ 69.1 mi) at constant speed."""
    lon_end = miles / (geo.EARTH_RADIUS_MI * np.pi / 180)
    coords = np.column_stack([np.zeros(101), np.linspace(0, lon_end, 101)])
    cum_mi = geo.cumulative(geo.segment_lengths_mi(coords))
    return TimedRoute(coords=coords, cum_mi=cum_mi, cum_s=cum_mi / mph * 3600, source="test")


class CheckpointTests(SimpleTestCase):
    def test_sampling_includes_origin_interval_and_destination(self):
        np.testing.assert_allclose(checkpoint_miles(105, 25), [0, 25, 50, 75, 100, 105])
        np.testing.assert_allclose(checkpoint_miles(100, 50), [0, 50, 100])
        np.testing.assert_allclose(checkpoint_miles(8, 10), [0, 8])

    def test_coverage_partitions_the_route(self):
        miles = checkpoint_miles(105, 25)
        starts, ends = coverage(miles)
        self.assertAlmostEqual(float((ends - starts).sum()), 105)
        np.testing.assert_allclose(starts[1:], ends[:-1])

    def test_eta_follows_travel_time(self):
        route = straight_route(120, mph=60)
        cps = build_checkpoints(route, 10, DEPART)
        self.assertEqual(len(cps), 13)
        self.assertAlmostEqual(cps[6].mile, 60, places=6)
        self.assertAlmostEqual((cps[6].eta - DEPART).total_seconds(), 3600, delta=1)
        self.assertAlmostEqual(cps[6].lat, 0, places=6)

    def test_risk_miles_sum_to_route_length(self):
        cps = build_checkpoints(straight_route(100), 25, DEPART)
        cps[2].level = RiskLevel.SEVERE
        by_level = risk_miles(cps)
        self.assertAlmostEqual(sum(by_level.values()), 100, places=6)
        self.assertAlmostEqual(by_level[RiskLevel.SEVERE], 25, places=6)

    def test_truck_speed_cap(self):
        coords = np.array([[0.0, 0.0], [0.0, 1.0]])  # ~69 mi
        raw = osrm.RawRoute(coords, np.array([3600.0 * 69.1 / 80]), 69.1, 3105, "test")
        timed = truck_timed(raw, max_speed_mph=65)
        self.assertAlmostEqual(timed.duration_s / 3600, timed.distance_mi / 65, places=4)


class WeatherSamplingTests(SimpleTestCase):
    def series(self):
        n = 6
        return HourlySeries(
            start=datetime(2026, 1, 5, 6, tzinfo=timezone.utc),
            wind=np.array([10, 20, 30, 40, 50, 60], float),
            gust=np.zeros(n),
            rain=np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5]),
            snow=np.zeros(n),
            temp=np.zeros(n),
            code=np.zeros(n),
        )

    def test_wind_is_interpolated_and_precip_uses_containing_hour(self):
        wx = self.series().at(DEPART)  # 08:30 → between 08:00 (30) and 09:00 (40)
        self.assertAlmostEqual(wx["wind_mph"], 35.0)
        # Precip stamped 09:00 is the accumulation for 08:00–09:00.
        self.assertAlmostEqual(wx["rain_in_hr"], 0.3)

    def test_fetch_window_is_aligned_and_covers_request(self):
        start, hours = fetch_window(DEPART, 30)
        self.assertEqual(start, datetime(2026, 1, 5, 6, tzinfo=timezone.utc))
        self.assertGreaterEqual(start + timedelta(hours=hours), DEPART + timedelta(hours=30))
        self.assertEqual(hours % 24, 0)


class GeometryTests(SimpleTestCase):
    def test_decode_polyline6(self):
        coords = geo.decode_polyline("_izlhA~rlgdF_{geC~ywl@_kwzCn`{nI", precision=6)
        np.testing.assert_allclose(coords, [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])

    def test_simplify_keeps_endpoints_and_drops_collinear(self):
        line = np.column_stack([np.linspace(0, 1, 50), np.linspace(0, 1, 50)])
        self.assertEqual(geo.simplify(line, 1e-6).tolist(), [0, 49])

    def test_overlap_ratio(self):
        a = straight_route(100).coords
        b = a.copy()
        b[:, 0] += 1.0  # shifted ~69 mi north
        self.assertGreater(osrm.overlap_ratio(a, a), 0.99)
        self.assertLess(osrm.overlap_ratio(a, b), 0.01)

    def test_heatmap_grid_is_bounded_and_mercator_aligned(self):
        path = np.array([[41.88, -87.63], [41.25, -95.99], [39.74, -104.99]])
        grid = heatmap.corridor_grid([path])
        self.assertLessEqual(len(grid["cells"]), heatmap.MAX_CELLS)
        self.assertGreater(len(grid["cells"]), 50)
        b = grid["bounds"]
        self.assertLess(b["south"], 39.74)
        self.assertGreater(b["north"], 41.88)
        # Cells are equally spaced in Mercator y.
        lat = grid["points"][:, 0].reshape(-1)
        ys = np.unique(np.round(geo.lat_to_mercator_y(lat), 9))
        self.assertTrue(np.allclose(np.diff(ys), np.diff(ys)[0], rtol=1e-6))
