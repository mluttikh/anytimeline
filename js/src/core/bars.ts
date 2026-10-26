// Bars (intervals layers): decoding, culling, picking, labels in the bars, the arrows of
// dependencies and the critical path. The view owns the camera and the lanes (which row of the
// plot shows which lane, with folded lanes hidden); it passes them in a BarView.

import { BAR_MILESTONE, BAR_OPEN, barBox, type BarLayerDraw, FLAG_SELECTED } from "./renderers/renderer";
import { decodeStrings, fillSolid, lowerBound, upperBound, view } from "./scene";
import type { DataSource, IntervalsLayerSpec } from "./types";

export interface BarsData {
  spec: IntervalsLayerSpec;
  count: number;
  start: Float64Array;
  end: Float64Array;
  rankStart: Float64Array;
  rankEnd: Float64Array;
  lane: Uint32Array;
  laneStarts: Uint32Array;
  row: Float32Array;
  rows: Float32Array;
  kind: Uint8Array;
  color: Uint8Array;
  themeColor: boolean;
  progress: Float32Array | null;
  text: string[] | null;
  /** States layers: each bar's state. */
  states: string[] | null;
  links: Uint32Array | null;
  critical: Uint32Array | null;
  /** Per lane, the longest bar: how far left of the view a bar in view may start. */
  maxDur: Float64Array;
  maxDurRank: Float64Array;
}

/** What the view tells the bars about the frame. */
export interface BarView {
  left: number;
  scale: number;
  plot: { x: number; y: number; w: number; h: number };
  laneTop: number;
  laneH: number;
  maxBar: number;
  sequence: boolean;
  /** The row of each lane on the plot; -1 for a hidden (folded) lane. */
  slot: Int32Array;
}

export function decodeBars(spec: IntervalsLayerSpec, source: DataSource): BarsData {
  const n = spec.count;
  const start = Float64Array.from(view(spec.start, source) as ArrayLike<number>);
  const end = Float64Array.from(view(spec.end, source) as ArrayLike<number>);
  const rank = view(spec.rank, source);
  const rankStart = new Float64Array(n);
  const rankEnd = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    rankStart[i] = rank[2 * i];
    rankEnd[i] = rank[2 * i + 1];
  }
  const lane = view(spec.lane, source) as Uint32Array;
  const laneStarts = view(spec.lane_starts, source) as Uint32Array;
  let color: Uint8Array;
  let themeColor = false;
  if (spec.color.rgba) color = new Uint8Array(view(spec.color.rgba, source) as Uint8Array);
  else {
    color = new Uint8Array(n * 4);
    if (spec.color.solid === "theme" || !spec.color.solid) themeColor = true;
    else fillSolid(color, spec.color.solid, spec.color.alpha);
  }
  const lanes = Math.max(0, laneStarts.length - 1);
  const maxDur = new Float64Array(lanes);
  const maxDurRank = new Float64Array(lanes);
  for (let i = 0; i < n; i++) {
    const l = lane[i];
    maxDur[l] = Math.max(maxDur[l], end[i] - start[i]);
    maxDurRank[l] = Math.max(maxDurRank[l], rankEnd[i] - rankStart[i]);
  }
  return {
    spec,
    count: n,
    start,
    end,
    rankStart,
    rankEnd,
    lane,
    laneStarts,
    row: view(spec.row, source) as Float32Array,
    rows: view(spec.rows, source) as Float32Array,
    kind: view(spec.kind, source) as Uint8Array,
    color,
    themeColor,
    progress: spec.progress ? (view(spec.progress, source) as Float32Array) : null,
    text: spec.text ? decodeStrings(spec.text, source) : null,
    states: spec.states ? decodeStrings(spec.states.values, source) : null,
    links: spec.links ? (view(spec.links.pairs, source) as Uint32Array) : null,
    critical: spec.critical?.count ? (view(spec.critical.segments, source) as Uint32Array) : null,
    maxDur,
    maxDurRank,
  };
}

export class BarLayer {
  readonly draw: BarLayerDraw;

