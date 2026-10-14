import L from "leaflet";
import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import type { HeatLayerKey } from "../api";
import type { HeatField } from "./heatField";

interface Props {
  field: HeatField;
  layer: HeatLayerKey;
  hour: number;
}

/**
 * Draws the heat field into a single canvas that Leaflet positions and scales
 * like an image overlay. Slider/playback updates only repaint the canvas
 * (coalesced to one paint per animation frame) — no layers are rebuilt.
 */
export function HeatmapLayer({ field, layer, hour }: Props) {
  const map = useMap();
  const ctxRef = useRef<{ ctx: CanvasRenderingContext2D; image: ImageData } | null>(null);
  const frameRef = useRef<number | null>(null);
  const latest = useRef({ layer, hour });
  latest.current = { layer, hour };

  useEffect(() => {
    if (!map.getPane("heat")) {
      const pane = map.createPane("heat");
      pane.style.zIndex = "350"; // above tiles, below routes and markers
      pane.style.pointerEvents = "none";
    }
    const canvas = document.createElement("canvas");
    canvas.width = field.width;
    canvas.height = field.height;
    canvas.className = "heat-canvas";
    const ctx = canvas.getContext("2d")!;
    ctxRef.current = { ctx, image: ctx.createImageData(field.width, field.height) };
    field.render(ctx, ctxRef.current.image, latest.current.layer, latest.current.hour);

    // SVGOverlay positions an arbitrary element over geographic bounds;
    // a canvas works the same way as an <svg> here.
    const overlay = L.svgOverlay(canvas as unknown as SVGElement, field.bounds, {
      pane: "heat",
      interactive: false,
    }).addTo(map);
    return () => {
      overlay.remove();
      ctxRef.current = null;
    };
  }, [map, field]);

  useEffect(() => {
    if (frameRef.current !== null) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      const target = ctxRef.current;
      if (target) field.render(target.ctx, target.image, latest.current.layer, latest.current.hour);
    });
  }, [field, layer, hour]);

  useEffect(
    () => () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    },
    [],
  );

  return null;
}
