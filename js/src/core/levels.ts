// Levels of detail of an events layer of many events (Python: anytimeline.levels). Python
// sends the layer's events counted per lane and bin, at bin widths a factor of 4 apart, and
// the events themselves only when asked: a window of a range, when few enough are in view.
//
// Each frame picks the finest level whose bins are at least BIN_PX wide (the levels Python
// sent, or a window's bins when the view is finer still), and draws its bins: a bin of more
// than one event as a bar from its first to its last event, its height by its count, in its
// most frequent colour; a bin of one event as that event. When the bins in view hold at most
// `raw` events, the view asks for those events and draws them as any layer's (Layer.data,
// with Layer.index the index of each among the layer's).

import { BarLayer, type BarView, decodeBars } from "./bars";
import { type BarLayerDraw, barBox, FLAG_SELECTED, type MarkLayerDraw } from "./renderers/renderer";
import { decodeEvents, type EventsData, fillSolid, lowerBound, specBufferIds, SYMBOLS, upperBound, view as bytes } from "./scene";
import type { Sequence } from "./sequence";
import type { BarLevelsSpec, DataSource, EventsLayerSpec, IntervalsLayerSpec, LevelSpec, LevelsSpec, ValueLevelsSpec, ValuesLayerSpec, WindowAnswer, XScale } from "./types";
import { decodeValues, type ValuesData } from "./values";

/** Asks Python for a window of a layer sent as levels: its events in a range (k null), or its
 * bins of level k there. */
export type WindowAsk = (layer: string, scale: XScale, range: [number, number], k: number | null) => Promise<WindowAnswer>;

/** A level's bins are drawn at least this wide (px). */
export const BIN_PX = 4;
/** The bars of bins fill this much of their lane at the most. */
export const BIN_FILL = 0.8;

/** One level (or a window's bins), decoded. */
export interface BinsData {
  spec: LevelSpec;
  scale: XScale;
  k: number;
  count: number;
  most: number;
  laneStarts: Uint32Array;
  /** Each bin's lane. */
  lane: Uint32Array;
  lo: Float64Array;
  hi: Float64Array;
  n: Uint32Array;
  /** Each bin's representative event: its index among the layer's events. */
  top: Uint32Array;
  color: Uint8Array;
  themeColor: boolean;
  alpha: number;
  symbol: Uint8Array;
  size: Float32Array;
}

export function decodeBins(spec: LevelSpec, scale: XScale, layer: EventsLayerSpec, source: DataSource): BinsData {
  const n = spec.count;
  const laneStarts = bytes(spec.lane_starts, source) as Uint32Array;
  const lane = new Uint32Array(n);
  for (let l = 0; l + 1 < laneStarts.length; l++) lane.fill(l, laneStarts[l], laneStarts[l + 1]);
  let color: Uint8Array;
  let themeColor = false;
  if (spec.rgba) color = new Uint8Array(bytes(spec.rgba, source) as Uint8Array);
  else {
    color = new Uint8Array(n * 4);
    if (layer.color.solid === "theme" || !layer.color.solid) themeColor = true;
    else fillSolid(color, layer.color.solid, layer.color.alpha);
  }
  const symbol = spec.symbol ? (bytes(spec.symbol, source) as Uint8Array) : new Uint8Array(n).fill(Math.max(0, SYMBOLS.indexOf(layer.symbol.value ?? "circle")));
  const size = spec.size ? (bytes(spec.size, source) as Float32Array) : new Float32Array(n).fill(layer.size.value ?? 8);
  return {
    spec,
    scale,
    k: spec.k,
    count: n,
    most: spec.most,
    laneStarts,
    lane,
    lo: bytes(spec.lo, source) as Float64Array,
    hi: bytes(spec.hi, source) as Float64Array,
    n: bytes(spec.n, source) as Uint32Array,
    top: bytes(spec.top, source) as Uint32Array,
    color,
    themeColor,
    alpha: layer.color.alpha,
    symbol,
    size,
  };
}

/** A level as it is drawn: its bins of more than one event as bars, of one event as marks. */
export class BinsLayer {
  readonly bars: BarLayerDraw;
  readonly marks: MarkLayerDraw;
  /** The bin each bar and each mark stands for. */
  readonly barBin: Uint32Array;
  readonly markBin: Uint32Array;
  /** Per bin: its bar (≥ 0) or its mark (−1 − index). */
  private readonly instance: Int32Array;
  /** How many events the bins in view hold (set by cull). */
  inView = 0;
  /** What the arrays were last made for: the view's base, rows, mark size and accent. */
  private baseFor = NaN;
  private slotFor: Int32Array | null = null;
  private scaleFor = NaN;
  private accentFor = "";
  private markedFor: Float64Array | undefined;

