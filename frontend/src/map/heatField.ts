import type { HeatLayerKey, HeatmapResponse, Rules } from "../api";
import { RISK_LUT, valueToIndex } from "../lib/risk";

const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
const TARGET_CANVAS_PX = 720;

export interface HeatSample {
  risk: number;
  wind: number;
  rain: number;
  snow: number;
}

/**
 * Corridor forecast as dense grids, plus a renderer that draws any
 * (layer, fractional hour) to a canvas.
 *
 * The grid is uniform in Web Mercator, so a canvas stretched over the grid
 * bounds lines up exactly with the map. Rendering:
 *   1. blend the two neighbouring hourly frames (smooth playback),
 *   2. bilinearly upsample value × weight and weight (soft corridor edges
 *      without dark fringes),
 *   3. colour through a 256-entry lookup table.
 */
export class HeatField {
  readonly nx: number;
  readonly ny: number;
  readonly hours: number;
  readonly scale: number;
  private readonly weight: Float32Array;
  private readonly raw: Record<HeatLayerKey, Float32Array[]>;
  private readonly index: Partial<Record<HeatLayerKey, Float32Array[]>> = {};
  private readonly scratch: Float32Array;
  private readonly x0: Int32Array;
  private readonly x1: Int32Array;
  private readonly fx: Float32Array;
  private readonly yTop: number;
  private readonly yBottom: number;

  constructor(
    private readonly heat: HeatmapResponse,
    private readonly rules: Rules,
  ) {
    const { nx, ny, cells, weights } = heat.grid;
    this.nx = nx;
    this.ny = ny;
    this.hours = heat.hours.length;
    this.weight = new Float32Array(nx * ny);
    cells.forEach((cell, i) => (this.weight[cell] = weights[i]));

    const densify = (frames: number[][]) =>
      frames.map((frame) => {
        const dense = new Float32Array(nx * ny);
        frame.forEach((v, i) => (dense[cells[i]] = v));
        return dense;
      });
    this.raw = {
      risk: densify(heat.layers.risk),
      wind: densify(heat.layers.wind),
      rain: densify(heat.layers.rain),
      snow: densify(heat.layers.snow),
    };
    this.index.risk = this.raw.risk;

    this.scale = Math.max(4, Math.min(24, Math.round(TARGET_CANVAS_PX / Math.max(nx, ny))));
    this.scratch = new Float32Array(nx * ny);
    const width = nx * this.scale;
    this.x0 = new Int32Array(width);
    this.x1 = new Int32Array(width);
    this.fx = new Float32Array(width);
    for (let px = 0; px < width; px++) {
      const gx = Math.min(Math.max((px + 0.5) / this.scale - 0.5, 0), nx - 1);
      this.x0[px] = Math.floor(gx);
      this.x1[px] = Math.min(this.x0[px] + 1, nx - 1);
      this.fx[px] = gx - this.x0[px];
    }
    this.yTop = mercY(heat.grid.bounds.north);
    this.yBottom = mercY(heat.grid.bounds.south);
  }

  get bounds(): [[number, number], [number, number]] {
    const b = this.heat.grid.bounds;
    return [
      [b.south, b.west],
      [b.north, b.east],
    ];
  }

  get width() {
    return this.nx * this.scale;
  }

  get height() {
    return this.ny * this.scale;
  }

  /** Frames on the shared 0–4 index scale (raw layers converted lazily, once). */
  private frames(layer: HeatLayerKey): Float32Array[] {
    let frames = this.index[layer];
    if (!frames) {
      const t = this.rules.conditions.find((c) => c.name === layer)!;
      frames = this.raw[layer].map((f) => f.map((v) => valueToIndex(v, t)));
      this.index[layer] = frames;
    }
    return frames;
  }

