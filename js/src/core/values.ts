// Values layers: a number over time drawn as a small chart in each lane's band (a line, an area
// or steps), on the back canvas, behind the events and bars. Many samples: each pixel column
// draws the first, lowest, highest and last value in it, so a line of a million samples costs
// about as much as one of a few thousand.
//
// On the Order scale samples have no place of their own: each is drawn between the events it
// falls between (its time interpolated between theirs).

import { fillSolid, lowerBound, upperBound, view } from "./scene";
import type { ValueDetail } from "./levels";
import type { Sequence } from "./sequence";
import type { DataSource, ValuesLayerSpec } from "./types";

export interface ValuesData {
  spec: ValuesLayerSpec;
  count: number;
  time: Float64Array;
  value: Float32Array;
  /** Runs (one line each: a lane's series): samples runStarts[k] .. runStarts[k + 1]. */
  runStarts: Uint32Array;
  runLane: Uint32Array;
  runColor: Uint8Array;
  /** Per lane of the plot: the low and high value of its band. */
  ylim: Float64Array;
  themeColor: boolean;
}

/** What the view tells the values about the frame. */
export interface ValueView {
  left: number;
  scale: number;
  plot: { x: number; y: number; w: number; h: number };
  laneTop: number;
  laneH: number;
  /** The row of each lane; -1 for a hidden (folded) lane. */
  slot: Int32Array;
  sequence: boolean;
  seq: Sequence | null;
}

export function decodeValues(spec: ValuesLayerSpec, source: DataSource): ValuesData {
  const runs = spec.runs;
  const runColor = new Uint8Array(view(runs.color, source) as Uint8Array);
  const themeColor = !spec.color.legend && (!spec.color.solid || spec.color.solid === "theme");
  if (!themeColor && spec.color.solid && !spec.color.legend) fillSolid(runColor, spec.color.solid, spec.color.alpha);
  return {
    spec,
    count: spec.count,
    time: view(spec.time, source) as Float64Array,
    value: view(spec.value, source) as Float32Array,
    runStarts: view(runs.starts, source) as Uint32Array,
    runLane: view(runs.lane, source) as Uint32Array,
    runColor,
    ylim: view(spec.ylim, source) as Float64Array,
    themeColor,
  };
}

export class ValueLayer {
  private seqX: Float64Array | null = null;
  private seqFor: Sequence | null = null;
  private seqVersion = -1;
  /** A layer sent as levels: its samples are some of the layer's (a level's, a window's). */
  detail: ValueDetail | null = null;
  /** The index of each sample among the layer's, or null: they are all there. */
  index: Uint32Array | null = null;

  constructor(
    public data: ValuesData,
    private accent: string,
  ) {}

  /** Draw these samples from now on (a level's or a window's); true when they are others. */
  show(data: ValuesData, index: Uint32Array): boolean {
    if (data === this.data) return false;
    this.data = data;
    this.index = index;
    this.seqX = null;
    return true;
  }

  /** Sample i's index among the layer's (as Python knows it). */
  globalIndex(i: number): number {
    return this.index ? this.index[i] : i;
  }

  recolor(accent: string): void {
    this.accent = accent;
  }

  /** x of each sample on the current scale: its time, or its place between events. */
  xs(v: ValueView): Float64Array {
    const seq = v.seq;
    if (!v.sequence || !seq) return this.data.time;
    if (this.seqFor !== seq || this.seqVersion !== seq.version || !this.seqX) {
      const t = this.data.time;
      const out = new Float64Array(t.length);
      for (let i = 0; i < t.length; i++) out[i] = seq.position(t[i]);
      this.seqX = out;
      this.seqFor = seq;
      this.seqVersion = seq.version;
    }
    return this.seqX;
  }