  constructor(readonly data: BinsData) {
    const d = data;
    let bars = 0;
    for (let i = 0; i < d.count; i++) if (d.n[i] > 1) bars++;
    const marks = d.count - bars;
    this.barBin = new Uint32Array(bars);
    this.markBin = new Uint32Array(marks);
    this.instance = new Int32Array(d.count);
    let b = 0;
    let m = 0;
    for (let i = 0; i < d.count; i++) {
      if (d.n[i] > 1) {
        this.instance[i] = b;
        this.barBin[b++] = i;
      } else {
        this.instance[i] = -1 - m;
        this.markBin[m++] = i;
      }
    }
    const geom = new Float32Array(bars * 4);
    const barColor = new Uint8Array(bars * 4);
    const top = Math.log1p(Math.max(2, d.most));
    for (let j = 0; j < bars; j++) {
      const i = this.barBin[j];
      // the height by count, on a log scale: a bin of many next to one of few still shows
      geom[4 * j + 2] = 1;
      geom[4 * j + 3] = -2 - Math.max(0.22, Math.log1p(d.n[i]) / top);
    }
    const sf = new Uint8Array(marks * 4);
    for (let j = 0; j < marks; j++) sf[4 * j] = d.symbol[this.markBin[j]];
    const key = `bins:${d.spec.lo.id}`;
    this.bars = {
      key: `${key}:bars`,
      count: bars,
      x: { data: new Float32Array(bars * 2), version: 0 },
      geom: { data: geom, version: 0 },
      color: { data: barColor, version: 0 },
      flags: { data: new Uint8Array(bars * 4), version: 0 },
      offset: 0,
      scale: 1,
      laneTop: 0,
      laneHeight: 30,
      fill: BIN_FILL,
      maxBar: 1e6,
      fade: false,
      visible: new Uint32Array(bars),
      visibleCount: 0,
    };
    this.marks = {
      key: `${key}:marks`,
      count: marks,
      x: { data: new Float32Array(marks), version: 0 },
      lane: { data: new Float32Array(marks), version: 0 },
      dy: { data: new Float32Array(marks), version: 0 },
      size: { data: new Float32Array(marks), version: 0 },
      color: { data: new Uint8Array(marks * 4), version: 0 },
      sf: { data: sf, version: 0 },
      offset: 0,
      scale: 1,
      laneTop: 0,
      laneHeight: 30,
      fade: false,
      visible: new Uint32Array(marks),
      visibleCount: 0,
    };
  }

  /** Bring the arrays up to date with the view: its base, rows, mark size and accent. */
  update(base: number, slot: Int32Array, markScale: number, accent: string): void {
    const d = this.data;
    if (base !== this.baseFor) {
      this.baseFor = base;
      const bx = this.bars.x.data;
      for (let j = 0; j < this.barBin.length; j++) {
        const i = this.barBin[j];
        bx[2 * j] = d.lo[i] - base;
        bx[2 * j + 1] = d.hi[i] - base;
      }
      const mx = this.marks.x.data;
      for (let j = 0; j < this.markBin.length; j++) mx[j] = d.lo[this.markBin[j]] - base;
      this.bars.x.version++;
      this.marks.x.version++;
    }
    if (slot !== this.slotFor) {
      this.slotFor = slot;
      const g = this.bars.geom.data;
      for (let j = 0; j < this.barBin.length; j++) g[4 * j] = slot[d.lane[this.barBin[j]]] ?? -1;
      const ml = this.marks.lane.data;
      for (let j = 0; j < this.markBin.length; j++) ml[j] = slot[d.lane[this.markBin[j]]] ?? -1;
      this.bars.geom.version++;
      this.marks.lane.version++;
    }
    if (markScale !== this.scaleFor) {
      this.scaleFor = markScale;
      const s = this.marks.size.data;
      for (let j = 0; j < this.markBin.length; j++) s[j] = d.size[this.markBin[j]] * markScale;
      this.marks.size.version++;
    }
    if (accent !== this.accentFor) {
      this.accentFor = accent;
      if (d.themeColor) fillSolid(d.color, accent, d.alpha);
      const bc = this.bars.color.data;
      for (let j = 0; j < this.barBin.length; j++) bc.set(d.color.subarray(4 * this.barBin[j], 4 * this.barBin[j] + 4), 4 * j);
      const mc = this.marks.color.data;
      for (let j = 0; j < this.markBin.length; j++) mc.set(d.color.subarray(4 * this.markBin[j], 4 * this.markBin[j] + 4), 4 * j);
      this.bars.color.version++;
      this.marks.color.version++;
    }
  }