  constructor(
    readonly data: BarsData,
    accent: string,
  ) {
    const n = data.count;
    if (data.themeColor) fillSolid(data.color, accent, data.spec.color.alpha);
    const geom = new Float32Array(n * 4);
    const flags = new Uint8Array(n * 4);
    for (let i = 0; i < n; i++) {
      geom[4 * i] = data.lane[i];
      geom[4 * i + 1] = data.row[i];
      geom[4 * i + 2] = data.rows[i];
      geom[4 * i + 3] = data.progress ? data.progress[i] : -1;
      const fades = data.kind[i] === 2 && data.spec.fade_open !== false;
      flags[4 * i] = (data.kind[i] === 1 ? BAR_MILESTONE : 0) | (fades ? BAR_OPEN : 0);
    }
    this.draw = {
      key: data.spec.start.id + data.spec.name,
      count: n,
      x: { data: new Float32Array(n * 2), version: 0 },
      geom: { data: geom, version: 0 },
      color: { data: data.color, version: 0 },
      flags: { data: flags, version: 0 },
      offset: 0,
      scale: 1,
      laneTop: 0,
      laneHeight: 30,
      fill: data.spec.height,
      maxBar: 24,
      fade: false,
      visible: new Uint32Array(n),
      visibleCount: 0,
    };
  }

  /** The tallest a bar gets: bars that fill their lane (height 1, e.g. states as a lane's
   * background) are not capped. */
  maxBar(cap: number): number {
    return this.data.spec.height >= 0.99 ? 1e6 : cap;
  }

  /** Start and end on the current scale. */
  ends(sequence: boolean): [Float64Array, Float64Array] {
    return sequence ? [this.data.rankStart, this.data.rankEnd] : [this.data.start, this.data.end];
  }

  /** The bar of `lane` that `x` (on the current scale) is in, or -1: the last that starts
   * at or before it and ends after it (states: a lane's bars follow one another). */
  at(x: number, lane: number, sequence: boolean): number {
    const [lo, hi] = this.ends(sequence);
    const starts = this.data.laneStarts;
    if (lane + 1 >= starts.length) return -1;
    const i = upperBound(lo, x, starts[lane], starts[lane + 1]) - 1;
    return i >= starts[lane] && hi[i] >= x ? i : -1;
  }

  rebase(base: number, sequence: boolean, version: number): void {
    const [lo, hi] = this.ends(sequence);
    const x = this.draw.x.data;
    for (let i = 0; i < this.data.count; i++) {
      x[2 * i] = lo[i] - base;
      x[2 * i + 1] = hi[i] - base;
    }
    this.draw.x.version = version;
  }

  /** Place each bar on its lane's row (lanes were folded or unfolded). */
  setSlots(slot: Int32Array): void {
    const geom = this.draw.geom.data;
    for (let i = 0; i < this.data.count; i++) geom[4 * i] = slot[this.data.lane[i]] ?? -1;
    this.draw.geom.version++;
  }

  bumpAll(): void {
    for (const a of [this.draw.x, this.draw.geom, this.draw.color, this.draw.flags]) a.version++;
  }

  applyMarks(marks: Int32Array | undefined): void {
    const f = this.draw.flags.data;
    for (let i = 0; i < this.data.count; i++) f[4 * i] &= ~FLAG_SELECTED;
    if (marks) for (const i of marks) if (i >= 0 && i < this.data.count) f[4 * i] |= FLAG_SELECTED;
    this.draw.flags.version++;
  }

  recolor(accent: string): void {
    if (!this.data.themeColor) return;
    fillSolid(this.data.color, accent, this.data.spec.color.alpha);
    this.draw.color.version++;
  }

  /** The bars of the lanes on rows r0..r1 (`laneAt`: the lane of each row) that reach into
   * [a, b] (on the current scale). */
  cull(laneAt: Int32Array, r0: number, r1: number, a: number, b: number, sequence: boolean): void {
    const [lo, hi] = this.ends(sequence);
    const maxDur = sequence ? this.data.maxDurRank : this.data.maxDur;
    const starts = this.data.laneStarts;
    const vis = this.draw.visible;
    let n = 0;
    for (let r = r0; r <= r1 && r < laneAt.length; r++) {
      const lane = laneAt[r];
      if (lane + 1 >= starts.length) continue;
      const i0 = lowerBound(lo, a - maxDur[lane], starts[lane], starts[lane + 1]);
      const i1 = upperBound(lo, b, i0, starts[lane + 1]);
      for (let i = i0; i < i1; i++) if (hi[i] >= a) vis[n++] = i;
    }
    this.draw.visibleCount = n;
  }

