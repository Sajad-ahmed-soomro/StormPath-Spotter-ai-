import { useState } from "react";
import type { Place, PlanRequest } from "../api";
import { nextHour, toLocalInput } from "../lib/format";
import { LocationInput } from "./LocationInput";

const INTERVALS = [10, 25, 50] as const;
const MAX_LOAD_LB = 120_000;

const EXAMPLES: { label: string; origin: Place; destination: Place }[] = [
  {
    label: "Chicago → Denver",
    origin: { label: "Chicago, IL", lat: 41.8781, lon: -87.6298 },
    destination: { label: "Denver, CO", lat: 39.7392, lon: -104.9903 },
  },
  {
    label: "Dallas → Atlanta",
    origin: { label: "Dallas, TX", lat: 32.7767, lon: -96.797 },
    destination: { label: "Atlanta, GA", lat: 33.749, lon: -84.388 },
  },
  {
    label: "Salt Lake City → Seattle",
    origin: { label: "Salt Lake City, UT", lat: 40.7608, lon: -111.891 },
    destination: { label: "Seattle, WA", lat: 47.6062, lon: -122.3321 },
  },
];

interface Props {
  loading: boolean;
  hasPlan: boolean;
  onSubmit: (request: PlanRequest) => void;
}

export function PlanForm({ loading, hasPlan, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place>({ label: "" });
  const [destination, setDestination] = useState<Place>({ label: "" });
  const [departure, setDeparture] = useState(() => toLocalInput(nextHour()));
  const [load, setLoad] = useState("42000");
  const [intervalMi, setIntervalMi] = useState<number>(25);
  const [error, setError] = useState<string | null>(null);

  const build = (overrides: Partial<{ origin: Place; destination: Place; interval: number }> = {}) => {
    const o = overrides.origin ?? origin;
    const d = overrides.destination ?? destination;
    if (!o.label.trim() || !d.label.trim()) return "Enter an origin and a destination.";
    const when = new Date(departure);
    if (Number.isNaN(when.getTime())) return "Enter a valid departure date and time.";
    const now = Date.now();
    if (when.getTime() < now - 3600_000) return "Departure can't be in the past.";
    if (when.getTime() > now + 7 * 86400_000) return "Departure must be within the next 7 days.";
    const weight = Number(load);
    if (!Number.isFinite(weight) || weight < 0 || weight > MAX_LOAD_LB) {
      return `Load weight must be between 0 and ${MAX_LOAD_LB.toLocaleString()} lb.`;
    }
    return {
      origin: o,
      destination: d,
      departure: when.toISOString(),
      load_weight_lb: weight,
      interval_mi: overrides.interval ?? intervalMi,
    } satisfies PlanRequest;
  };

  const submit = (overrides?: Parameters<typeof build>[0]) => {
    const result = build(overrides);
    if (typeof result === "string") {
      setError(result);
      return;
    }
    setError(null);
    onSubmit(result);
  };

  return (
    <form
      className="plan-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      noValidate
    >
      <div className="od">
        <LocationInput label="Origin" marker="A" value={origin} onChange={setOrigin} placeholder="City or address" />
        <button
          type="button"
          className="swap"
          title="Swap origin and destination"
          aria-label="Swap origin and destination"
          onClick={() => {
            setOrigin(destination);
            setDestination(origin);
          }}
        >
          ⇅
        </button>
        <LocationInput
          label="Destination"
          marker="B"
          value={destination}
          onChange={setDestination}
          placeholder="City or address"
        />
      </div>

      <div className="row">
        <div className="field">
          <label htmlFor="departure">Departure</label>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            onChange={(e) => setDeparture(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="load">Load weight</label>
          <div className="suffix-input">
            <input
              id="load"
              type="number"
              inputMode="numeric"
              min={0}
              max={MAX_LOAD_LB}
              step={500}
              value={load}
              onChange={(e) => setLoad(e.target.value)}
            />
            <span>lb</span>
          </div>
        </div>
      </div>

      <div className="field">
        <label id="interval-label">Weather checkpoint every</label>
        <div className="segmented" role="radiogroup" aria-labelledby="interval-label">
          {INTERVALS.map((mi) => (
            <button
              key={mi}
              type="button"
              role="radio"
              aria-checked={intervalMi === mi}
              className={intervalMi === mi ? "on" : ""}
              onClick={() => {
                setIntervalMi(mi);
                if (hasPlan && !loading) submit({ interval: mi });
              }}
            >
              {mi} mi
            </button>
          ))}
        </div>
      </div>

      {error && <div className="form-error">{error}</div>}

      <button type="submit" className="primary" disabled={loading}>
        {loading ? (
          <>
            <span className="spinner small light" /> Planning…
          </>
        ) : hasPlan ? (
          "Re-plan routes"
        ) : (
          "Plan safest route"
        )}
      </button>

      {!hasPlan && (
        <div className="examples">
          <span>Try:</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              type="button"
              className="chip"
              disabled={loading}
              onClick={() => {
                setOrigin(ex.origin);
                setDestination(ex.destination);
                submit({ origin: ex.origin, destination: ex.destination });
              }}
            >
              {ex.label}
            </button>
          ))}
        </div>
      )}
    </form>
  );
}