  /** Flag the bins that hold a selected event (`marked`: time, place in the order and lane of
   * each, as Python sends them), so that a selection fades the others. */
  select(marked: Float64Array | undefined): void {
    if (marked === this.markedFor) return;
    this.markedFor = marked;
    const d = this.data;
    const held = new Uint8Array(d.count);
    const starts = d.laneStarts;
    const at = d.scale === "order" ? 1 : 0;
    for (let k = 0; marked && k + 2 < marked.length; k += 3) {
      const lane = marked[k + 2];
      if (lane + 1 >= starts.length) continue;
      const x = marked[k + at];
      const i = lowerBound(d.hi, x, starts[lane], starts[lane + 1]);
      if (i < starts[lane + 1] && d.lo[i] <= x) held[i] = 1;
    }
    const bf = this.bars.flags.data;
    for (let j = 0; j < this.barBin.length; j++) bf[4 * j] = held[this.barBin[j]] ? FLAG_SELECTED : 0;
    const sf = this.marks.sf.data;
    for (let j = 0; j < this.markBin.length; j++) sf[4 * j + 1] = held[this.markBin[j]] ? FLAG_SELECTED : 0;
    this.bars.flags.version++;
    this.marks.sf.version++;
  }

  /** The bins of the lanes on rows r0..r1 that reach into [a, b]; counts their events. */
  cull(laneAt: Int32Array, r0: number, r1: number, a: number, b: number): void {
    const d = this.data;
    const starts = d.laneStarts;
    let nb = 0;
    let nm = 0;
    let events = 0;
    for (let r = r0; r <= r1 && r < laneAt.length; r++) {
      const lane = laneAt[r];
      if (lane + 1 >= starts.length) continue;
      // bins do not overlap: the first that ends at or after a, to the last that starts by b
      const i0 = lowerBound(d.hi, a, starts[lane], starts[lane + 1]);
      const i1 = upperBound(d.lo, b, i0, starts[lane + 1]);
      for (let i = i0; i < i1; i++) {
        const k = this.instance[i];
        if (k >= 0) this.bars.visible[nb++] = k;
        else this.marks.visible[nm++] = -1 - k;
        events += d.n[i];
      }
    }
    this.bars.visibleCount = nb;
    this.marks.visibleCount = nm;
    this.inView = events;
  }

  /** Where bin i is drawn (CSS px): a bar's ends, centre and height; a mark's centre. */
  box(i: number, v: BarView): { x0: number; x1: number; cy: number; h: number; mark: boolean } {
    const d = this.data;
    const x0 = v.plot.x + (d.lo[i] - v.left) * v.scale;
    const x1 = v.plot.x + (d.hi[i] - v.left) * v.scale;
    const row = v.slot[d.lane[i]];
    const k = this.instance[i];
    if (k < 0) return { x0, x1: x0, cy: v.laneTop + (row + 0.5) * v.laneH, h: d.size[i] * this.scaleFor, mark: true };
    const { cy, h } = barBox(row, 0, 1, v.laneTop, v.laneH, BIN_FILL, 1e6, this.bars.geom.data[4 * k + 3]);
    return { x0, x1: Math.max(x1, x0 + 1), cy, h, mark: false };
  }

  /** The bin under a point (the lanes of rows near `row`), or −1. */
  pick(px: number, py: number, row: number, laneAt: Int32Array, v: BarView, reach: number): number {
    const d = this.data;
    const starts = d.laneStarts;
    const x = v.left + (px - v.plot.x) / v.scale;
    const slack = reach / v.scale;
    let best = -1;
    let bestD = Infinity;
    for (let r = Math.max(0, row - 1); r <= row + 1 && r < laneAt.length; r++) {
      const l = laneAt[r];
      if (l + 1 >= starts.length) continue;
      const i0 = lowerBound(d.hi, x - slack, starts[l], starts[l + 1]);
      const i1 = upperBound(d.lo, x + slack, i0, starts[l + 1]);
      for (let i = i0; i < i1; i++) {
        const b = this.box(i, v);
        const dy = Math.max(0, Math.abs(py - b.cy) - b.h / 2);
        const dx = px < b.x0 ? b.x0 - px : px > b.x1 ? px - b.x1 : 0;
        const dist = Math.hypot(dx, dy);
        if (dist <= reach && dist < bestD) {
          bestD = dist;
          best = i;
        }
      }
    }
    return best;
  }