  /** The band of lane `lane` on row `row`: value → y. */
  private yOf(lane: number, row: number, v: ValueView): (value: number) => number {
    const lo = this.data.ylim[2 * lane];
    const hi = this.data.ylim[2 * lane + 1];
    const pad = Math.max(2, v.laneH * 0.14);
    const top = v.laneTop + row * v.laneH + pad;
    const h = Math.max(1, v.laneH - 2 * pad);
    if (!(hi > lo)) return () => top + h / 2;
    return (value) => top + h - ((value - lo) / (hi - lo)) * h;
  }

  private color(k: number): string {
    if (this.data.themeColor) return this.accent;
    const c = this.data.runColor;
    return `rgba(${c[4 * k]},${c[4 * k + 1]},${c[4 * k + 2]},${(c[4 * k + 3] || 255) / 255})`;
  }

  /** Draw the lines of the lanes on rows r0..r1 (the back canvas, clipped to the plot). */
  draw(ctx: CanvasRenderingContext2D, v: ValueView, r0: number, r1: number): void {
    const d = this.data;
    const xs = this.xs(v);
    const right = v.left + v.plot.w / v.scale;
    const kind = d.spec.kind;
    ctx.save();
    ctx.lineWidth = d.spec.width;
    ctx.lineJoin = "round";
    for (let k = 0; k + 1 < d.runStarts.length; k++) {
      const lane = d.runLane[k];
      const row = v.slot[lane];
      if (row < r0 || row > r1 || row < 0) continue;
      const a = d.runStarts[k];
      const b = d.runStarts[k + 1];
      // one sample beyond each edge, so the line runs to the edges
      const i0 = Math.max(a, lowerBound(xs, v.left, a, b) - 1);
      const i1 = Math.min(b, upperBound(xs, right, i0, b) + 1);
      if (i1 <= i0) continue;
      const y = this.yOf(lane, row, v);
      const pts = this.points(xs, i0, i1, v, y, kind === "step");
      if (!pts.length) continue;
      const color = this.color(k);
      if (kind === "area") {
        const lo = d.ylim[2 * lane];
        const hi = d.ylim[2 * lane + 1];
        const base = y(lo <= 0 && hi >= 0 ? 0 : lo);
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.22;
        for (const line of pts) {
          ctx.beginPath();
          ctx.moveTo(line[0], base);
          for (let p = 0; p < line.length; p += 2) ctx.lineTo(line[p], line[p + 1]);
          ctx.lineTo(line[line.length - 2], base);
          ctx.closePath();
          ctx.fill();
        }
        ctx.globalAlpha = 1;
      }
      ctx.strokeStyle = color;
      ctx.beginPath();
      for (const line of pts) {
        ctx.moveTo(line[0], line[1]);
        for (let p = 2; p < line.length; p += 2) ctx.lineTo(line[p], line[p + 1]);
      }
      ctx.stroke();
    }
    ctx.restore();
  }

  /**
   * The polylines (x, y pairs; a missing value starts a new one) of samples i0..i1. Where
   * samples are denser than the pixels, each pixel column gives its first, lowest, highest
   * and last value.
   */
  private points(xs: Float64Array, i0: number, i1: number, v: ValueView, y: (value: number) => number, step: boolean): number[][] {
    const val = this.data.value;
    const lines: number[][] = [];
    let line: number[] = [];
    const px = (i: number) => v.plot.x + (xs[i] - v.left) * v.scale;
    const dense = i1 - i0 > v.plot.w * 2;
    if (!dense) {
      let lastY = NaN;
      for (let i = i0; i < i1; i++) {
        if (!Number.isFinite(val[i])) {
          if (line.length) lines.push(line);
          line = [];
          lastY = NaN;
          continue;
        }
        const x = px(i);
        const yy = y(val[i]);
        if (step && line.length) line.push(x, lastY);
        line.push(x, yy);
        lastY = yy;
      }
      if (line.length) lines.push(line);
      return lines;
    }
    let col = NaN;
    let first = 0;
    let lo = 0;
    let hi = 0;
    let last = 0;
    const flush = () => {
      if (Number.isNaN(col)) return;
      line.push(col, first);
      if (lo !== first) line.push(col, lo);
      if (hi !== lo) line.push(col, hi);
      if (last !== hi) line.push(col, last);
    };
    for (let i = i0; i < i1; i++) {
      if (!Number.isFinite(val[i])) {
        flush();
        col = NaN;
        if (line.length) lines.push(line);
        line = [];
        continue;
      }
      const c = Math.round(px(i));
      const yy = y(val[i]);
      if (c !== col) {
        flush();
        col = c;
        first = lo = hi = last = yy;
      } else {
        lo = Math.min(lo, yy);
        hi = Math.max(hi, yy);
        last = yy;
      }
    }
    flush();
    if (line.length) lines.push(line);
    return lines;
  }

