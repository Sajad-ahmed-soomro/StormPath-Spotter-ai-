from django.test import SimpleTestCase

from routing.services.recommend import RiskSummary, explain, rank


def summary(rid, no_travel=0.0, severe=0.0, high=0.0, avg=0.0, hours=10.0):
    return RiskSummary(rid, no_travel, severe, high, avg, hours * 3600)


class RankingTests(SimpleTestCase):
    def ids(self, *summaries):
        return [s.route_id for s in rank(list(summaries))]

    def test_fewest_severe_miles_beats_everything_else(self):
        self.assertEqual(
            self.ids(summary("A", severe=10, hours=8), summary("B", severe=0, high=200, avg=2, hours=14)),
            ["B", "A"],
        )

    def test_high_miles_break_severe_ties(self):
        self.assertEqual(
            self.ids(summary("A", severe=5, high=40), summary("B", severe=5, high=10, hours=12)),
            ["B", "A"],
        )

    def test_average_risk_then_time(self):
        self.assertEqual(self.ids(summary("A", avg=0.4), summary("B", avg=0.2, hours=11)), ["B", "A"])
        self.assertEqual(self.ids(summary("A", hours=11), summary("B", hours=9)), ["B", "A"])

    def test_no_travel_is_worse_than_severe(self):
        self.assertEqual(self.ids(summary("A", no_travel=5), summary("B", severe=300)), ["B", "A"])

    def test_float_noise_does_not_decide(self):
        self.assertEqual(
            self.ids(summary("A", high=10.00001, hours=9), summary("B", high=10.0, hours=10)),
            ["A", "B"],
        )

    def test_explanations_name_the_deciding_criterion(self):
        ranked = rank([summary("A", hours=9), summary("B", severe=12), summary("C", avg=0.5), summary("D")])
        self.assertEqual([s.route_id for s in ranked], ["A", "D", "C", "B"])
        result = explain(ranked)
        self.assertEqual(result["route_id"], "A")
        self.assertEqual(len(result["reasons"]), 3)
        self.assertIn("Same weather risk as Route D but faster", result["reasons"][0])
        self.assertIn("Lower average risk than Route C", result["reasons"][1])
        self.assertIn("Fewer Severe miles than Route B", result["reasons"][2])
        self.assertIsNone(result["warning"])

    def test_warning_when_all_routes_hit_no_travel(self):
        result = explain(rank([summary("A", no_travel=20), summary("B", no_travel=40)]))
        self.assertIn("No-Travel", result["warning"])
