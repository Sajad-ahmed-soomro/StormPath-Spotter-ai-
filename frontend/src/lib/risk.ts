import type { ConditionThresholds, HeatLayerKey, LevelKey } from "../api";

export const LEVELS: { key: LevelKey; label: string; color: string; text: string }[] = [
  { key: "low", label: "Low", color: "#22c55e", text: "#052e16" },
  { key: "moderate", label: "Moderate", color: "#eab308", text: "#422006" },
  { key: "high", label: "High", color: "#f97316", text: "#431407" },
  { key: "severe", label: "Severe", color: "#dc2626", text: "#ffffff" },
  { key: "no_travel", label: "No Travel", color: "#7e22ce", text: "#ffffff" },
];

export const levelColor = (level: number) => LEVELS[Math.max(0, Math.min(4, Math.round(level)))].color;

/**
 * Raw value → continuous 0–4 index, linear within each band.
 * Mirrors ``Thresholds.index`` on the backend; used only to colour the raw
 * wind/rain/snow heatmap layers (the risk layer arrives pre-computed).
 */
export function valueToIndex(value: number, t: ConditionThresholds): number {
  const stops = [0, t.moderate, t.high, t.severe, t.no_travel];
  const atTop = t.no_travel_inclusive ? value >= t.no_travel : value > t.no_travel;
  if (atTop) return 4;
  for (let level = 3; level >= 0; level--) {
    if (value >= stops[level]) {
      const span = stops[level + 1] - stops[level];
      return level + Math.min(0.999, span > 0 ? (value - stops[level]) / span : 0);
    }
  }
  return 0;
}

type RGB = [number, number, number];

const hexToRgb = (hex: string): RGB => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
];

const STOPS = LEVELS.map((l) => hexToRgb(l.color));

/**
 * 256-entry RGBA lookup table over the 0–4 index. Calm weather is nearly
 * transparent so the basemap stays readable; opacity rises with risk.
 */
export const RISK_LUT: Uint8ClampedArray = (() => {
  const lut = new Uint8ClampedArray(256 * 4);
  for (let i = 0; i < 256; i++) {
    const x = (i / 255) * 4;
    const lo = Math.min(3, Math.floor(x));
    const f = x - lo;
    const a = STOPS[lo];
    const b = STOPS[lo + 1];
    lut[i * 4] = a[0] + (b[0] - a[0]) * f;
    lut[i * 4 + 1] = a[1] + (b[1] - a[1]) * f;
    lut[i * 4 + 2] = a[2] + (b[2] - a[2]) * f;
    // 0 → 0.10, 1 → 0.42, 2+ → up to 0.78 alpha
    const alpha = x < 1 ? 0.1 + 0.32 * x : Math.min(0.78, 0.42 + 0.12 * (x - 1));
    lut[i * 4 + 3] = alpha * 255;
  }
  return lut;
})();

export const HEAT_LAYERS: { key: HeatLayerKey; label: string; unit: string }[] = [
  { key: "risk", label: "Risk", unit: "" },
  { key: "wind", label: "Wind", unit: "mph" },
  { key: "rain", label: "Rain", unit: "in/hr" },
  { key: "snow", label: "Snow", unit: "in/hr" },
];
