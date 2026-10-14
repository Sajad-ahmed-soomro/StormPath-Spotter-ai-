import L from "leaflet";
import { memo, useEffect, useMemo, useRef } from "react";
import {
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { Checkpoint, HeatLayerKey, MetaResponse, PlanResponse, RouteOption } from "../api";
import { fmtDayTime, fmtMiles } from "../lib/format";
import { LEVELS, levelColor } from "../lib/risk";
import { truckPosition } from "../lib/route";
import { HeatmapLayer } from "./HeatmapLayer";
import type { HeatField, HeatSample } from "./heatField";

export const ROUTE_COLORS: Record<string, string> = { A: "#0ea5e9", B: "#8b5cf6", C: "#db2777" };

interface Props {
  /** Tile URLs come from the backend's environment via /api/meta/. */
  basemap: MetaResponse["basemap"] | null;
  plan: PlanResponse | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  highlight: Checkpoint | null;
  field: HeatField | null;
  heatLayer: HeatLayerKey | null;
  hour: number;
  /** Seconds between departure and the heatmap's hour 0. */
  heatOffsetS: number;
  onHover: (sample: (HeatSample & { x: number; y: number }) | null) => void;
}

export function MapView(props: Props) {
  const { plan, selectedId, field, heatLayer, hour } = props;
  return (
    <MapContainer
      center={[39.5, -98.35]}
      zoom={4}
      minZoom={3}
      maxZoom={16}
      preferCanvas
      zoomControl={false}
      className="map"
      worldCopyJump
    >
      {props.basemap && (
        <TileLayer
          url={props.basemap.url}
        attribution='Basemap &copy; <a href="https://www.esri.com">Esri</a>, HERE, Garmin, &copy; OpenStreetMap contributors · Weather: <a href="https://open-meteo.com">Open-Meteo</a> · Routing: <a href="https://project-osrm.org">OSRM</a>'
          maxZoom={16}
        />
      )}
      {props.basemap?.labels_url && <LabelsLayer url={props.basemap.labels_url} />}
      <ZoomControl />
      {field && heatLayer && <HeatmapLayer field={field} layer={heatLayer} hour={hour} />}
      {plan && (
        <>
          <FitToPlan plan={plan} />
          <RoutesLayer plan={plan} selectedId={selectedId} onSelect={props.onSelect} />
          <CheckpointsLayer plan={plan} selectedId={selectedId} onSelect={props.onSelect} />
          <Endpoints plan={plan} />
          <Trucks plan={plan} selectedId={selectedId} elapsedS={hour * 3600 + props.heatOffsetS} />
          {props.highlight && <HighlightRing cp={props.highlight} />}
        </>
      )}
      {field && heatLayer && <HoverProbe field={field} hour={hour} onHover={props.onHover} />}
    </MapContainer>
  );
}

/** Place labels drawn above the heatmap so towns stay readable under heavy weather. */
function LabelsLayer({ url }: { url: string }) {
  const map = useMap();
  useEffect(() => {
    if (!map.getPane("labels")) {
      const pane = map.createPane("labels");
      pane.style.zIndex = "360";
      pane.style.pointerEvents = "none";
    }
    const layer = L.tileLayer(url, { pane: "labels", maxZoom: 16 }).addTo(map);
    return () => {
      layer.remove();
    };
  }, [map, url]);
  return null;
}

function ZoomControl() {
  const map = useMap();
  useEffect(() => {
    const control = L.control.zoom({ position: "topright" }).addTo(map);
    return () => {
      control.remove();
    };
  }, [map]);
  return null;
}

function FitToPlan({ plan }: { plan: PlanResponse }) {
  const map = useMap();
  useEffect(() => {
    const bounds = L.latLngBounds(plan.routes.flatMap((r) => r.path));
    map.flyToBounds(bounds, { paddingTopLeft: [40, 40], paddingBottomRight: [40, 170], duration: 0.8 });
  }, [map, plan]);
  return null;
}

const RoutesLayer = memo(function RoutesLayer({
  plan,
  selectedId,
  onSelect,
}: {
  plan: PlanResponse;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const others = plan.routes.filter((r) => r.id !== selectedId);
  const selected = plan.routes.find((r) => r.id === selectedId);
  return (
    <>
      {others.map((r) => (
        <Polyline
          key={r.id}
          positions={r.path}
          pathOptions={{ color: ROUTE_COLORS[r.id], weight: 5, opacity: 0.6, lineJoin: "round" }}
          eventHandlers={{ click: () => onSelect(r.id) }}
        >
          <Tooltip sticky>
            {r.name} · {fmtMiles(r.distance_mi)} — click to select
          </Tooltip>
        </Polyline>
      ))}
      {selected && <SelectedRoute route={selected} />}
    </>
  );
});

function SelectedRoute({ route }: { route: RouteOption }) {
  return (
    <>
      <Polyline
        positions={route.path}
        pathOptions={{ color: "#0f172a", weight: 11, opacity: 0.85, lineJoin: "round" }}
        interactive={false}
      />
      <Polyline
        positions={route.path}
        pathOptions={{ color: ROUTE_COLORS[route.id], weight: 9, opacity: 1, lineJoin: "round" }}
        interactive={false}
      />
      {route.segments.map((seg, i) => (
        <Polyline
          key={i}
          positions={seg.coords}
          pathOptions={{ color: levelColor(seg.level), weight: 4.5, opacity: 1, lineJoin: "round" }}
          interactive={false}
        />
      ))}
    </>
  );
}

const CheckpointsLayer = memo(function CheckpointsLayer({
  plan,
  selectedId,
  onSelect,
}: {
  plan: PlanResponse;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const ordered = [...plan.routes].sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId));
  return (
    <>
      {ordered.map((route) => {
        const active = route.id === selectedId;
        return route.checkpoints.map((cp) => (
          <CircleMarker
            key={`${route.id}-${cp.index}`}
            center={[cp.lat, cp.lon]}
            radius={active ? 6 : 3.5}
            pathOptions={{
              color: active ? "#ffffff" : ROUTE_COLORS[route.id],
              weight: active ? 2 : 1,
              fillColor: levelColor(cp.level),
              fillOpacity: active ? 1 : 0.85,
              opacity: active ? 1 : 0.8,
            }}
            eventHandlers={active ? undefined : { click: () => onSelect(route.id) }}
          >
            <Tooltip direction="top" offset={[0, -6]}>
              <CheckpointTooltip route={route} cp={cp} />
            </Tooltip>
            {active && (
              <Popup>
                <CheckpointPopup route={route} cp={cp} />
              </Popup>
            )}
          </CircleMarker>
        ));
      })}
    </>
  );
});

function LevelPill({ level }: { level: number }) {
  const l = LEVELS[level];
  return (
    <span className="pill" style={{ background: l.color, color: l.text }}>
      {l.label}
    </span>
  );
}

function CheckpointTooltip({ route, cp }: { route: RouteOption; cp: Checkpoint }) {
  return (
    <div className="cp-tip">
      <div className="cp-tip-head">
        <strong>
          Route {route.id} · mile {Math.round(cp.mile)}
        </strong>
        <LevelPill level={cp.level} />
      </div>
      <div>ETA {fmtDayTime(cp.eta)}</div>
      <div className="muted">
        {cp.weather.wind_mph.toFixed(0)} mph · {cp.weather.rain_in_hr.toFixed(2)}″ rain ·{" "}
        {cp.weather.snow_in_hr.toFixed(2)}″ snow
      </div>
    </div>
  );
}

function CheckpointPopup({ route, cp }: { route: RouteOption; cp: Checkpoint }) {
  const w = cp.weather;
  return (
    <div className="cp-popup">
      <div className="cp-tip-head">
        <strong>
          {route.name} — mile {cp.mile.toFixed(0)}
        </strong>
        <LevelPill level={cp.level} />
      </div>
      <div className="muted">
        ETA {fmtDayTime(cp.eta)} · {cp.elapsed_h.toFixed(1)} h after departure
      </div>
      <table>
        <tbody>
          <tr>
            <th>Conditions</th>
            <td>
              {w.description}, {w.temp_f.toFixed(0)}°F
            </td>
          </tr>
          <tr>
            <th>Wind</th>
            <td>
              {w.wind_mph.toFixed(0)} mph <span className="muted">(gusts {w.gust_mph.toFixed(0)})</span>
            </td>
          </tr>
          <tr>
            <th>Rain</th>
            <td>{w.rain_in_hr.toFixed(2)} in/hr</td>
          </tr>
          <tr>
            <th>Snow</th>
            <td>{w.snow_in_hr.toFixed(2)} in/hr</td>
          </tr>
        </tbody>
      </table>
      {cp.factors.length > 0 && (
        <ul className="factors">
          {cp.factors.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function endpointIcon(kind: "origin" | "destination") {
  return L.divIcon({
    className: "",
    html: `<div class="endpoint endpoint-${kind}">${kind === "origin" ? "A" : "B"}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function Endpoints({ plan }: { plan: PlanResponse }) {
  const icons = useMemo(() => ({ o: endpointIcon("origin"), d: endpointIcon("destination") }), []);
  return (
    <>
      <Marker position={[plan.origin.lat, plan.origin.lon]} icon={icons.o} zIndexOffset={900}>
        <Tooltip direction="top" offset={[0, -14]}>
          Origin · {plan.origin.label}
        </Tooltip>
      </Marker>
      <Marker position={[plan.destination.lat, plan.destination.lon]} icon={icons.d} zIndexOffset={900}>
        <Tooltip direction="top" offset={[0, -14]}>
          Destination · {plan.destination.label}
        </Tooltip>
      </Marker>
    </>
  );
}

const TRUCK_SVG = `<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M3 6h11v9H3zM14 9h4l3 3v3h-7z"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/></svg>`;

function truckIcon(color: string, active: boolean) {
  return L.divIcon({
    className: "",
    html: `<div class="truck ${active ? "truck-active" : ""}" style="--c:${color}">${TRUCK_SVG}</div>`,
    iconSize: active ? [30, 30] : [22, 22],
    iconAnchor: active ? [15, 15] : [11, 11],
  });
}

/** Each route's truck at the forecast slider's time, so you can see what weather it meets. */
function Trucks({ plan, selectedId, elapsedS }: { plan: PlanResponse; selectedId: string | null; elapsedS: number }) {
  const icons = useMemo(
    () =>
      Object.fromEntries(
        plan.routes.map((r) => [r.id, truckIcon(ROUTE_COLORS[r.id], r.id === selectedId)]),
      ),
    [plan, selectedId],
  );
  return (
    <>
      {plan.routes.map((r) => {
        const pos = truckPosition(r, elapsedS);
        return (
          <Marker
            key={r.id}
            position={[pos.lat, pos.lon]}
            icon={icons[r.id]}
            zIndexOffset={r.id === selectedId ? 1000 : 950}
            interactive={false}
          />
        );
      })}
    </>
  );
}

function HighlightRing({ cp }: { cp: Checkpoint }) {
  const map = useMap();
  useEffect(() => {
    if (!map.getBounds().pad(-0.1).contains([cp.lat, cp.lon])) {
      map.panTo([cp.lat, cp.lon], { animate: true });
    }
  }, [map, cp]);
  return (
    <CircleMarker
      center={[cp.lat, cp.lon]}
      radius={13}
      pathOptions={{ color: "#0f172a", weight: 3, fillOpacity: 0, dashArray: "4 3" }}
      interactive={false}
    />
  );
}

function HoverProbe({
  field,
  hour,
  onHover,
}: {
  field: HeatField;
  hour: number;
  onHover: Props["onHover"];
}) {
  const last = useRef<L.LeafletMouseEvent | null>(null);
  const hourRef = useRef(hour);
  hourRef.current = hour;

  const emit = () => {
    const e = last.current;
    if (!e) return;
    const sample = field.sample(e.latlng.lat, e.latlng.lng, hourRef.current);
    onHover(sample ? { ...sample, x: e.containerPoint.x, y: e.containerPoint.y } : null);
  };

  useMapEvents({
    mousemove(e) {
      last.current = e;
      emit();
    },
    mouseout() {
      last.current = null;
      onHover(null);
    },
  });
  // Keep the readout live while the forecast plays under a still cursor.
  useEffect(emit, [hour, field]);
  return null;
}