  /** The high and low of each lane's band, small at its top and bottom left (when tall). */
  drawScales(ctx: CanvasRenderingContext2D, v: ValueView, r0: number, r1: number, fmt: (x: number) => string, minLane: number): void {
    if (v.laneH < minLane) return;
    const d = this.data;
    const seen = new Set<number>();
    for (let k = 0; k < d.runLane.length; k++) {
      const lane = d.runLane[k];
      const row = v.slot[lane];
      if (row < r0 || row > r1 || row < 0 || seen.has(lane)) continue;
      seen.add(lane);
      const lo = d.ylim[2 * lane];
      const hi = d.ylim[2 * lane + 1];
      if (!(hi >= lo)) continue;
      const y = this.yOf(lane, row, v);
      ctx.fillText(fmt(hi), v.plot.x + 3, y(hi));
      if (hi > lo) ctx.fillText(fmt(lo), v.plot.x + 3, y(lo));
    }
  }

  /** The sample nearest to a point (CSS px) on the lanes of rows near `row`, or -1. */
  pick(px: number, py: number, row: number, laneAt: Int32Array, v: ValueView, reach: number): number {
    const d = this.data;
    const xs = this.xs(v);
    const x = v.left + (px - v.plot.x) / v.scale;
    let best = -1;
    let bestD = reach;
    for (let k = 0; k + 1 < d.runStarts.length; k++) {
      const lane = d.runLane[k];
      const r = v.slot[lane];
      if (r < 0 || Math.abs(r - row) > 0 || laneAt[r] !== lane) continue;
      const a = d.runStarts[k];
      const b = d.runStarts[k + 1];
      const j = lowerBound(xs, x, a, b);
      const y = this.yOf(lane, r, v);
      for (const i of [j - 1, j]) {
        if (i < a || i >= b || !Number.isFinite(d.value[i])) continue;
        const dist = Math.hypot(v.plot.x + (xs[i] - v.left) * v.scale - px, y(d.value[i]) - py);
        if (dist < bestD) {
          bestD = dist;
          best = i;
        }
      }
    }
    return best;
  }

  /** Where sample i is drawn (CSS px). */
  position(i: number, v: ValueView): { x: number; y: number; color: string } {
    const d = this.data;
    const xs = this.xs(v);
    let k = upperBound(d.runStarts, i) - 1;
    k = Math.max(0, Math.min(d.runLane.length - 1, k));
    const lane = d.runLane[k];
    const y = this.yOf(lane, v.slot[lane], v);
    return { x: v.plot.x + (xs[i] - v.left) * v.scale, y: y(d.value[i]), color: this.color(k) };
  }

  /** The series of sample i (its run's name), or "". */
  seriesOf(i: number): string {
    const names = this.data.spec.series;
    if (!names) return "";
    const k = upperBound(this.data.runStarts, i) - 1;
    return names[k] ?? "";
  }

  /** The lane of sample i. */
  laneOf(i: number): number {
    const k = upperBound(this.data.runStarts, i) - 1;
    return this.data.runLane[Math.max(0, k)];
  }
}
