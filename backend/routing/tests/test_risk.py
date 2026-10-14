from django.test import SimpleTestCase

from routing.services.risk import RAIN, SNOW, WIND, Conditions, RiskLevel, assess

L = RiskLevel


class ThresholdTests(SimpleTestCase):
    def check(self, thresholds, cases):
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(thresholds.level(value), expected)

    def test_wind_bands(self):
        self.check(WIND, [
            (0, L.LOW), (24.9, L.LOW), (25, L.MODERATE), (34.9, L.MODERATE),
            (35, L.HIGH), (44.9, L.HIGH), (45, L.SEVERE), (54.9, L.SEVERE),
            (55, L.NO_TRAVEL), (80, L.NO_TRAVEL),
        ])

    def test_rain_bands(self):
        self.check(RAIN, [
            (0, L.LOW), (0.099, L.LOW), (0.10, L.MODERATE), (0.249, L.MODERATE),
            (0.25, L.HIGH), (0.49, L.HIGH), (0.50, L.SEVERE), (1.00, L.SEVERE),
            (1.01, L.NO_TRAVEL),
        ])

    def test_snow_bands(self):
        self.check(SNOW, [
            (0.49, L.LOW), (0.5, L.MODERATE), (1.0, L.HIGH), (2.0, L.SEVERE),
            (3.0, L.SEVERE), (3.01, L.NO_TRAVEL),
        ])

    def test_continuous_index_agrees_with_level(self):
        for t in (WIND, RAIN, SNOW):
            for i in range(0, 400):
                value = i * t.no_travel / 300
                with self.subTest(condition=t.name, value=value):
                    self.assertEqual(int(t.index(value)), t.level(value))


class LoadRuleTests(SimpleTestCase):
    def level(self, wind, load, rain=0.0, snow=0.0):
        return assess(Conditions(wind, rain, snow), load).level

    def test_55_mph_is_no_travel_for_any_load(self):
        self.assertEqual(self.level(55, 0), L.NO_TRAVEL)
        self.assertEqual(self.level(60, 10_000), L.NO_TRAVEL)

    def test_45_to_54_mph(self):
        self.assertEqual(self.level(45, 30_000), L.SEVERE)  # not *over* 30,000
        self.assertEqual(self.level(45, 30_001), L.NO_TRAVEL)
        self.assertEqual(self.level(54.9, 50_000), L.NO_TRAVEL)

    def test_35_to_44_mph(self):
        self.assertEqual(self.level(35, 40_000), L.HIGH)
        self.assertEqual(self.level(35, 40_001), L.SEVERE)
        self.assertEqual(self.level(44.9, 45_000), L.SEVERE)
        self.assertEqual(self.level(34.9, 79_000), L.MODERATE)  # rule doesn't apply

    def test_worst_condition_wins(self):
        self.assertEqual(self.level(10, 0, rain=0.3), L.HIGH)
        self.assertEqual(self.level(30, 0, rain=0.3, snow=2.5), L.SEVERE)

    def test_index_reflects_load_rule(self):
        result = assess(Conditions(36, 0, 0), 45_000)
        self.assertEqual(result.level, L.SEVERE)
        self.assertGreaterEqual(result.index, 3.0)
        self.assertLess(result.index, 4.0)
        self.assertTrue(any("40,000" in f for f in result.factors))
