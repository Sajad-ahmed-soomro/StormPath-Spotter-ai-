# StormPath — Weather-Aware Truck Routing

A React + Django web app that helps a truck driver choose the safest route. It weighs forecast weather at the truck's arrival time at each point along the route, the load weight, and travel time.

Enter an origin, a destination, a departure time and a load weight. The app then:

1. Generates **3 route options** with OSRM.
2. Places **weather checkpoints every 10, 25 or 50 miles** (your choice) and estimates the truck's **ETA** at each one.
3. Reads the **hourly forecast at that ETA** from Open-Meteo, and classifies risk with the **rule table and load rules** from the brief.
4. **Recommends a route**: fewest Severe miles → fewest High miles → lowest average risk → shortest time. It explains which criterion decided against each alternative.
5. Draws all routes, risk-colored checkpoints, ETAs and route summaries on a map. It also shows a **corridor weather heatmap** with a **0–48 h forecast slider** and playback. Truck markers move along each route in step with the slider.

All third-party services are free and need no API key: [OSRM](https://project-osrm.org) for routing, [Open-Meteo](https://open-meteo.com) for weather, [Photon](https://photon.komoot.io) for geocoding, and Esri Light Gray for the basemap.

---

## Quick start

Requirements: Python 3.11+ and Node 18+.

```bash
# Backend (http://127.0.0.1:8000)
cd backend
cp .env.example .env          # then set DJANGO_SECRET_KEY (command is in the file)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver

# Frontend dev server (http://localhost:5173, proxies /api to the backend)
cd frontend
cp .env.example .env
npm install
npm run dev
```

Production-style single server (Django serves the built SPA through WhiteNoise):

```bash
cd frontend && npm run build
cd ../backend && DJANGO_DEBUG=false gunicorn config.wsgi:application \
  --workers 1 --worker-class gthread --threads 16 --timeout 180
```

### Tests

```bash
cd backend && python manage.py test routing     # 30 tests: rules, load rules, ranking, ETAs, geometry, staged API flow
cd frontend && npm run typecheck
```

### Deploy

The repo ships a multi-stage `Dockerfile` (it builds the React app, then runs Django under gunicorn) and a Render blueprint (`render.yaml`). On Render, choose **New → Blueprint** and point it at this repo. Any Docker host works the same way. It listens on `$PORT`.

All configuration lives in environment variables. Nothing (API endpoints, keys, secrets) is hardcoded. Locally they are read from `backend/.env` and `frontend/.env`. Both files are git-ignored; copy them from the committed `.env.example` files. On Render, `render.yaml` generates the secret key and prompts for the other values in the dashboard (copy them from `backend/.env.example`). If a required variable is missing, the app stops at startup with a message naming it.

| Backend variable | Required | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | yes | Django secret |
| `DJANGO_DEBUG` | no (`false`) | `true` for local development |
| `DJANGO_ALLOWED_HOSTS` | no | Comma-separated hostnames, e.g. `.onrender.com` |
| `CORS_ALLOWED_ORIGINS` | no | Frontend origins on another host, e.g. the Vercel URL |
| `CORS_ALLOWED_ORIGIN_REGEXES` | no | Patterns for Vercel preview URLs |
| `OSRM_URLS` | yes | Comma-separated OSRM servers, tried in order with hedging |
| `OPEN_METEO_URL` | yes | Forecast endpoint (sent to the browser in each weather spec) |
| `PHOTON_URL` | yes | Geocoding server |
| `BASEMAP_URL` / `BASEMAP_LABELS_URL` | yes / no | Map tile templates, sent to the browser via `/api/meta/` |
| `HTTP_USER_AGENT` | yes | Identifies the app to the public APIs |
| `TRUCK_MAX_SPEED_MPH` | no (`65`) | Speed cap applied to ETAs |

| Frontend variable | Purpose |
|---|---|
| `VITE_DEV_API_PROXY` | Dev server only: where `/api` is forwarded |
| `VITE_API_BASE` | Backend URL when the frontend is hosted separately (e.g. on Vercel); empty when Django serves it |

**Frontend on Vercel, backend on Render:** import the repo in Vercel with **Root Directory `frontend`**. `frontend/vercel.json` sets up the Vite build. Add `VITE_API_BASE=https://<your-service>.onrender.com` in Vercel. On Render, set `CORS_ALLOWED_ORIGINS=https://<your-app>.vercel.app`.

---

## How it works

```
browser (React + TS + Leaflet)                 backend (Django + DRF)
──────────────────────────────                 ─────────────────────────────────────────
1. POST /api/plan/ ──────────────────────────► planner.prepare_plan
                                                 ├─ osrm.get_routes      3 distinct routes
                                                 ├─ truck_timed          per-segment truck ETAs
                                                 ├─ build_checkpoints    every N mi + destination
                                                 └─ weather.build_request  which forecasts to fetch
   ◄── plan_id + weather spec (url, params, locations, window)
2. fetch forecasts from Open-Meteo (visitor's own quota, batched)
3. POST /api/plan/<id>/score/ {hourly} ──────► planner.score_plan
                                                 ├─ weather.parse        validate against the spec
                                                 ├─ risk.assess          rule table + load rules at ETA
                                                 └─ recommend.rank       lexicographic ranking
   ◄── routes, checkpoints, segments, recommendation

Heatmap: POST /api/heatmap/ {plan_id} → spec → fetch → POST /api/heatmap/<id>/score/
         (heatmap.prepare_heatmap / score_heatmap: corridor grid × 49 hours × risk/wind/rain/snow)
```

**Why the browser downloads the forecasts.** Open-Meteo's free tier is rate-limited per IP address, and hosting platforms such as Render share outbound IPs between many customers, so server-side fetching ran into a quota other apps had already used up. The backend still decides *exactly* what to fetch (locations, hourly window, variables, units), keeps the prepared plan in its cache under a random id, and validates every forecast it receives (location count, array lengths, numeric values) before scoring. All routing, timing, risk and ranking logic stays on the server.

The core logic is in `backend/routing/services/`. Each module is small and pure where possible:

| Module | Responsibility |
|---|---|
| `risk.py` | Rule table and load rules; discrete level plus a continuous 0–4 index |
| `osrm.py` | Route options; via-point fallback that guarantees a third route; hedged requests |
| `planner.py` | Truck ETAs, checkpoint sampling, risk miles, map segments |
| `weather.py` | Batched Open-Meteo client, caching, sampling at an exact ETA |
| `recommend.py` | Ranking and human-readable reasons |
| `heatmap.py` | Mercator-uniform corridor grid and hourly risk fields |

### Routes

OSRM's `alternatives` often returns only 1–2 routes for long trips. When it does, the backend generates more by sending the route through **via points offset ±12% / ±25% to either side of the trip midpoint**. It screens those candidates with cheap simplified queries that run *in parallel* with the main query. A candidate is kept only if:

- it shares **< 80%** of its length with any existing route (relaxed to 95% if needed), and
- it is at most **60% slower** than the fastest route.

Each route is named after the town where it diverges most from the others (for example "Route C via Marshall, KS").

Public OSRM servers vary from under 1 s to over 15 s for the same query. If the first server hasn't answered in 5 s, the same request goes to the mirror and the first answer wins. Routes are cached for 30 minutes, so changing the checkpoint interval re-plans quickly.

### ETAs

OSRM returns a travel time for every road segment (`annotations=duration`). The public server only has a car profile, so each segment is slowed to at most **65 mph** (configurable) to reflect a loaded truck. A checkpoint's ETA is the departure time plus the cumulative truck time to that mile, interpolated along the geometry. Hours-of-service breaks are not modelled.

### Weather at the ETA

- Checkpoints sit at **mile 0, every N miles, and the destination**.
- Forecasts come from Open-Meteo in the rule units directly (mph, in/hr). Rain is `rain + showers`; snow is `snowfall`.
- **Wind** is interpolated linearly between the hours on either side of the ETA.
- **Precipitation** in Open-Meteo is the amount accumulated over the *preceding* hour. For an ETA of 08:30 the app therefore uses the value stamped 09:00 (the 08:00–09:00 accumulation). Unit tests cover this.
- Locations from all routes are rounded to ~1 km and **de-duplicated**, so shared stretches of road are fetched once. The browser downloads them in batches of 100.

### Risk rules

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind | <25 mph | 25–34 | 35–44 | 45–54 | ≥55 |
| Rain | <0.10 in/hr | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00 |
| Snow | <0.5 in/hr | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | >3.0 |

The load rules apply to wind:

- ≥55 mph → No Travel for any load
- 45–54 mph with >30,000 lb → No Travel
- 35–44 mph with >40,000 lb → Severe

A checkpoint's level is the **worst** of wind (after load rules), rain and snow. The table's ranges share their edge values, so I resolved boundaries as follows:

- Each band **includes its lower bound**: 35.0 mph is High, and 0.25 in/hr is High.
- Wind bands are continuous: 34.6 mph is still Moderate.
- Rain and snow No Travel is **strictly greater** than the top value (rain 1.00 is Severe), while wind No Travel is inclusive (≥55).
- The load thresholds are strict: exactly 30,000 lb does not trigger the first rule.

Unit tests cover every edge.

### Risk miles and recommendation

Each checkpoint represents the stretch of road **halfway to its neighbours**, so a route's risk miles add up exactly to its length. The average risk is the distance-weighted mean of the levels (Low 0 … No Travel 4).

Routes are ranked lexicographically by:

0. **fewest No-Travel miles.** The brief doesn't list this, but No Travel is strictly worse than Severe, so a route crossing a closure must never win on a tiebreak.
1. fewest Severe miles
2. fewest High miles
3. lowest average risk
4. shortest travel time

Miles are compared at 0.1 mi and average risk at 0.01, so float noise never decides a ranking. The UI states the deciding criterion against each alternative, for example "Fewer High-risk miles than Route C (0.0 mi vs 50 mi)". It also warns when even the best route includes Severe or No-Travel miles.

### Heatmap

- **Grid.** The backend lays a grid over a buffer around all routes: 20–75 mi wide, scaled with trip length, with about 200 cells. The grid is **uniform in Web Mercator**, so the browser can stretch one canvas over its bounds with no distortion. Cells near the corridor edge carry a fade weight.
- **Data.** For each of 49 hours the backend sends the load-adjusted risk index. That index is the same rule code as the checkpoints, made continuous within each band so the colours shade smoothly. Raw wind, rain and snow values are included too.
- **Rendering (`HeatField`).** The slider's fractional hour is blended between neighbouring frames. The renderer then **bilinearly upsamples value × weight and weight**, which gives soft edges without dark fringes, and colours each pixel through a 256-entry lookup table. Each paint is coalesced into one `requestAnimationFrame`. In Chrome, dragging the slider repaints at display rate (~16.6 ms per frame). Map layers are memoized, so playback never re-renders routes or markers.
- **Hover readout.** Hovering anywhere in the corridor shows interpolated wind, rain, snow and risk.
- **Timeline.** The slider is relative to the departure hour. Each route's truck marker shows where that truck will be at the selected time, so you can watch a route drive into, or ahead of, a weather system.

---

## API

| Method | Path | Body / query |
|---|---|---|
| `POST` | `/api/plan/` | `{origin, destination, departure, load_weight_lb, interval_mi}`. `origin` and `destination` are `{label, lat?, lon?}`; free text is geocoded. `interval_mi` is 10, 25 or 50. Returns `{plan_id, weather}`. |
| `POST` | `/api/plan/<plan_id>/score/` | `{hourly: [...]}`, one Open-Meteo `hourly` object per spec location. Returns the full plan. |
| `POST` | `/api/heatmap/` | `{plan_id}`. Returns `{heatmap_id, weather}`. |
| `POST` | `/api/heatmap/<heatmap_id>/score/` | `{hourly: [...]}`. Returns the 0–48 h corridor layers. |
| `GET` | `/api/geocode/?q=` | Place autocomplete |
| `GET` | `/api/meta/` | Rule thresholds (single source for UI legends) |
| `GET` | `/api/health/` | Liveness |

Validation errors return `400 {"error": "..."}`. Upstream failures return `502` with a readable message.

## Known limitations

- **No truck-specific routing.** The public OSRM server has no HGV profile (bridge heights, truck restrictions). The speed cap approximates truck travel times only.
- **Open-Meteo free-tier quotas** apply per visitor: about 600 location-calls per minute and 10,000 per day. A long trip at a 10-mile interval plus its heatmap uses roughly 300–500.
- **Prepared plans live in the server's memory** for an hour between the two stages. That fits one gunicorn process, as deployed. Running several processes or instances would need a shared cache such as Redis.
- **Departure window.** Departures are limited to the next 7 days, which keeps every ETA and the 48 h heatmap inside the 16-day forecast range.
- **Forecasts are model output.** Convective spikes in individual model hours, such as an isolated 3 in/hr cell, appear exactly as forecast.
