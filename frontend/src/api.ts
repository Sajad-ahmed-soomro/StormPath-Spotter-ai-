/** Typed client for the Django API. Shapes mirror backend/routing/services. */

export type LevelKey = "low" | "moderate" | "high" | "severe" | "no_travel";

export interface Place {
  label: string;
  lat?: number;
  lon?: number;
}

export interface ResolvedPlace {
  label: string;
  lat: number;
  lon: number;
}

export interface ConditionThresholds {
  name: "wind" | "rain" | "snow";
  unit: string;
  moderate: number;
  high: number;
  severe: number;
  no_travel: number;
  no_travel_inclusive: boolean;
}

export interface Rules {
  levels: { value: number; key: LevelKey; label: string }[];
  conditions: ConditionThresholds[];
}

export interface Weather {
  wind_mph: number;
  gust_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
  temp_f: number;
  weather_code: number;
  description: string;
}

export interface Checkpoint {
  index: number;
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  elapsed_h: number;
  covers_mi: [number, number];
  weather: Weather;
  level: number;
  level_label: string;
  index_value: number;
  factors: string[];
}

export interface RouteOption {
  id: string;
  name: string;
  via: string | null;
  source: "osrm" | "via";
  distance_mi: number;
  duration_h: number;
  extra_minutes: number;
  arrival: string;
  risk: {
    miles_by_level: Record<LevelKey, number>;
    avg_risk: number;
    max_level: number;
  };
  path: [number, number][];
  path_elapsed_s: number[];
  segments: { level: number; coords: [number, number][] }[];
  checkpoints: Checkpoint[];
  rank: number;
  recommended: boolean;
}

export interface PlanResponse {
  plan_id: string;
  origin: ResolvedPlace;
  destination: ResolvedPlace;
  departure: string;
  load_weight_lb: number;
  interval_mi: number;
  truck_max_speed_mph: number;
  routes: RouteOption[];
  recommendation: { route_id: string; reasons: string[]; warning: string | null };
  rules: Rules;
}

export type HeatLayerKey = "risk" | "wind" | "rain" | "snow";

export interface HeatmapResponse {
  start: string;
  hours: string[];
  grid: {
    nx: number;
    ny: number;
    bounds: { west: number; east: number; north: number; south: number };
    spacing_mi: number;
    buffer_mi: number;
    cells: number[];
    weights: number[];
  };
  layers: Record<HeatLayerKey, number[][]>;
}

/** What the browser must download from Open-Meteo for a stage (decided by the backend). */
export interface WeatherSpec {
  url: string;
  batch_size: number;
  locations: [number, number][];
  params: Record<string, string>;
}

export interface PlanStage {
  plan_id: string;
  weather: WeatherSpec;
}

export interface HeatmapStage {
  heatmap_id: string;
  weather: WeatherSpec;
}

type Forecasts = { hourly: Record<string, unknown>[] };

export interface MetaResponse {
  rules: Rules;
  truck_max_speed_mph: number;
  basemap: { url: string; labels_url: string };
}

export interface PlanRequest {
  origin: Place;
  destination: Place;
  departure: string;
  load_weight_lb: number;
  interval_mi: number;
}

// Backend origin, set at build time (Vercel env). Empty = same origin.
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new Error("Cannot reach the server. Check your connection and try again.");
  }
  const body = await resp.json().catch(() => null);
  if (!resp.ok) {
    throw new Error(body?.error ?? `Request failed (${resp.status})`);
  }
  return body as T;
}

export const api = {
  meta: () => request<MetaResponse>("/api/meta/"),
  geocode: (q: string, signal?: AbortSignal) =>
    request<{ results: (ResolvedPlace & { type?: string })[] }>(
      `/api/geocode/?q=${encodeURIComponent(q)}`,
      { signal },
    ),
  /** Stage 1: routes, ETAs, checkpoints → which forecasts to fetch. */
  plan: (body: PlanRequest, signal?: AbortSignal) =>
    request<PlanStage>("/api/plan/", { method: "POST", body: JSON.stringify(body), signal }),
  /** Stage 2: forecasts → risk, recommendation, full plan. */
  scorePlan: (planId: string, body: Forecasts, signal?: AbortSignal) =>
    request<PlanResponse>(`/api/plan/${planId}/score/`, { method: "POST", body: JSON.stringify(body), signal }),
  heatmap: (planId: string, signal?: AbortSignal) =>
    request<HeatmapStage>("/api/heatmap/", { method: "POST", body: JSON.stringify({ plan_id: planId }), signal }),
  scoreHeatmap: (heatmapId: string, body: Forecasts, signal?: AbortSignal) =>
    request<HeatmapResponse>(`/api/heatmap/${heatmapId}/score/`, {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    }),
};