  /** Where bar i is drawn (CSS px): its left and right ends, centre y and height. */
  box(i: number, v: BarView): { x0: number; x1: number; cy: number; h: number; milestone: boolean } {
    const [lo, hi] = this.ends(v.sequence);
    const x0 = v.plot.x + (lo[i] - v.left) * v.scale;
    const x1 = v.plot.x + (hi[i] - v.left) * v.scale;
    const { cy, h } = barBox(v.slot[this.data.lane[i]], this.data.row[i], this.data.rows[i], v.laneTop, v.laneH, this.data.spec.height, this.maxBar(v.maxBar));
    return { x0, x1: Math.max(x1, x0 + 1), cy, h, milestone: this.data.kind[i] === 1 };
  }

  /** The bar under a point (the lanes of rows near `row`), or -1. */
  pick(px: number, py: number, row: number, laneAt: Int32Array, v: BarView): number {
    const [lo, hi] = this.ends(v.sequence);
    const maxDur = v.sequence ? this.data.maxDurRank : this.data.maxDur;
    const starts = this.data.laneStarts;
    const x = v.left + (px - v.plot.x) / v.scale;
    const slack = 4 / v.scale;
    let best = -1;
    let bestD = Infinity;
    for (let r = Math.max(0, row - 1); r <= row + 1 && r < laneAt.length; r++) {
      const l = laneAt[r];
      if (l + 1 >= starts.length) continue;
      const i0 = lowerBound(lo, x - maxDur[l] - slack, starts[l], starts[l + 1]);
      const i1 = upperBound(lo, x + slack, i0, starts[l + 1]);
      for (let i = i0; i < i1; i++) {
        if (hi[i] + slack < x) continue;
        const b = this.box(i, v);
        const half = b.milestone ? b.h * 0.62 : b.h / 2;
        if (Math.abs(py - b.cy) > half + 2) continue;
        const d = b.milestone ? Math.abs(px - b.x0) : px < b.x0 ? b.x0 - px : px > b.x1 ? px - b.x1 : 0;
        if (d <= (b.milestone ? half + 2 : 3) && d < bestD) {
          bestD = d;
          best = i;
        }
      }
    }
    return best;
  }

  /** Text in each bar in view where it fits (truncated with …), milestones' beside them; and
   * each bar's duration right of it (`span` formats it) when the layer asks for that. */
  drawLabels(ctx: CanvasRenderingContext2D, v: BarView, ink: string, bg: string, muted: string, span: (ticks: number) => string): void {
    const text = this.data.text;
    const { plot } = v;
    if (this.data.spec.durations) {
      const { start, end, kind } = this.data;
      ctx.fillStyle = muted;
      for (let j = 0; j < this.draw.visibleCount; j++) {
        const i = this.draw.visible[j];
        if (kind[i] === 2) continue;
        const b = this.box(i, v);
        if (text?.[i] && b.milestone) continue; // the milestone's text goes there
        const label = span(end[i] - start[i]);
        const w = ctx.measureText(label).width;
        const reach = b.milestone ? b.h * 0.62 : 0;
        // right of the bar; left of it when that is past the plot's right edge
        let x = (b.milestone ? b.x0 : b.x1) + reach + 5;
        if (x + w > plot.x + plot.w) x = b.x0 - reach - 5 - w;
        if (x < plot.x || x + w > plot.x + plot.w) {
          // no room beside it: inside its right end, when the bar is long and has no text
          const right = Math.min(b.x1, plot.x + plot.w) - 5;
          if (b.milestone || text?.[i] || b.h < 9 || right - w < Math.max(b.x0, plot.x) + 5) continue;
          ctx.fillStyle = this.inkOn(i, ink);
          ctx.fillText(label, right - w, b.cy);
          ctx.fillStyle = muted;
          continue;
        }
        ctx.fillText(label, x, b.cy);
      }
    }
    if (!text) return;
    for (let j = 0; j < this.draw.visibleCount; j++) {
      const i = this.draw.visible[j];
      const label = text[i];
      if (!label) continue;
      const b = this.box(i, v);
      if (b.milestone) {
        ctx.fillStyle = ink;
        ctx.strokeStyle = bg;
        ctx.lineWidth = 3;
        ctx.strokeText(label, b.x0 + b.h * 0.62 + 4, b.cy);
        ctx.fillText(label, b.x0 + b.h * 0.62 + 4, b.cy);
        continue;
      }
      const left = Math.max(b.x0, plot.x) + 4;
      const room = Math.min(b.x1, plot.x + plot.w) - 4 - left;
      if (room < 16 || b.h < 9) continue;
      const fitted = fit(ctx, label, room);
      if (!fitted) continue;
      ctx.fillStyle = this.inkOn(i, ink);
      ctx.fillText(fitted, left, b.cy);
    }
  }