  render(ctx: CanvasRenderingContext2D, image: ImageData, layer: HeatLayerKey, hour: number) {
    const { nx, ny, scale, weight, scratch, x0, x1, fx } = this;
    const frames = this.frames(layer);
    const h = Math.min(Math.max(hour, 0), this.hours - 1);
    const h0 = Math.floor(h);
    const a = frames[h0];
    const b = frames[Math.min(h0 + 1, this.hours - 1)];
    const t = h - h0;

    // Premultiplied value (value × weight) on the coarse grid.
    for (let i = 0; i < nx * ny; i++) {
      scratch[i] = weight[i] > 0 ? (a[i] + (b[i] - a[i]) * t) * weight[i] : 0;
    }

    const data = image.data;
    const width = nx * scale;
    const height = ny * scale;
    let p = 0;
    for (let py = 0; py < height; py++) {
      const gy = Math.min(Math.max((py + 0.5) / scale - 0.5, 0), ny - 1);
      const y0 = Math.floor(gy);
      const y1 = Math.min(y0 + 1, ny - 1);
      const fy = gy - y0;
      const r0 = y0 * nx;
      const r1 = y1 * nx;
      for (let px = 0; px < width; px++, p += 4) {
        const c0 = x0[px];
        const c1 = x1[px];
        const f = fx[px];
        const w0 = weight[r0 + c0] + (weight[r0 + c1] - weight[r0 + c0]) * f;
        const w1 = weight[r1 + c0] + (weight[r1 + c1] - weight[r1 + c0]) * f;
        const w = w0 + (w1 - w0) * fy;
        if (w < 0.01) {
          data[p + 3] = 0;
          continue;
        }
        const v0 = scratch[r0 + c0] + (scratch[r0 + c1] - scratch[r0 + c0]) * f;
        const v1 = scratch[r1 + c0] + (scratch[r1 + c1] - scratch[r1 + c0]) * f;
        const value = (v0 + (v1 - v0) * fy) / w;
        const li = Math.min(255, Math.max(0, Math.round(value * 63.75))) * 4;
        data[p] = RISK_LUT[li];
        data[p + 1] = RISK_LUT[li + 1];
        data[p + 2] = RISK_LUT[li + 2];
        data[p + 3] = RISK_LUT[li + 3] * Math.min(1, w * 1.15);
      }
    }
    ctx.putImageData(image, 0, 0);
  }

  /** Interpolated raw values at a map position, or null outside the corridor. */
  sample(lat: number, lon: number, hour: number): HeatSample | null {
    const { west, east } = this.heat.grid.bounds;
    const gx = ((lon - west) / (east - west)) * this.nx - 0.5;
    const gy = ((this.yTop - mercY(lat)) / (this.yTop - this.yBottom)) * this.ny - 0.5;
    if (gx < -0.5 || gy < -0.5 || gx > this.nx - 0.5 || gy > this.ny - 0.5) return null;

    const cx = Math.min(Math.max(gx, 0), this.nx - 1);
    const cy = Math.min(Math.max(gy, 0), this.ny - 1);
    const xa = Math.floor(cx);
    const ya = Math.floor(cy);
    const xb = Math.min(xa + 1, this.nx - 1);
    const yb = Math.min(ya + 1, this.ny - 1);
    const corners: [number, number][] = [
      [ya * this.nx + xa, (1 - (cx - xa)) * (1 - (cy - ya))],
      [ya * this.nx + xb, (cx - xa) * (1 - (cy - ya))],
      [yb * this.nx + xa, (1 - (cx - xa)) * (cy - ya)],
      [yb * this.nx + xb, (cx - xa) * (cy - ya)],
    ];
    const totalWeight = corners.reduce((s, [i, k]) => s + this.weight[i] * k, 0);
    if (totalWeight < 0.25) return null;

    const h = Math.min(Math.max(hour, 0), this.hours - 1);
    const h0 = Math.floor(h);
    const h1 = Math.min(h0 + 1, this.hours - 1);
    const t = h - h0;
    const at = (frames: Float32Array[]) => {
      let sum = 0;
      let wsum = 0;
      for (const [i, k] of corners) {
        const w = this.weight[i] * k;
        if (w <= 0) continue;
        sum += (frames[h0][i] + (frames[h1][i] - frames[h0][i]) * t) * w;
        wsum += w;
      }
      return wsum > 0 ? sum / wsum : 0;
    };
    return {
      risk: at(this.raw.risk),
      wind: at(this.raw.wind),
      rain: at(this.raw.rain),
      snow: at(this.raw.snow),
    };
  }
}
