import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type Checkpoint,
  type HeatLayerKey,
  type HeatmapResponse,
  type MetaResponse,
  type PlanRequest,
  type PlanResponse,
} from "./api";
import { ForecastControl, MAX_HOUR } from "./components/ForecastControl";
import { HowItWorks } from "./components/HowItWorks";
import { PlanForm } from "./components/PlanForm";
import { Recommendation, RouteCards } from "./components/RouteCards";
import { RouteDetail } from "./components/RouteDetail";
import { fmtDayTime, fmtLb } from "./lib/format";
import { fetchForecasts } from "./lib/openMeteo";
import { LEVELS } from "./lib/risk";
import { checkpointAtMile, truckPosition } from "./lib/route";
import { HeatField, type HeatSample } from "./map/heatField";
import { MapView } from "./map/MapView";

type Status = "idle" | "loading" | "ready" | "error";
const PLAYBACK_HOURS_PER_SECOND = 3;

export default function App() {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [planStatus, setPlanStatus] = useState<Status>("idle");
  const [planError, setPlanError] = useState<string | null>(null);
  const [progress, setProgress] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Checkpoint | null>(null);

  const [heat, setHeat] = useState<HeatmapResponse | null>(null);
  const [heatStatus, setHeatStatus] = useState<Status>("idle");
  const [heatError, setHeatError] = useState<string | null>(null);
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [layer, setLayer] = useState<HeatLayerKey | null>("risk");
  const [hover, setHover] = useState<(HeatSample & { x: number; y: number }) | null>(null);

  const planAbort = useRef<AbortController | null>(null);
  const heatAbort = useRef<AbortController | null>(null);

  const loadHeatmap = useCallback(async (p: PlanResponse) => {
    heatAbort.current?.abort();
    const controller = new AbortController();
    heatAbort.current = controller;
    setHeatStatus("loading");
    setHeatError(null);
    try {
      const { signal } = controller;
      const stage = await api.heatmap(p.plan_id, signal);
      const hourly = await fetchForecasts(stage.weather, signal);
      const result = await api.scoreHeatmap(stage.heatmap_id, { hourly }, signal);
      if (signal.aborted) return;
      setHeat(result);
      setHeatStatus("ready");
    } catch (e) {
      if (controller.signal.aborted) return;
      setHeatError((e as Error).message);
      setHeatStatus("error");
    }
  }, []);

  const runPlan = useCallback(
    async (req: PlanRequest) => {
      planAbort.current?.abort();
      heatAbort.current?.abort();
      const controller = new AbortController();
      planAbort.current = controller;
      setPlanStatus("loading");
      setPlanError(null);
      setProgress("Finding routes and timing checkpoints…");
      setPlaying(false);
      try {
        const { signal } = controller;
        const stage = await api.plan(req, signal);
        const total = stage.weather.locations.length;
        setProgress(`Downloading forecasts for ${total} checkpoints…`);
        const hourly = await fetchForecasts(stage.weather, signal, (done) =>
          setProgress(`Downloading forecasts at each ETA… ${done}/${total}`),
        );
        setProgress("Scoring weather risk…");
        const result = await api.scorePlan(stage.plan_id, { hourly }, signal);
        if (signal.aborted) return;
        setPlan(result);
        setSelectedId(result.recommendation.route_id);
        setHighlight(null);
        setHeat(null);
        setHour(0);
        setPlanStatus("ready");
        loadHeatmap(result);
      } catch (e) {
        if (controller.signal.aborted) return;
        setPlanError((e as Error).message);
        setPlanStatus("error");
      }
    },
    [loadHeatmap],
  );

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  // Forecast playback: advance the hour continuously; frames are blended.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setHour((h) => {
        const next = h + dt * PLAYBACK_HOURS_PER_SECOND;
        return next > MAX_HOUR ? 0 : next;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const field = useMemo(() => (heat && plan ? new HeatField(heat, plan.rules) : null), [heat, plan]);
  const selected = plan?.routes.find((r) => r.id === selectedId) ?? null;

  // Heatmap hour 0 is the departure hour (floored); trucks run on departure time.
  const heatOffsetS = useMemo(() => {
    if (!plan) return 0;
    const dep = new Date(plan.departure).getTime();
    const start = heat ? new Date(heat.start).getTime() : Math.floor(dep / 3600_000) * 3600_000;
    return (start - dep) / 1000;
  }, [plan, heat]);

  const elapsedS = hour * 3600 + heatOffsetS;
  const truck = selected ? truckPosition(selected, elapsedS) : null;
  const truckStatus = useMemo(() => {
    if (!selected || !truck || !plan) return null;
    if (truck.state === "waiting") return `Route ${selected.id} departs ${fmtDayTime(plan.departure)}`;
    if (truck.state === "arrived") return `Route ${selected.id} arrived ${fmtDayTime(selected.arrival)}`;
    const cp = checkpointAtMile(selected, truck.mile);
    return `Route ${selected.id} truck at mile ${Math.round(truck.mile)} · ${LEVELS[cp.level].label} risk on arrival`;
  }, [selected, truck, plan]);

  const onSelect = useCallback((id: string) => {
    setSelectedId(id);
    setHighlight(null);
  }, []);

  const hoverLevel = hover ? LEVELS[Math.min(4, Math.floor(hover.risk))] : null;

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="brand">
          <div className="logo" aria-hidden>
            <svg viewBox="0 0 32 32" width="34" height="34">
              <rect width="32" height="32" rx="9" fill="#0b3d4f" />
              <path d="M6 22c4-1 5-6 10-6s6 5 10 4" fill="none" stroke="#2dd4bf" strokeWidth="3" strokeLinecap="round" />
              <circle cx="6" cy="22" r="2.5" fill="#fff" />
              <circle cx="26" cy="20" r="2.5" fill="#f97316" />
              <path d="M19 6l-3 5h3l-2 4" fill="none" stroke="#facc15" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <h1>StormPath</h1>
            <p>Weather-aware truck routing</p>
          </div>
        </header>

        <PlanForm loading={planStatus === "loading"} hasPlan={!!plan} onSubmit={runPlan} />

        {planStatus === "loading" && (
          <div className="progress" role="status">
            <span className="spinner" />
            <div>
              <strong>{progress}</strong>
              <span>Routing and forecasts come from live public APIs; long trips can take ~15–30 s.</span>
            </div>
          </div>
        )}
        {planStatus === "error" && planError && (
          <div className="alert" role="alert">
            {planError}
          </div>
        )}

        {plan && (
          <div className={`results ${planStatus === "loading" ? "stale" : ""}`}>
            <div className="trip-line">
              <span>
                {plan.origin.label} → {plan.destination.label}
              </span>
              <span className="muted">
                Departs {fmtDayTime(plan.departure)} · {fmtLb(plan.load_weight_lb)} · every {plan.interval_mi} mi
              </span>
            </div>
            <Recommendation plan={plan} />
            <RouteCards plan={plan} selectedId={selectedId} onSelect={onSelect} />
            {selected && (
              <RouteDetail
                route={selected}
                highlight={highlight}
                onHighlight={setHighlight}
                truckMile={truck && truck.state === "driving" ? truck.mile : null}
              />
            )}
          </div>
        )}
        <HowItWorks maxSpeed={plan?.truck_max_speed_mph ?? 65} />
      </aside>

      <main className="map-area">
        <MapView
          basemap={meta?.basemap ?? null}
          plan={plan}
          selectedId={selectedId}
          onSelect={onSelect}
          highlight={highlight}
          field={field}
          heatLayer={layer}
          hour={hour}
          heatOffsetS={heatOffsetS}
          onHover={setHover}
        />
        {!plan && planStatus !== "loading" && (
          <div className="map-empty">
            <h2>Plan a trip to compare routes</h2>
            <p>
              Three route options, weather sampled at the truck's ETA at every checkpoint, risk scored with your load
              weight, and a 48-hour corridor forecast.
            </p>
          </div>
        )}
        {hover && hoverLevel && (
          <div className="hover-readout" style={{ left: hover.x + 16, top: hover.y + 16 }}>
            <div className="hr-head">
              <i style={{ background: hoverLevel.color }} /> {hoverLevel.label}
            </div>
            <div>Wind {hover.wind.toFixed(0)} mph</div>
            <div>Rain {hover.rain.toFixed(2)} in/hr</div>
            <div>Snow {hover.snow.toFixed(2)} in/hr</div>
          </div>
        )}
        {plan && (
          <ForecastControl
            heat={heat}
            status={heatStatus}
            error={heatError}
            onRetry={() => loadHeatmap(plan)}
            hour={hour}
            onHour={setHour}
            playing={playing}
            onPlaying={setPlaying}
            layer={layer}
            onLayer={setLayer}
            rules={plan.rules}
            loadLb={plan.load_weight_lb}
            truckStatus={truckStatus}
          />
        )}
      </main>
    </div>
  );
}