  /** The first and last position of the bins of lanes lane0 .. lane1 − 1, or null. */
  extent(lane0: number, lane1: number): [number, number] | null {
    const s = this.data.laneStarts;
    let a = Infinity;
    let b = -Infinity;
    for (let l = lane0; l < lane1 && l + 1 < s.length; l++) {
      if (s[l + 1] <= s[l]) continue;
      a = Math.min(a, this.data.lo[s[l]]);
      b = Math.max(b, this.data.hi[s[l + 1] - 1]);
    }
    return b >= a ? [a, b] : null;
  }
}

/** What the view does for a layer sent as levels: what it draws (or asks for). */
export interface DetailView {
  readonly xscale: XScale;
  readonly camera: { left: number; right: number; span: number; scale: number };
  readonly slot: Int32Array;
  readonly laneAt: Int32Array;
  requestRender(): void;
  /** A window's events came: draw them for this layer. */
  setWindow(detail: Detail, data: EventsData, index: Uint32Array): void;
  /** The exact times of the order from rank `offset` (a window's). */
  setSequence(offset: number, times: Float64Array): void;
  /** The layer's bins changed: the renderer may forget those no longer kept. */
  retainDraws(): void;
}

/** The levels and windows of one events layer sent as levels. */
export class Detail {
  readonly levels: LevelsSpec;
  /** The levels sent with the plot, decoded as they come: per scale, as in the spec. */
  private readonly made: Record<XScale, (BinsLayer | null)[]>;
  private readonly loading = new Set<string>();
  /** The bins of a window (finer than the levels sent). */
  private windowBins: { bins: BinsLayer; range: [number, number] } | null = null;
  /** The scale and range of the window of events the view's layer holds, or null. */
  private raw: { scale: XScale; range: [number, number] } | null = null;
  /** A window asked for and not answered; the last one asked for. */
  private asking = false;
  private asked: { scale: XScale; k: number | null; range: [number, number] } | null = null;
  /** The bins drawn in the last frame (picking), or null: the events are drawn. */
  shown: BinsLayer | null = null;
  /** The last frame drew other bins than the one before (a bin hovered is another one). */
  changed = false;
  private gone = false;

  constructor(
    readonly spec: EventsLayerSpec,
    private readonly source: DataSource,
    private readonly ask: WindowAsk | null,
  ) {
    this.levels = spec.levels!;
    this.made = { time: this.levels.time.levels.map(() => null), order: this.levels.order.levels.map(() => null) };
  }

  /** The buffers of the coarsest level of a scale (loaded with the spec, for a first frame). */
  firstIds(scale: XScale): string[] {
    const first = this.levels[scale].levels[0];
    return first ? specBufferIds(first) : [];
  }

  /** The view moved on to another spec: answers still coming are for nothing. */
  destroy(): void {
    this.gone = true;
  }

  /** Every renderer key this layer's bins use (those kept). */
  keys(into: Set<string>): void {
    for (const scale of ["time", "order"] as XScale[])
      for (const b of this.made[scale])
        if (b) {
          into.add(b.bars.key);
          into.add(b.marks.key);
        }
    if (this.windowBins) {
      into.add(this.windowBins.bins.bars.key);
      into.add(this.windowBins.bins.marks.key);
    }
  }

  /**
   * What to draw in this frame: the bins of a level (culled to rows r0..r1), "raw" when the
   * layer's events cover the view (a window of few enough), or null when nothing is loaded
   * yet. Starts loading the level the view wants, and asks for windows.
   */
  frame(view: DetailView, events: EventsData, r0: number, r1: number): BinsLayer | "raw" | null {
    const scale = view.xscale;
    const cam = view.camera;
    const a = cam.left;
    const b = cam.right;
    const lv = this.levels;
    if (this.raw && this.raw.scale === scale && this.raw.range[0] <= a && this.raw.range[1] >= b) {
      if (countInView(events, scale, view.laneAt, r0, r1, a, b) <= lv.raw * 1.5) {
        this.show(null);
        return "raw";
      }
    }
    const want = eventsLevel(lv[scale].top, cam.scale);
    const bins = this.choose(view, scale, want, a, b);
    this.show(bins);
    if (!bins) return null;
    bins.cull(view.laneAt, r0, r1, a, b);
    if (lv.windows && bins.inView <= lv.raw) this.askFor(view, scale, null, a, b);
    return bins;
  }

