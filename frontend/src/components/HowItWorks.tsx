import { LEVELS } from "../lib/risk";

const ROWS: [string, string[]][] = [
  ["Wind (mph)", ["<25", "25–34", "35–44", "45–54", "≥55"]],
  ["Rain (in/hr)", ["<0.10", "0.10–0.25", "0.25–0.50", "0.50–1.00", ">1.00"]],
  ["Snow (in/hr)", ["<0.5", "0.5–1.0", "1.0–2.0", "2.0–3.0", ">3.0"]],
];

/** In-app methodology: the rule table and how routes are ranked. */
export function HowItWorks({ maxSpeed }: { maxSpeed: number }) {
  return (
    <details className="how">
      <summary>How risk is scored</summary>
      <table className="rules">
        <thead>
          <tr>
            <th />
            {LEVELS.map((l) => (
              <th key={l.key}>
                <i style={{ background: l.color }} />
                {l.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([name, cells]) => (
            <tr key={name}>
              <th>{name}</th>
              {cells.map((c) => (
                <td key={c}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <ul>
        <li>
          <b>Load rules:</b> 45–54 mph with &gt;30,000 lb → No Travel; 35–44 mph with &gt;40,000 lb → Severe; ≥55 mph is
          No Travel for any load.
        </li>
        <li>
          <b>Checkpoints</b> are placed at the origin, every 10/25/50 mi, and the destination. Weather is taken from the
          hourly forecast at the truck's ETA there; each checkpoint's level applies to the road halfway to its neighbours.
        </li>
        <li>
          <b>ETAs</b> use OSRM road travel times with each segment capped at {maxSpeed} mph for a loaded truck.
        </li>
        <li>
          <b>Recommendation:</b> fewest No-Travel miles, then fewest Severe miles, fewest High miles, lowest
          distance-weighted average risk (Low 0 … No Travel 4), and finally shortest travel time.
        </li>
      </ul>
    </details>
  );
}
