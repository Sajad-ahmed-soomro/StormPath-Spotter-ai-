import type { HeatLayerKey, HeatmapResponse, Rules } from "../api";
import { fmtDayTime } from "../lib/format";
import { HEAT_LAYERS, LEVELS } from "../lib/risk";

interface Props {
  heat: HeatmapResponse | null;
  status: "idle" | "loading" | "ready" | "error";
  error: string | null;
  onRetry: () => void;
  hour: number;
  onHour: (h: number) => void;
  playing: boolean;
  onPlaying: (p: boolean) => void;
  layer: HeatLayerKey | null;
  onLayer: (l: HeatLayerKey | null) => void;
  rules: Rules;
  loadLb: number;
  truckStatus: string | null;
}

export const MAX_HOUR = 48;

export function ForecastControl(props: Props) {
  const { heat, status, hour, layer } = props;
  const hourStart = heat ? new Date(heat.start) : null;
  const current = hourStart ? new Date(hourStart.getTime() + hour * 3600_000) : null;
  const ticks = [0, 6, 12, 18, 24, 30, 36, 42, 48];

  return (
    <div className="forecast" role="region" aria-label="Forecast timeline">
      <div className="fc-row">
        <button
          type="button"
          className="play"
          disabled={status !== "ready"}
          onClick={() => props.onPlaying(!props.playing)}
          aria-label={props.playing ? "Pause forecast animation" : "Play forecast animation"}
        >
          {props.playing ? "❚❚" : "▶"}
        </button>
        <div className="fc-time">
          <strong>T+{Math.floor(hour)}h</strong>
          <span>{current ? fmtDayTime(current) : "—"}</span>
        </div>
        <div className="fc-layers segmented small" role="radiogroup" aria-label="Heatmap layer">
          {HEAT_LAYERS.map((l) => (
            <button
              key={l.key}
              type="button"
              role="radio"
              aria-checked={layer === l.key}
              className={layer === l.key ? "on" : ""}
              onClick={() => props.onLayer(l.key)}
            >
              {l.label}
            </button>
          ))}
          <button
            type="button"
            role="radio"
            aria-checked={layer === null}
            className={layer === null ? "on" : ""}
            onClick={() => props.onLayer(null)}
          >
            Off
          </button>
        </div>
      </div>

      <div className="fc-slider">
        <input
          type="range"
          min={0}
          max={MAX_HOUR}
          step={0.25}
          value={hour}
          disabled={status !== "ready"}
          onChange={(e) => {
            props.onPlaying(false);
            props.onHour(Number(e.target.value));
          }}
          aria-label="Forecast hour"
          aria-valuetext={current ? `${Math.floor(hour)} hours, ${fmtDayTime(current)}` : undefined}
          style={{ "--fill": `${(hour / MAX_HOUR) * 100}%` } as React.CSSProperties}
        />
        <div className="fc-ticks">
          {ticks.map((t) => (
            <span key={t} style={{ left: `${(t / MAX_HOUR) * 100}%` }}>
              {t === 0 ? "Depart" : `${t}h`}
            </span>
          ))}
        </div>
      </div>

      <div className="fc-foot">
        {status === "loading" && (
          <span className="fc-status">
            <span className="spinner small" /> Loading corridor forecast…
          </span>
        )}
        {status === "error" && (
          <span className="fc-status error">
            {props.error}{" "}
            <button type="button" className="link" onClick={props.onRetry}>
              Retry
            </button>
          </span>
        )}
        {status === "ready" && layer && <Legend layer={layer} rules={props.rules} loadLb={props.loadLb} />}
        {status === "ready" && props.truckStatus && <span className="fc-truck">🚚 {props.truckStatus}</span>}
      </div>
    </div>
  );
}

function Legend({ layer, rules, loadLb }: { layer: HeatLayerKey; rules: Rules; loadLb: number }) {
  const gradient = `linear-gradient(90deg, ${LEVELS.map((l, i) => `${l.color} ${i * 25}%`).join(", ")})`;
  let labels: string[];
  let caption: string;
  if (layer === "risk") {
    labels = LEVELS.map((l) => l.label);
    caption = `Worst of wind/rain/snow, with load rules for ${loadLb.toLocaleString()} lb`;
  } else {
    const t = rules.conditions.find((c) => c.name === layer)!;
    labels = ["0", t.moderate, t.high, t.severe, t.no_travel].map(String);
    caption = layer === "wind" ? "Sustained wind, mph" : `${layer === "rain" ? "Rain" : "Snowfall"}, in/hr`;
  }
  return (
    <div className="legend">
      <div className="legend-bar" style={{ background: gradient }} />
      <div className="legend-labels">
        {labels.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
      </div>
      <div className="legend-caption">{caption}</div>
    </div>
  );
}