  private show(bins: BinsLayer | null): void {
    this.changed = bins !== this.shown;
    this.shown = bins;
  }

  /** The bins to draw for level `want`: those of the level nearest it (finer ones only when no
   * coarser is loaded); loads the level, or asks for a window's bins finer than the levels. */
  private choose(view: DetailView, scale: XScale, want: number, a: number, b: number): BinsLayer | null {
    const list = this.levels[scale].levels;
    const made = this.made[scale];
    if (!list.length) return null;
    const finest = list.length - 1;
    // the finest level sent whose bins are wide enough (the coarsest when zoomed out past it)
    let at = 0;
    for (let i = 0; i < list.length; i++) if (list[i].k <= want) at = i;
    if (!made[at]) this.load(view, scale, at);
    if (want > list[finest].k && this.levels.windows) {
      const w = this.windowBins;
      const fits = w && w.bins.data.scale === scale && w.bins.data.k === want && w.range[0] <= a && w.range[1] >= b;
      if (fits) return w.bins;
      this.askFor(view, scale, want, a, b);
      // until it comes: the window's bins if they cover the view, else the finest level
      if (w && w.bins.data.scale === scale && w.range[0] <= a && w.range[1] >= b) return w.bins;
    }
    if (made[at]) return made[at];
    // the nearest one loaded, coarser first
    for (let d = 1; d <= finest; d++) {
      if (at - d >= 0 && made[at - d]) return made[at - d];
      if (at + d <= finest && made[at + d]) return made[at + d];
    }
    return null;
  }

  private load(view: DetailView, scale: XScale, at: number): void {
    const key = `${scale}:${at}`;
    if (this.loading.has(key)) return;
    this.loading.add(key);
    const spec = this.levels[scale].levels[at];
    const ids = specBufferIds(spec);
    void this.source.ensure(ids).then(() => {
      if (this.gone || !ids.every((id) => this.source.has(id))) return;
      this.made[scale][at] = new BinsLayer(decodeBins(spec, scale, this.spec, this.source));
      view.requestRender();
    });
  }

  /** Decode a level sent with the plot now (its buffers are there). */
  preload(scale: XScale): void {
    const spec = this.levels[scale].levels[0];
    if (spec && !this.made[scale][0] && specBufferIds(spec).every((id) => this.source.has(id))) {
      this.made[scale][0] = new BinsLayer(decodeBins(spec, scale, this.spec, this.source));
    }
  }

  /** Ask Python for a window around the view (three views wide): its events (k null) or its
   * bins of level k. One at a time; not again for a view inside the last one asked for. */
  private askFor(view: DetailView, scale: XScale, k: number | null, a: number, b: number): void {
    const ask = this.ask;
    if (!ask || this.asking) return;
    const last = this.asked;
    if (last && last.scale === scale && last.k === k && last.range[0] <= a && last.range[1] >= b) return;
    const span = b - a;
    const range: [number, number] = [a - span, b + span];
    this.asking = true;
    this.asked = { scale, k, range };
    ask(this.spec.name, scale, range, k)
      .then(async (answer) => {
        const ids = specBufferIds(answer.spec, true);
        if (answer.sequence) ids.push(answer.sequence.times.id);
        await this.source.ensure(ids);
        if (this.gone || !ids.every((id) => this.source.has(id))) return;
        if (answer.sequence) view.setSequence(answer.sequence.offset, new Float64Array(this.source.get(answer.sequence.times.id)));
        if (k === null) {
          const spec = answer.spec as EventsLayerSpec;
          this.raw = { scale, range: answer.range };
          view.setWindow(this, decodeEvents(spec, this.source), new Uint32Array(this.source.get(spec.index!.id)));
        } else {
          this.windowBins = { bins: new BinsLayer(decodeBins(answer.spec as LevelSpec, scale, this.spec, this.source)), range: answer.range };
          view.retainDraws();
        }
      })
      .catch(() => {})
      .finally(() => {
        this.asking = false;
        if (!this.gone) view.requestRender();
      });
  }

  /** The first and last position of the layer's events on lanes lane0 .. lane1 − 1 (on the
   * view's scale), from the coarsest level loaded. */
  extent(scale: XScale, lane0: number, lane1: number): [number, number] | null {
    const b = this.made[scale].find((m) => m);
    return b ? b.extent(lane0, lane1) : null;
  }

}