  /** Text colour on bar i: dark or white by its colour; a faint bar (a tint) takes the
   * plot's text colour, as the background shows through it. */
  private inkOn(i: number, ink: string): string {
    const c = this.data.color;
    if (c[4 * i + 3] < 150) return ink;
    return luminance(c[4 * i], c[4 * i + 1], c[4 * i + 2]) > 0.55 ? "#1b2430" : "#ffffff";
  }

  /**
   * The critical path: a line through the middle of each part of a bar on it, on rows r0..r1.
   */
  drawCritical(ctx: CanvasRenderingContext2D, v: BarView, r0: number, r1: number, color: string): void {
    const seg = this.data.critical;
    if (!seg) return;
    const [lo, hi] = this.ends(v.sequence);
    const at = (code: number) => ((code & 1) === 0 ? lo : hi)[code >>> 1];
    const right = v.left + v.plot.w / v.scale;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.beginPath();
    for (let k = 0; k < seg.length; k += 3) {
      const i = seg[k];
      const row = v.slot[this.data.lane[i]];
      if (row < r0 || row > r1) continue;
      const a = at(seg[k + 1]);
      const b = at(seg[k + 2]);
      if (b < v.left || a > right) continue;
      const box = this.box(i, v);
      const x0 = v.plot.x + (a - v.left) * v.scale;
      const x1 = Math.max(x0 + 1, v.plot.x + (b - v.left) * v.scale);
      ctx.moveTo(Math.max(x0, v.plot.x - 2) + 1, box.cy);
      ctx.lineTo(Math.min(x1, v.plot.x + v.plot.w + 2) - 1, box.cy);
    }
    ctx.stroke();
    ctx.restore();
  }

  /** Arrows of dependencies whose ends are on rows r0..r1 and near the view. */
  drawLinks(ctx: CanvasRenderingContext2D, v: BarView, l0: number, l1: number, color: string): void {
    const pairs = this.data.links;
    if (!pairs) return;
    const [lo, hi] = this.ends(v.sequence);
    const right = v.left + v.plot.w / v.scale;
    const slot = v.slot;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1.2;
    const heads: [number, number][] = [];
    ctx.beginPath();
    for (let k = 0; k < pairs.length / 2; k++) {
      const a = pairs[2 * k];
      const b = pairs[2 * k + 1];
      const ra = slot[this.data.lane[a]];
      const rb = slot[this.data.lane[b]];
      if (ra < 0 || rb < 0) continue; // a folded lane
      if ((ra < l0 && rb < l0) || (ra > l1 && rb > l1)) continue;
      if ((hi[a] < v.left && lo[b] < v.left) || (hi[a] > right && lo[b] > right)) continue;
      const pa = this.box(a, v);
      const pb = this.box(b, v);
      const ax = pa.milestone ? pa.x0 + pa.h * 0.62 : pa.x1;
      const bx = pb.milestone ? pb.x0 - pb.h * 0.62 : pb.x0;
      const ay = pa.cy;
      const by = pb.cy;
      ctx.moveTo(ax, ay);
      if (bx - ax >= 14) {
        ctx.lineTo(ax + 6, ay);
        ctx.lineTo(ax + 6, by);
        ctx.lineTo(bx - 1, by);
      } else {
        // the next bar starts before this one ends: around, between the two rows
        const my = by > ay ? Math.max(ay + pa.h / 2 + 3, by - pb.h / 2 - 3) : Math.min(ay - pa.h / 2 - 3, by + pb.h / 2 + 3);
        ctx.lineTo(ax + 6, ay);
        ctx.lineTo(ax + 6, my);
        ctx.lineTo(bx - 8, my);
        ctx.lineTo(bx - 8, by);
        ctx.lineTo(bx - 1, by);
      }
      heads.push([bx, by]);
    }
    ctx.stroke();
    ctx.beginPath();
    for (const [x, y] of heads) {
      ctx.moveTo(x, y);
      ctx.lineTo(x - 6, y - 3.5);
      ctx.lineTo(x - 6, y + 3.5);
      ctx.closePath();
    }
    ctx.fill();
    ctx.restore();
  }
}

function luminance(r: number, g: number, b: number): number {
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

/** `text`, cut with … to fit `width` px; "" when not even one letter and … fit. */
function fit(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  if (ctx.measureText(text).width <= width) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ctx.measureText(text.slice(0, mid) + "…").width <= width) lo = mid;
    else hi = mid - 1;
  }
  return lo ? text.slice(0, lo) + "…" : "";
}

