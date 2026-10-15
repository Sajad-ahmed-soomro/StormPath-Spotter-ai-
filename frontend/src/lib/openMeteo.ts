import type { WeatherSpec } from "../api";

const CONCURRENCY = 4;

type Hourly = Record<string, unknown>;

/**
 * Download the forecasts described by a backend weather spec.
 *
 * Runs in the visitor's browser so each visitor uses their own Open-Meteo
 * quota (the free tier is limited per IP, and hosting platforms share IPs).
 * Returns each location's ``hourly`` object, in the spec's order.
 */
export async function fetchForecasts(
  spec: WeatherSpec,
  signal?: AbortSignal,
  onProgress?: (done: number, total: number) => void,
): Promise<Hourly[]> {
  const batches: [number, number][][] = [];
  for (let i = 0; i < spec.locations.length; i += spec.batch_size) {
    batches.push(spec.locations.slice(i, i + spec.batch_size));
  }
  const results: Hourly[][] = new Array(batches.length);
  let done = 0;
  let next = 0;

  const worker = async () => {
    while (next < batches.length) {
      const i = next++;
      results[i] = await fetchBatch(spec, batches[i], signal);
      done += batches[i].length;
      onProgress?.(done, spec.locations.length);
    }
  };
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, batches.length) }, worker));
  return results.flat();
}

async function fetchBatch(spec: WeatherSpec, locations: [number, number][], signal?: AbortSignal) {
  const query = new URLSearchParams({
    ...spec.params,
    latitude: locations.map(([lat]) => lat.toFixed(2)).join(","),
    longitude: locations.map(([, lon]) => lon.toFixed(2)).join(","),
  });
  let resp: Response;
  try {
    resp = await fetch(`${spec.url}?${query}`, { signal });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new Error("Couldn't reach the weather service (Open-Meteo). Check your connection and try again.");
  }
  const body = await resp.json().catch(() => null);
  if (resp.status === 429) {
    throw new Error("Open-Meteo's free rate limit was reached for your network. Please retry in a minute.");
  }
  if (!resp.ok || !body) {
    throw new Error(`Weather service error: ${body?.reason ?? resp.status}`);
  }
  const items: { hourly: Hourly }[] = Array.isArray(body) ? body : [body];
  // Only the hourly arrays are needed; drop timestamps to keep the upload small.
  return items.map(({ hourly }) => {
    const { time: _time, ...values } = hourly;
    return values;
  });
}