/** The level an events layer draws: the finest whose bins are at least BIN_PX wide at
 * `scale` px per unit (`top`: the coarsest level's bin width). */
export function eventsLevel(top: number, scale: number): number {
  const bins = (top * scale) / BIN_PX;
  return bins > 0 ? Math.floor(Math.log(bins) / Math.log(4)) : 0;
}

/** The level a values layer draws: the coarsest whose bins are at most a pixel wide at `px`
 * px per unit of time. */
export function valuesLevel(top: number, px: number): number {
  const bins = top * px;
  return bins > 1 ? Math.ceil(Math.log(bins) / Math.log(4)) : 0;
}

/** The level an intervals layer draws: the coarsest whose bins are at most MERGE_PX wide. */
export function barsLevel(top: number, scale: number): number {
  const bins = (top * scale) / MERGE_PX;
  return bins > 1 ? Math.ceil(Math.log(bins) / Math.log(4)) : 0;
}

/** How many of a window's events are in view (lanes on rows r0..r1, from a to b). */
function countInView(d: EventsData, scale: XScale, laneAt: Int32Array, r0: number, r1: number, a: number, b: number): number {
  const src = scale === "order" ? d.rank : d.time;
  const starts = d.laneStarts;
  let n = 0;
  for (let r = r0; r <= r1 && r < laneAt.length; r++) {
    const lane = laneAt[r];
    if (lane + 1 >= starts.length) continue;
    const i0 = lowerBound(src, a, starts[lane], starts[lane + 1]);
    n += upperBound(src, b, i0, starts[lane + 1]) - i0;
  }
  return n;
}

// ------------------------------------------------------------------ values layers

/** What a values layer sent as levels needs of the view. */
export interface ValueDetailView {
  readonly xscale: XScale;
  readonly camera: { left: number; right: number; span: number; scale: number };
  readonly seq: Sequence | null;
  requestRender(): void;
}

/** Samples to draw: a level's or a window's, and the index of each among the layer's. */
export interface ValueSamples {
  data: ValuesData;
  index: Uint32Array;
}

/**
 * The levels and windows of one values layer of many samples. Level k has the samples that
 * draw the layer with bins of width top / 4^k (each run's first, lowest, highest and last
 * sample per bin); each frame draws the coarsest level whose bins are at most a pixel wide.
 * Finer than the levels sent, the view asks for a window: every sample of a range when few
 * enough, else those of a finer level there.
 */
export class ValueDetail {
  readonly levels: ValueLevelsSpec;
  private readonly made: (ValueSamples | null)[];
  private readonly loading = new Set<number>();
  /** A window's samples: every one (k null) or those of level k, from range[0] to range[1]. */
  private window: { samples: ValueSamples; k: number | null; range: [number, number] } | null = null;
  private asking = false;
  private asked: { k: number; range: [number, number] } | null = null;
  private gone = false;

  constructor(
    readonly spec: ValuesLayerSpec,
    private readonly source: DataSource,
    private readonly ask: WindowAsk | null,
  ) {
    this.levels = spec.levels!;
    this.made = this.levels.levels.map(() => null);
  }

  /** The buffers of the coarsest level (loaded with the spec, for a first frame). */
  firstIds(): string[] {
    const first = this.levels.levels[0];
    return first ? specBufferIds(first) : [];
  }

  /** Decode the coarsest level now (its buffers are there). */
  preload(): void {
    const spec = this.levels.levels[0];
    if (spec && !this.made[0] && specBufferIds(spec).every((id) => this.source.has(id))) this.made[0] = this.decode(spec);
  }

  destroy(): void {
    this.gone = true;
  }

  private decode(spec: ValuesLayerSpec): ValueSamples {
    const index = spec.index ? new Uint32Array(this.source.get(spec.index.id)) : new Uint32Array(0);
    return { data: decodeValues(spec, this.source), index };
  }

