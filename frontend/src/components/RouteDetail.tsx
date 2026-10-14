import { memo } from "react";
import type { Checkpoint, RouteOption } from "../api";
import { fmtDayTime, localTzName } from "../lib/format";
import { LEVELS, levelColor } from "../lib/risk";

interface Props {
  route: RouteOption;
  highlight: Checkpoint | null;
  onHighlight: (cp: Checkpoint | null) => void;
  /** Truck's current mile on the forecast timeline (for the profile cursor). */
  truckMile: number | null;
}

/** Risk profile strip + full checkpoint table for the selected route. */
export function RouteDetail({ route, highlight, onHighlight, truckMile }: Props) {
  return (
    <section className="route-detail">
      <h3 className="section-title">
        {route.name} · {route.checkpoints.length} checkpoints
      </h3>
      <RiskProfile route={route} highlight={highlight} onHighlight={onHighlight} truckMile={truckMile} />
      <CheckpointTable route={route} highlight={highlight} onHighlight={onHighlight} />
    </section>
  );
}

function RiskProfile({ route, highlight, onHighlight, truckMile }: Props) {
  const total = route.distance_mi || 1;
  const pct = (mi: number) => `${(mi / total) * 100}%`;
  const hours = Math.floor(route.duration_h);
  const step = hours > 36 ? 12 : hours > 12 ? 6 : hours > 4 ? 2 : 1;
  const ticks = [];
  for (let h = step; h < route.duration_h; h += step) {
    const cp = route.checkpoints.find((c) => c.elapsed_h >= h);
    if (cp) ticks.push({ h, mile: cp.mile });
  }
  return (
    <div className="profile" onMouseLeave={() => onHighlight(null)}>
      <div className="profile-strip">
        {route.checkpoints.map((cp) => (
          <span
            key={cp.index}
            className={highlight?.index === cp.index ? "hl" : ""}
            style={{
              left: pct(cp.covers_mi[0]),
              width: pct(cp.covers_mi[1] - cp.covers_mi[0]),
              background: levelColor(cp.level),
            }}
            onMouseEnter={() => onHighlight(cp)}
          />
        ))}
        {truckMile !== null && <i className="profile-truck" style={{ left: pct(truckMile) }} />}
      </div>
      <div className="profile-axis">
        <span>0 mi</span>
        {ticks.map((t) => (
          <span key={t.h} className="tick" style={{ left: pct(t.mile) }}>
            {t.h}h
          </span>
        ))}
        <span>{Math.round(total)} mi</span>
      </div>
    </div>
  );
}

const CheckpointTable = memo(function CheckpointTable({
  route,
  highlight,
  onHighlight,
}: Omit<Props, "truckMile">) {
  return (
    <div className="cp-table-wrap">
      <table className="cp-table">
        <thead>
          <tr>
            <th>Mile</th>
            <th>ETA ({localTzName})</th>
            <th>Wind</th>
            <th>Rain</th>
            <th>Snow</th>
            <th>Risk</th>
          </tr>
        </thead>
        <tbody>
          {route.checkpoints.map((cp) => {
            const w = cp.weather;
            const lvl = LEVELS[cp.level];
            return (
              <tr
                key={cp.index}
                className={highlight?.index === cp.index ? "hl" : ""}
                onMouseEnter={() => onHighlight(cp)}
                onMouseLeave={() => onHighlight(null)}
                title={cp.factors.join("\n") || w.description}
              >
                <td className="num">{Math.round(cp.mile)}</td>
                <td>{fmtDayTime(cp.eta)}</td>
                <td className="num">
                  {w.wind_mph.toFixed(0)}
                  <small> mph</small>
                </td>
                <td className="num">{w.rain_in_hr.toFixed(2)}</td>
                <td className="num">{w.snow_in_hr.toFixed(2)}</td>
                <td>
                  <span className="pill" style={{ background: lvl.color, color: lvl.text }}>
                    {lvl.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
});
