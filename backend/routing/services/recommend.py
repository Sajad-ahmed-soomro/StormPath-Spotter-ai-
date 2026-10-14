"""Route ranking.

The assessment's preference order is applied lexicographically:

  1. fewest Severe miles
  2. fewest High miles
  3. lowest average risk (distance-weighted, Low=0 … No Travel=4)
  4. shortest travel time

No Travel is strictly worse than Severe, so "No Travel" miles are compared
first: a route that crosses a No-Travel zone can never beat one that doesn't.
Distances are compared at 0.1 mi and average risk at 0.01 resolution so that
floating-point noise never decides between two effectively equal routes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskSummary:
    route_id: str
    no_travel_mi: float
    severe_mi: float
    high_mi: float
    avg_risk: float
    duration_s: float


CRITERIA = (
    ("no_travel_mi", "No-Travel miles"),
    ("severe_mi", "Severe miles"),
    ("high_mi", "High-risk miles"),
    ("avg_risk", "average risk"),
    ("duration_s", "travel time"),
)


def sort_key(s: RiskSummary) -> tuple:
    return (
        round(s.no_travel_mi, 1),
        round(s.severe_mi, 1),
        round(s.high_mi, 1),
        round(s.avg_risk, 2),
        round(s.duration_s),
    )


def rank(summaries: list[RiskSummary]) -> list[RiskSummary]:
    """Best route first."""
    return sorted(summaries, key=sort_key)


def _fmt(attr: str, value: float) -> str:
    if attr == "duration_s":
        hours, minutes = divmod(round(value / 60), 60)
        return f"{hours}h {minutes:02d}m"
    if attr == "avg_risk":
        return f"{value:.2f}"
    return f"{value:,.0f} mi" if value >= 10 else f"{value:.1f} mi"


def deciding_criterion(best: RiskSummary, other: RiskSummary) -> tuple[str, str] | None:
    """The first criterion on which ``best`` beats ``other`` and a sentence explaining it.

    Every criterion before the deciding one is tied by construction.
    """
    for (attr, label), b, o in zip(CRITERIA, sort_key(best), sort_key(other)):
        if b == o:
            continue
        values = f"({_fmt(attr, getattr(best, attr))} vs {_fmt(attr, getattr(other, attr))})"
        if attr == "duration_s":
            return attr, f"Same weather risk as Route {other.route_id} but faster {values}"
        if attr == "avg_risk":
            return attr, f"Lower average risk than Route {other.route_id} {values}"
        return attr, f"Fewer {label} than Route {other.route_id} {values}"
    return None


def explain(ranked: list[RiskSummary]) -> dict:
    best = ranked[0]
    reasons = []
    for other in ranked[1:]:
        decided = deciding_criterion(best, other)
        reasons.append(
            decided[1] if decided else f"Identical risk and time to Route {other.route_id}"
        )

    warning = None
    if best.no_travel_mi > 0:
        warning = (
            f"Every option crosses No-Travel conditions (best: {best.no_travel_mi:.0f} mi). "
            "Consider delaying departure — use the forecast slider to find a safer window."
        )
    elif best.severe_mi > 0:
        warning = f"The recommended route still has {best.severe_mi:.0f} mi of Severe conditions."

    return {"route_id": best.route_id, "reasons": reasons, "warning": warning}