  /** The samples to draw in this frame, or null when none is loaded yet. Starts loading the
   * level the view wants, and asks for windows. */
  frame(view: ValueDetailView): ValueSamples | null {
    const cam = view.camera;
    // the times in view, and how many px a unit of time is (on the Order scale, on average)
    let ta = cam.left;
    let tb = cam.right;
    const seq = view.xscale === "order" ? view.seq : null;
    if (seq && seq.count) {
      const at = (x: number) => seq.time(Math.max(0, Math.min(seq.count - 1, x)));
      ta = at(Math.floor(cam.left));
      tb = at(Math.ceil(cam.right));
    }
    const px = tb > ta ? ((cam.right - cam.left) * cam.scale) / (tb - ta) : cam.scale;
    const want = valuesLevel(this.levels.top, px);
    const w = this.window;
    const covers = !!w && w.range[0] <= ta && w.range[1] >= tb;
    if (w && covers && (w.k === null || w.k >= want)) return w.samples;
    const list = this.levels.levels;
    if (!list.length) return null;
    const finest = list.length - 1;
    // the coarsest level fine enough (the finest when none is)
    let at = finest;
    for (let i = finest; i >= 0; i--) if (list[i].k >= want) at = i;
    if (!this.made[at]) this.load(view, at);
    if (want > list[finest].k && this.levels.windows) {
      this.askFor(view, want, ta, tb);
      if (w && covers) return w.samples;
    }
    if (this.made[at]) return this.made[at];
    for (let d = 1; d <= finest; d++) {
      if (at - d >= 0 && this.made[at - d]) return this.made[at - d];
      if (at + d <= finest && this.made[at + d]) return this.made[at + d];
    }
    return null;
  }

  private load(view: ValueDetailView, at: number): void {
    if (this.loading.has(at)) return;
    this.loading.add(at);
    const spec = this.levels.levels[at];
    const ids = specBufferIds(spec);
    void this.source.ensure(ids).then(() => {
      if (this.gone || !ids.every((id) => this.source.has(id))) return;
      this.made[at] = this.decode(spec);
      view.requestRender();
    });
  }

  /** Ask Python for the samples of three views of time around the view (those of level k
   * when there are many). One at a time; not again for a view inside the last one asked for. */
  private askFor(view: ValueDetailView, k: number, ta: number, tb: number): void {
    const ask = this.ask;
    if (!ask || this.asking) return;
    const last = this.asked;
    if (last && last.k >= k && last.range[0] <= ta && last.range[1] >= tb) return;
    const span = tb - ta;
    const range: [number, number] = [ta - span, tb + span];
    this.asking = true;
    this.asked = { k, range };
    ask(this.spec.name, "time", range, k)
      .then(async (answer) => {
        const ids = specBufferIds(answer.spec, true);
        await this.source.ensure(ids);
        if (this.gone || !ids.every((id) => this.source.has(id))) return;
        this.window = { samples: this.decode(answer.spec as ValuesLayerSpec), k: answer.k, range: answer.range };
        // every sample there: no need to ask again inside it
        if (answer.k === null) this.asked = { k: Infinity, range: answer.range };
      })
      .catch(() => {})
      .finally(() => {
        this.asking = false;
        if (!this.gone) view.requestRender();
      });
  }
}

// ------------------------------------------------------------------ intervals layers

/** What an intervals layer sent as levels needs of the view. */
export interface BarDetailView {
  readonly xscale: XScale;
  readonly camera: { left: number; right: number; span: number; scale: number };
  readonly theme: { accent: string };
  requestRender(): void;
  /** The exact times of the order from rank `offset` (a window's). */
  setSequence(offset: number, times: Float64Array): void;
}

/** A level's bars are merged where shorter than this many px. */
export const MERGE_PX = 2;

/**
 * The levels and windows of one intervals layer of many bars. Level k has the bars at least
 * top / 4^k long, and the shorter ones merged per lane, sub-row and bin of that width (one
 * bar over them, as opaque as they cover it); each frame draws the coarsest level whose bins
 * are at most MERGE_PX wide. Finer than the levels sent, or with few bars in view, the view
 * asks for a window: every bar there when few enough, else those of a finer level there.
 */
export class BarDetail {
  readonly levels: BarLevelsSpec;
  private readonly made: Record<XScale, (BarLayer | null)[]>;
  private readonly loading = new Set<string>();
  private window: { bars: BarLayer; scale: XScale; k: number | null; range: [number, number] } | null = null;
  private asking = false;
  private asked: { scale: XScale; k: number; range: [number, number] } | null = null;
  private gone = false;

  constructor(
    readonly spec: IntervalsLayerSpec,
    private readonly source: DataSource,
    private readonly ask: WindowAsk | null,
    private readonly accent: () => string,
  ) {
    this.levels = spec.levels!;
    this.made = { time: this.levels.time.levels.map(() => null), order: this.levels.order.levels.map(() => null) };
  }

  /** The buffers of the coarsest level of a scale (loaded with the spec, for a first frame). */
  firstIds(scale: XScale): string[] {
    const first = this.levels[scale].levels[0];
    return first ? specBufferIds(first) : [];
  }

