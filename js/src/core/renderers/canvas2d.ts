// Canvas 2D backend: the CPU fallback. Draws only the events in view (the view culls them),
// batched into one path per colour and symbol; above MAX_MARKS per frame it draws an evenly
// spaced subset and reports it.

import type { RendererKind } from "../types";
import { BAR_MILESTONE, BAR_OPEN, barBox, FLAG_HOVERED, FLAG_SELECTED, type BarLayerDraw, type FrameDraw, type Renderer, type RendererOptions } from "./renderer";
import { isOpen, tracePath } from "./symbols";

export const MAX_MARKS = 40_000;

export class Canvas2DRenderer implements Renderer {
  readonly kind: RendererKind = "canvas2d";
  readonly description = "Canvas 2D (CPU)";
  onFailure: ((reason: string) => void) | null = null;
  /** Events left out of the last frame (above MAX_MARKS). */
  thinned = 0;
  private dpr = 1;

  static create(canvas: HTMLCanvasElement, _options: RendererOptions): Canvas2DRenderer | null {
    const ctx = canvas.getContext("2d");
    return ctx ? new Canvas2DRenderer(canvas, ctx) : null;
  }

  private constructor(
    readonly canvas: HTMLCanvasElement,
    private readonly ctx: CanvasRenderingContext2D,
  ) {}

  resize(cssWidth: number, cssHeight: number, dpr: number): void {
    // device pixel ratio 1 at most: 4× fewer pixels on a retina screen, for speed
    this.dpr = Math.min(dpr, 1.5);
    this.canvas.width = Math.max(1, Math.round(cssWidth * this.dpr));
    this.canvas.height = Math.max(1, Math.round(cssHeight * this.dpr));
  }

