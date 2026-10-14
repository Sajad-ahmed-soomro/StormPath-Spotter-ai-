import type { PlanResponse, RouteOption } from "../api";
import { fmtDayTime, fmtDuration, fmtMiles } from "../lib/format";
import { LEVELS } from "../lib/risk";
import { ROUTE_COLORS } from "../map/MapView";

interface Props {
  plan: PlanResponse;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function Recommendation({ plan }: { plan: PlanResponse }) {
  const rec = plan.recommendation;
  const route = plan.routes.find((r) => r.id === rec.route_id)!;
  return (
    <section className={`recommendation ${rec.warning ? "has-warning" : ""}`}>
      <div className="rec-head">
        <span className="rec-badge">★ Recommended</span>
        <h2>{route.name}</h2>
      </div>
      <div className="rec-meta">
        {fmtMiles(route.distance_mi)} · {fmtDuration(route.duration_h)} · arrives {fmtDayTime(route.arrival)}
      </div>
      {rec.reasons.length > 0 && (
        <ul className="rec-reasons">
          {rec.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {rec.warning && <div className="rec-warning">⚠ {rec.warning}</div>}
      {plan.routes.length < 3 && (
        <div className="rec-note">Only {plan.routes.length} distinct route(s) exist for this trip.</div>
      )}
    </section>
  );
}

export function RiskBar({ route, height = 8 }: { route: RouteOption; height?: number }) {
  const total = route.distance_mi || 1;
  return (
    <div className="risk-bar" style={{ height }} aria-label="Miles by risk level">
      {LEVELS.map((l) => {
        const mi = route.risk.miles_by_level[l.key];
        return mi > 0 ? (
          <span
            key={l.key}
            style={{ width: `${(mi / total) * 100}%`, background: l.color }}
            title={`${l.label}: ${fmtMiles(mi)}`}
          />
        ) : null;
      })}
    </div>
  );
}

export function RouteCards({ plan, selectedId, onSelect }: Props) {
  const ranked = [...plan.routes].sort((a, b) => a.rank - b.rank);
  return (
    <section className="route-cards">
      <h3 className="section-title">Route options</h3>
      {ranked.map((r) => {
        const m = r.risk.miles_by_level;
        return (
          <button
            key={r.id}
            type="button"
            className={`route-card ${r.id === selectedId ? "selected" : ""}`}
            style={{ "--route": ROUTE_COLORS[r.id] } as React.CSSProperties}
            onClick={() => onSelect(r.id)}
            aria-pressed={r.id === selectedId}
          >
            <div className="rc-top">
              <span className="rc-id">{r.id}</span>
              <span className="rc-name">{r.via ? `via ${r.via}` : r.name}</span>
              {r.recommended && <span className="tag tag-rec">★ Best</span>}
              {r.extra_minutes === 0 && <span className="tag">Fastest</span>}
            </div>
            <div className="rc-stats">
              <div>
                <strong>{fmtDuration(r.duration_h)}</strong>
                <span>{r.extra_minutes > 0 ? `+${fmtDuration(r.extra_minutes / 60)}` : "drive time"}</span>
              </div>
              <div>
                <strong>{fmtMiles(r.distance_mi)}</strong>
                <span>distance</span>
              </div>
              <div>
                <strong>{fmtDayTime(r.arrival)}</strong>
                <span>arrival</span>
              </div>
            </div>
            <RiskBar route={r} />
            <div className="rc-risk">
              <span className={m.no_travel > 0 ? "bad" : ""}>No-travel {fmtMiles(m.no_travel)}</span>
              <span className={m.severe > 0 ? "bad" : ""}>Severe {fmtMiles(m.severe)}</span>
              <span className={m.high > 0 ? "warn" : ""}>High {fmtMiles(m.high)}</span>
              <span>Avg risk {r.risk.avg_risk.toFixed(2)}</span>
            </div>
          </button>
        );
      })}
    </section>
  );
}