  /** Decode the coarsest level of a scale now (its buffers are there). */
  preload(scale: XScale): void {
    const spec = this.levels[scale].levels[0];
    if (spec && !this.made[scale][0] && specBufferIds(spec).every((id) => this.source.has(id))) this.made[scale][0] = this.decode(spec);
  }

  destroy(): void {
    this.gone = true;
  }

  /** Every renderer key this layer's bars use (those kept). */
  keys(into: Set<string>): void {
    for (const scale of ["time", "order"] as XScale[]) for (const b of this.made[scale]) if (b) into.add(b.draw.key);
    if (this.window) into.add(this.window.bars.draw.key);
  }

  private decode(spec: IntervalsLayerSpec): BarLayer {
    const b = new BarLayer(decodeBars(spec, this.source), this.accent());
    b.detail = this;
    return b;
  }

  /** The bars to draw in this frame (`shown`: those drawn now, as culled last frame), or
   * null when none is loaded yet. Starts loading the level the view wants, and asks for
   * windows. */
  frame(view: BarDetailView, shown: BarLayer): BarLayer | null {
    const scale = view.xscale;
    const cam = view.camera;
    const a = cam.left;
    const b = cam.right;
    const p = this.levels[scale];
    const want = barsLevel(p.top, cam.scale);
    const w = this.window;
    const covers = !!w && w.scale === scale && w.range[0] <= a && w.range[1] >= b;
    if (w && covers && (w.k === null || w.k >= want)) return w.bars;
    const list = p.levels;
    if (!list.length) return null;
    const finest = list.length - 1;
    let at = finest;
    for (let i = finest; i >= 0; i--) if (list[i].k >= want) at = i;
    const made = this.made[scale];
    if (!made[at]) this.load(view, scale, at);
    if (this.levels.windows) {
      // finer than the levels sent, or few bars in view: their window
      let few = false;
      if (shown.detail === this && shown.data.n && shown === made[at]) {
        const n = shown.data.n;
        const vis = shown.draw.visible;
        let total = 0;
        for (let j = 0; j < shown.draw.visibleCount && total <= this.levels.raw; j++) total += n[vis[j]];
        few = total > 0 && total <= this.levels.raw;
      }
      if (want > list[finest].k || few) this.askFor(view, scale, Math.max(want, list[finest].k + 1), a, b);
      if (w && covers) return w.bars;
    }
    if (made[at]) return made[at];
    for (let d = 1; d <= finest; d++) {
      if (at - d >= 0 && made[at - d]) return made[at - d];
      if (at + d <= finest && made[at + d]) return made[at + d];
    }
    return null;
  }

  private load(view: BarDetailView, scale: XScale, at: number): void {
    const key = `${scale}:${at}`;
    if (this.loading.has(key)) return;
    this.loading.add(key);
    const spec = this.levels[scale].levels[at];
    const ids = specBufferIds(spec);
    void this.source.ensure(ids).then(() => {
      if (this.gone || !ids.every((id) => this.source.has(id))) return;
      this.made[scale][at] = this.decode(spec);
      view.requestRender();
    });
  }

  /** Ask Python for the bars of three views around the view (those of level k when there are
   * many). One at a time; not again for a view inside the last one asked for. */
  private askFor(view: BarDetailView, scale: XScale, k: number, a: number, b: number): void {
    const ask = this.ask;
    if (!ask || this.asking) return;
    const last = this.asked;
    if (last && last.scale === scale && last.k >= k && last.range[0] <= a && last.range[1] >= b) return;
    const span = b - a;
    const range: [number, number] = [a - span, b + span];
    this.asking = true;
    this.asked = { scale, k, range };
    ask(this.spec.name, scale, range, k)
      .then(async (answer) => {
        const ids = specBufferIds(answer.spec, true);
        if (answer.sequence) ids.push(answer.sequence.times.id);
        await this.source.ensure(ids);
        if (this.gone || !ids.every((id) => this.source.has(id))) return;
        if (answer.sequence) view.setSequence(answer.sequence.offset, new Float64Array(this.source.get(answer.sequence.times.id)));
        this.window = { bars: this.decode(answer.spec as IntervalsLayerSpec), scale, k: answer.k, range: answer.range };
        if (answer.k === null) this.asked = { scale, k: Infinity, range: answer.range };
      })
      .catch(() => {})
      .finally(() => {
        this.asking = false;
        if (!this.gone) view.requestRender();
      });
  }
}