  render(frame: FrameDraw): void {
    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.save();
    const { plot } = frame;
    ctx.beginPath();
    ctx.rect(plot.x, plot.y, plot.w, plot.h);
    ctx.clip();

    for (const b of frame.bars) this.drawBars(b, frame);

    for (const s of frame.segments) {
      ctx.lineWidth = s.width;
      const byColor = new Map<number, Path2D>();
      for (let i = 0; i < s.count; i++) {
        const key = (s.colors[4 * i] << 16) | (s.colors[4 * i + 1] << 8) | s.colors[4 * i + 2];
        let p = byColor.get(key);
        if (!p) byColor.set(key, (p = new Path2D()));
        p.moveTo(s.coords[4 * i], s.coords[4 * i + 1]);
        p.lineTo(s.coords[4 * i + 2], s.coords[4 * i + 3]);
      }
      ctx.globalAlpha = s.count ? s.colors[3] / 255 : 1;
      for (const [key, p] of byColor) {
        ctx.strokeStyle = `rgb(${key >> 16},${(key >> 8) & 255},${key & 255})`;
        ctx.stroke(p);
      }
      ctx.globalAlpha = 1;
    }

    const total = frame.layers.reduce((n, l) => n + l.visibleCount, 0);
    const stride = Math.max(1, Math.ceil(total / MAX_MARKS));
    this.thinned = stride > 1 ? total - Math.floor(total / stride) : 0;
    const rgb = (c: [number, number, number]) => `rgb(${c.map((v) => Math.round(v * 255)).join(",")})`;
    for (const layer of frame.layers) {
      const filled = new Map<string, Path2D>();
      const open = new Map<string, Path2D>();
      const rings: { x: number; y: number; r: number; hover: boolean }[] = [];
      const xs = layer.x.data;
      const sf = layer.sf.data;
      const col = layer.color.data;
      for (let j = 0; j < layer.visibleCount; j += stride) {
        const i = layer.visible[j];
        const x = plot.x + (xs[i] - layer.offset) * layer.scale;
        const y = layer.laneTop + (layer.lane.data[i] + 0.5) * layer.laneHeight + layer.dy.data[i];
        const r = layer.size.data[i] / 2;
        const flags = sf[4 * i + 1];
        const faded = layer.fade && !(flags & FLAG_SELECTED);
        const a = (col[4 * i + 3] / 255) * (faded ? 0.2 : 1);
        const key = `${col[4 * i]},${col[4 * i + 1]},${col[4 * i + 2]},${a.toFixed(2)}`;
        const target = isOpen(sf[4 * i]) ? open : filled;
        let p = target.get(key);
        if (!p) target.set(key, (p = new Path2D()));
        tracePath(p, sf[4 * i], x, y, r);
        if (flags & (FLAG_SELECTED | FLAG_HOVERED)) rings.push({ x, y, r, hover: !!(flags & FLAG_HOVERED) });
      }
      for (const [key, p] of filled) {
        ctx.fillStyle = `rgba(${key})`;
        ctx.fill(p);
      }
      for (const [key, p] of open) {
        const [r, g, b, a] = key.split(",");
        ctx.strokeStyle = `rgba(${r},${g},${b},${a})`;
        ctx.fillStyle = `rgba(${r},${g},${b},${a})`;
        ctx.lineWidth = 1.6;
        ctx.stroke(p);
      }
      for (const ring of rings) {
        ctx.beginPath();
        ctx.arc(ring.x, ring.y, ring.r + 2, 0, Math.PI * 2);
        ctx.strokeStyle = rgb(ring.hover ? frame.hover : frame.selection);
        ctx.lineWidth = 1.8;
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  /** Bars in view: rectangles (milestones: diamonds), the part past the progress lighter. */
  private drawBars(layer: BarLayerDraw, frame: FrameDraw): void {
    const ctx = this.ctx;
    const { plot } = frame;
    const xs = layer.x.data;
    const g = layer.geom.data;
    const col = layer.color.data;
    const fl = layer.flags.data;
    const bg = frame.background.map((v) => Math.round(v * 255));
    const sel = `rgb(${frame.selection.map((v) => Math.round(v * 255)).join(",")})`;
    for (let j = 0; j < layer.visibleCount; j++) {
      const i = layer.visible[j];
      const x0 = plot.x + (xs[2 * i] - layer.offset) * layer.scale;
      const x1 = plot.x + (xs[2 * i + 1] - layer.offset) * layer.scale;
      const { cy, h } = barBox(g[4 * i], g[4 * i + 1], g[4 * i + 2], layer.laneTop, layer.laneHeight, layer.fill, layer.maxBar);
      const flags = fl[4 * i];
      const faded = layer.fade && !(flags & FLAG_SELECTED);
      const a = (col[4 * i + 3] / 255) * (faded ? 0.22 : 1);
      const rgb = [col[4 * i], col[4 * i + 1], col[4 * i + 2]];
      ctx.fillStyle = `rgba(${rgb.join(",")},${a})`;
      if (flags & BAR_MILESTONE) {
        const r = h * 0.62;
        ctx.beginPath();
        ctx.moveTo(x0, cy - r);
        ctx.lineTo(x0 + r, cy);
        ctx.lineTo(x0, cy + r);
        ctx.lineTo(x0 - r, cy);
        ctx.closePath();
        ctx.fill();
        if (flags & FLAG_SELECTED) {
          ctx.strokeStyle = sel;
          ctx.lineWidth = 1.8;
          ctx.stroke();
        }
        continue;
      }
      const a0 = Math.max(x0, plot.x - 8);
      const b0 = Math.min(Math.max(x1 - (x1 - x0 > 3 ? 1 : 0), x0 + 1), plot.x + plot.w + 8);
      const w = Math.max(1, b0 - a0);
      if (flags & BAR_OPEN) {
        const grad = ctx.createLinearGradient(a0, 0, a0 + w, 0);
        grad.addColorStop(0, `rgba(${rgb.join(",")},${a})`);
        grad.addColorStop(Math.max(0, 1 - 48 / w), `rgba(${rgb.join(",")},${a})`);
        grad.addColorStop(1, `rgba(${rgb.join(",")},${a * 0.12})`);
        ctx.fillStyle = grad;
      }
      ctx.fillRect(a0, cy - h / 2, w, h);
      const p = g[4 * i + 3];
      if (p >= 0) {
        const px = Math.max(a0, Math.min(a0 + w, x0 + p * (x1 - x0)));
        const light = rgb.map((v, k) => Math.round(v * 0.45 + bg[k] * 0.55));
        ctx.fillStyle = `rgba(${light.join(",")},${a})`;
        ctx.fillRect(px, cy - h / 2, a0 + w - px, h);
      }
      if (flags & FLAG_SELECTED) {
        ctx.strokeStyle = sel;
        ctx.lineWidth = 1.8;
        ctx.strokeRect(a0 - 1.5, cy - h / 2 - 1.5, w + 3, h + 3);
      }
    }
  }

  async finish(): Promise<void> {}

  retain(_keys: Set<string>): void {}

  destroy(): void {}
}
