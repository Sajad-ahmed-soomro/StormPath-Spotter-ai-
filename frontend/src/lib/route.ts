import type { RouteOption } from "../api";

export interface TruckPosition {
  lat: number;
  lon: number;
  mile: number;
  state: "waiting" | "driving" | "arrived";
}

/** Where the truck is ``elapsedS`` seconds after departure (binary search + lerp). */
export function truckPosition(route: RouteOption, elapsedS: number): TruckPosition {
  const t = route.path_elapsed_s;
  const p = route.path;
  const last = p.length - 1;
  if (elapsedS <= 0) return { lat: p[0][0], lon: p[0][1], mile: 0, state: "waiting" };
  if (elapsedS >= t[last]) {
    return { lat: p[last][0], lon: p[last][1], mile: route.distance_mi, state: "arrived" };
  }
  let lo = 0;
  let hi = last;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (t[mid] <= elapsedS) lo = mid;
    else hi = mid;
  }
  const f = t[hi] > t[lo] ? (elapsedS - t[lo]) / (t[hi] - t[lo]) : 0;
  return {
    lat: p[lo][0] + (p[hi][0] - p[lo][0]) * f,
    lon: p[lo][1] + (p[hi][1] - p[lo][1]) * f,
    mile: milesAtElapsed(route, elapsedS),
    state: "driving",
  };
}

/** Mile marker at a given elapsed time, interpolated between checkpoints. */
function milesAtElapsed(route: RouteOption, elapsedS: number): number {
  const cps = route.checkpoints;
  const h = elapsedS / 3600;
  for (let i = 1; i < cps.length; i++) {
    if (cps[i].elapsed_h >= h) {
      const a = cps[i - 1];
      const b = cps[i];
      const f = b.elapsed_h > a.elapsed_h ? (h - a.elapsed_h) / (b.elapsed_h - a.elapsed_h) : 0;
      return a.mile + (b.mile - a.mile) * f;
    }
  }
  return route.distance_mi;
}

/** The checkpoint whose stretch of road contains the given mile. */
export function checkpointAtMile(route: RouteOption, mile: number) {
  return (
    route.checkpoints.find((cp) => mile >= cp.covers_mi[0] && mile <= cp.covers_mi[1]) ??
    route.checkpoints[route.checkpoints.length - 1]
  );
}
