// Notes (Timeline.notes) as Python sends them (ticks, places in the order, lane indices):
// annotations (bands over a time range, or a line at a time), connections (arrows from an
// edge of a mark to an edge of another) and measures (dimension lines with the time between
// their ends). The key `a` and then a drag (or a click) makes a note; the key `c` on one mark
// and then on another makes an arrow; measuring (measure.ts) makes measures. They go to
// Python, which keeps them; a page keeps its own measures until it is closed.

import { globalIndex, type Hit } from "./common";
import type { TimelineView } from "./view";

export type Side = "start" | "end";

/** An end of a note: a mark's edge (`side`, `layer`, `index`), or a time (no side, and no
 * lane unless the note has one). `x`: ticks; `r`: the place in the order (null: no order). */
export interface NoteEnd {
  x: number;
  r: number | null;
  lane: number | null;
  side: Side | null;
  layer?: string;
  index?: number;
}

export interface NoteBand {
  x0: number;
  x1: number;
  /** Places in the order (an edge's own, a time's between the instants around it). */
  r0?: number | null;
  r1?: number | null;
  /** A note at one time (a line), not over a range. */
  point: boolean;
  /** The lane it is in; null: across all lanes. */
  lane: number | null;
  text: string;
  color: string | null;
  id?: number;
}

export interface NoteArrow {
  a: NoteEnd;
  b: NoteEnd;
  text: string;
  color: string | null;
  id?: number;
}

export interface NoteMeasure {
  a: NoteEnd;
  b: NoteEnd;
  /** b − a, ticks. */
  span: number;
  /** Instants of the order strictly between the ends (null: no order). */
  events: number | null;
  /** The lane its line is in when its ends say none; null: theirs, or the top. */
  lane: number | null;
  /** Its own text (`{time}`, `{events}` filled in); null: the time between. */
  text: string | null;
  color: string | null;
  /** Its index in Python's list of notes; a page's own measures: −1, −2, ... */
  id: number;
}

export interface Notes {
  bands?: NoteBand[];
  arrows?: NoteArrow[];
  measures?: NoteMeasure[];
}

/** An annotation made in the plot, for Python (ticks; x1 null: at one time). */
export interface NewNote {
  x0: number;
  x1: number | null;
  lane: number | null;
  text: string;
}

/** A mark, as Python knows it: its layer's name and its index among the layer's, and an
 * edge of it when one is meant. */
export interface MarkRef {
  layer: string;
  index: number;
  side?: Side;
}

type Rect = { x: number; y: number; w: number; h: number };

/** The length of a measure's arrowheads (px). */
export const ARROW_LEN = 7;

/** The mark of a hit, as Python knows it (null: a bin, or merged bars). */
export function markOf(view: TimelineView, h: Hit | null): MarkRef | null {
  if (!h || h.bin || h.val) return null;
  if (h.bar) {
    const b = view.bars[h.layer];
    const index = b?.globalIndex(h.index) ?? -1;
    return index >= 0 ? { layer: b.data.spec.name, index } : null;
  }
  const l = view.layers[h.layer];
  return l ? { layer: l.data.spec.name, index: globalIndex(l, h.index) } : null;
}

/** A time (ticks) on the scale shown: itself, or its place in the order. */
export function place(view: TimelineView, t: number): number | null {
  if (view.xscale !== "order") return t;
  return view.seq?.count ? view.seq.lower(t) - 0.5 : null;
}

/** Where an end is on the scale shown (null: not on the Order scale). */
export function endX(view: TimelineView, e: NoteEnd): number | null {
  return view.xscale === "order" ? e.r : e.x;
}

function bandPlace(view: TimelineView, x: number, r: number | null | undefined): number | null {
  if (view.xscale !== "order") return x;
  return r ?? place(view, x);
}

/** The row a lane shows in: its own, or that of the lane it is folded into (null: none). */
export function rowOf(view: TimelineView, lane: number | null): number | null {
  if (lane === null || lane < 0 || lane >= view.slot.length) return null;
  if (view.slot[lane] >= 0) return view.slot[lane];
  const size = view.spec?.lanes.tree?.size ?? [];
  for (let k = Math.min(lane, size.length) - 1; k >= 0; k--) {
    if (view.slot[k] >= 0 && k + size[k] > lane) return view.slot[k];
  }
  return null;
}

function label(view: TimelineView, ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string, plot: Rect): void {
  const w = ctx.measureText(text).width + 8;
  const lx = Math.max(plot.x + 1, Math.min(x, plot.x + plot.w - w - 1));
  ctx.globalAlpha = 0.9;
  ctx.fillStyle = view.theme.bg;
  ctx.fillRect(lx, y, w, view.fs + 4);
  ctx.globalAlpha = 1;
  ctx.fillStyle = color;
  ctx.fillText(text, lx + 4, y + view.fs);
}

/** How many instants of the order lie strictly between two places (null: no order). */
export function between(ra: number | null, rb: number | null): number | null {
  if (ra === null || rb === null) return null;
  return Math.max(0, Math.ceil(Math.max(ra, rb)) - Math.floor(Math.min(ra, rb)) - 1);
}

/** A measure's label: its text with `{time}` and `{events}` filled in; without text the
 * time, and on the Order scale the events between too. */
export function measureText(view: TimelineView, m: NoteMeasure): string {
  const time = view.axis ? view.axis.formatMeasure(Math.abs(m.span)) : String(Math.abs(m.span));
  const n = m.events;
  const count = n === null ? "" : `${n.toLocaleString("en-US").replace(/,/g, " ")} event${n === 1 ? "" : "s"}`;
  if (m.text === null || m.text === undefined) return view.xscale === "order" && count ? `${time} · ${count}` : time;
  return m.text.replace(/\{time\}/g, time).replace(/\{events\}/g, count);
}

/** A measure as drawn: where its ends are (px), the rows of their marks, the row of its line
 * (null: the top of the plot), its text and colour; after layout, its line's height and its
 * label's left. */
export interface MeasureLaid {
  m: NoteMeasure;
  xa: number;
  xb: number;
  rows: [number | null, number | null];
  row: number | null;
  text: string;
  tw: number;
  color: string;
  y: number;
  lx: number;
}

/** Where measures' lines go (Python's layout_measures): per row (null: the top of the
 * plot), each measure takes the first level whose earlier lines and labels end before it
 * starts; its label goes at its middle, or beyond its right end when it does not fit. */
export function layoutMeasures(view: TimelineView, ctx: CanvasRenderingContext2D, measures: NoteMeasure[], plot: Rect, laneTop: number): MeasureLaid[] {
  const c = view.camera;
  const px = (v: number) => plot.x + (v - c.left) * c.scale;
  const geoms: Omit<MeasureLaid, "y" | "lx">[] = [];
  for (const m of measures) {
    const a = endX(view, m.a);
    const b = endX(view, m.b);
    if (a === null || b === null) continue;
    const rows: [number | null, number | null] = [rowOf(view, m.a.lane), rowOf(view, m.b.lane)];
    let row = m.lane !== null ? rowOf(view, m.lane) : null;
    if (row === null) {
      const shown = rows.filter((r): r is number => r !== null);
      row = shown.length ? Math.min(...shown) : null;
    }
    const text = measureText(view, m);
    geoms.push({ m, xa: px(a), xb: px(b), rows, row, text, tw: ctx.measureText(text).width + 8, color: m.color ?? view.theme.accent });
  }
  geoms.sort((p, q) => Math.min(p.xa, p.xb) - Math.min(q.xa, q.xb));
  const step = view.fs + 8;
  const levels = new Map<number | null, number[]>();
  const out: MeasureLaid[] = [];
  for (const g of geoms) {
    const lo = Math.min(g.xa, g.xb);
    const hi = Math.max(g.xa, g.xb);
    let lx: number;
    if (g.tw + 2 * ARROW_LEN <= hi - lo) lx = (lo + hi) / 2 - g.tw / 2;
    else if (hi + 6 + g.tw <= plot.x + plot.w) lx = hi + 6;
    else lx = lo - 6 - g.tw;
    lx = Math.max(plot.x + 1, Math.min(lx, plot.x + plot.w - g.tw - 1));
    const left = Math.min(lo, lx);
    const right = Math.max(hi, lx + g.tw);
    let ends = levels.get(g.row);
    if (!ends) levels.set(g.row, (ends = []));
    let k = ends.findIndex((e) => e < left - 4);
    if (k < 0) {
      k = ends.length;
      ends.push(right);
    } else ends[k] = right;
    const top = g.row === null ? plot.y : laneTop + g.row * view.laneH;
    out.push({ ...g, y: top + 3 + (view.fs + 4) / 2 + k * step, lx });
  }
  return out;
}

function head(ctx: CanvasRenderingContext2D, x: number, y: number, tip: number): void {
  const base = x - tip * ARROW_LEN;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(base, y - 3.5);
  ctx.lineTo(base, y + 3.5);
  ctx.closePath();
  ctx.fill();
}

/** A measure: an extension line from each end's mark to the line's height (a short tick
 * through the line at a time), the line with an arrowhead at each end (outside, pointing in,
 * when the line is short), the label on the background. Selected: thicker, with handles. */
function drawMeasure(view: TimelineView, ctx: CanvasRenderingContext2D, d: MeasureLaid, plot: Rect, laneTop: number, selected: boolean): void {
  const y = d.y;
  const lo = Math.min(d.xa, d.xb);
  const hi = Math.max(d.xa, d.xb);
  if (hi < plot.x - 1 || lo > plot.x + plot.w + 1 || y < plot.y || y > plot.y + plot.h) return;
  ctx.strokeStyle = d.color;
  ctx.fillStyle = d.color;
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 2]);
  const ends: [number, number | null][] = [[d.xa, d.rows[0]], [d.xb, d.rows[1]]];
  for (const [x, row] of ends) {
    let y0 = y - 5;
    let y1 = y + 5;
    if (row !== null) {
      const yc = laneTop + (row + 0.5) * view.laneH;
      const away = y > yc ? 1 : -1;
      y0 = yc + away * Math.min(6, view.laneH / 4);
      y1 = y + away * 4;
    }
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + 0.5, y0);
    ctx.lineTo(Math.round(x) + 0.5, y1);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  const inside = hi - lo >= 2 * ARROW_LEN + 2;
  // a band of the background under the line and its heads: it shows over marks
  const reach = inside ? 0 : 2 * ARROW_LEN;
  ctx.globalAlpha = 0.85;
  ctx.strokeStyle = view.theme.bg;
  ctx.lineWidth = 7;
  ctx.beginPath();
  ctx.moveTo(lo - reach, y);
  ctx.lineTo(hi + reach, y);
  ctx.stroke();
  ctx.globalAlpha = 1;
  ctx.strokeStyle = d.color;
  ctx.lineWidth = selected ? 2.5 : 1.5;
  ctx.beginPath();
  ctx.moveTo(lo, y);
  ctx.lineTo(hi, y);
  ctx.stroke();
  for (const [x, way] of [[lo, -1], [hi, 1]] as const) {
    if (inside) head(ctx, x, y, way);
    else {
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + way * 2 * ARROW_LEN, y);
      ctx.stroke();
      head(ctx, x, y, -way);
    }
  }
  if (selected) {
    for (const x of [d.xa, d.xb]) {
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = view.theme.bg;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    ctx.fillStyle = d.color;
  }
  if (d.text) label(view, ctx, d.text, d.lx, y - (view.fs + 4) / 2, d.color, plot);
}

/** An arrow from one edge to another: it leaves a start leftwards and an end rightwards, and
 * comes into a start from the left and into an end from the right. */
function drawArrow(view: TimelineView, ctx: CanvasRenderingContext2D, n: NoteArrow, plot: Rect, laneTop: number): void {
  const c = view.camera;
  const px = (v: number) => plot.x + (v - c.left) * c.scale;
  const ra = rowOf(view, n.a.lane);
  const rb = rowOf(view, n.b.lane);
  const a = endX(view, n.a);
  const b = endX(view, n.b);
  if (ra === null || rb === null || a === null || b === null) return;
  const xa = px(a);
  const xb = px(b);
  const ya = laneTop + (ra + 0.5) * view.laneH;
  const yb = laneTop + (rb + 0.5) * view.laneH;
  if (Math.max(xa, xb) < plot.x || Math.min(xa, xb) > plot.x + plot.w) return;
  const out = (n.a.side ?? "end") === "end" ? 1 : -1;
  const into = (n.b.side ?? "start") === "start" ? 1 : -1;
  const color = n.color ?? view.theme.accent;
  const bend = Math.max(24, Math.min(160, Math.abs(xb - xa) / 2));
  const ex = xb - into * 3;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(xa, ya);
  ctx.bezierCurveTo(xa + out * bend, ya, ex - into * bend, yb, ex, yb);
  ctx.stroke();
  // the head, along the curve's end (horizontal)
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(xb, yb);
  ctx.lineTo(xb - into * 8, yb - 4);
  ctx.lineTo(xb - into * 8, yb + 4);
  ctx.closePath();
  ctx.fill();
  if (n.text) {
    const w = ctx.measureText(n.text).width + 8;
    label(view, ctx, n.text, (xa + xb) / 2 - w / 2, (ya + yb) / 2 - view.fs / 2 - 2, color, plot);
  }
}

/** The measures to draw: Python's and the page's own, one end moved while it is dragged,
 * and the one being made (its second end at the pointer). */
export function measuresShown(view: TimelineView): NoteMeasure[] {
  const out = [...(view.notes.measures ?? []), ...view.localMeasures].map((m) => {
    const h = view.handleDrag;
    if (!h || h.id !== m.id) return m;
    const moved = { ...m, [h.end]: h.to };
    return { ...moved, span: moved.b.x - moved.a.x, events: between(moved.a.r, moved.b.r) };
  });
  const draft = view.measureDraft;
  if (draft?.b) out.push({ a: draft.a, b: draft.b, span: draft.b.x - draft.a.x, events: between(draft.a.r, draft.b.r), lane: draft.lane, text: null, color: null, id: Number.NaN });
  return out;
}

/** The notes: translucent bands with their text at the top (a line for a note at one time),
 * arrows with their text at the middle, measures, and lines across all lanes over them. */
export function drawNotes(view: TimelineView, ctx: CanvasRenderingContext2D, plot: Rect, laneTop: number): void {
  const notes = view.notes;
  const measures = measuresShown(view);
  view.measureHits = [];
  if (!notes.bands?.length && !notes.arrows?.length && !measures.length && !view.snapEdge) return;
  const c = view.camera;
  const px = (v: number) => plot.x + (v - c.left) * c.scale;
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  ctx.font = view.font(-1);
  ctx.textBaseline = "alphabetic";
  const lines: NoteBand[] = [];
  for (const n of notes.bands ?? []) {
    if (n.point && n.lane === null) {
      lines.push(n);
      continue;
    }
    const a = bandPlace(view, n.x0, n.r0);
    const b = bandPlace(view, n.x1, n.r1);
    if (a === null || b === null) continue;
    let y0 = plot.y;
    let y1 = plot.y + plot.h;
    if (n.lane !== null) {
      const row = rowOf(view, n.lane);
      if (row === null) continue;
      y0 = laneTop + row * view.laneH + 1;
      y1 = y0 + view.laneH - 2;
    }
    const xa = px(a);
    const xb = n.point ? xa : Math.max(px(b), xa + 1);
    if (xb < plot.x - 200 || xa > plot.x + plot.w || y1 < plot.y || y0 > plot.y + plot.h) continue;
    const color = n.color ?? view.theme.accent;
    ctx.strokeStyle = color;
    if (n.point) {
      ctx.lineWidth = 1.5;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(Math.round(xa) + 0.5, y0);
      ctx.lineTo(Math.round(xa) + 0.5, y1);
      ctx.stroke();
      ctx.setLineDash([]);
    } else {
      ctx.globalAlpha = 0.1;
      ctx.fillStyle = color;
      ctx.fillRect(xa, y0, xb - xa, y1 - y0);
      ctx.globalAlpha = 0.7;
      ctx.lineWidth = 1;
      ctx.strokeRect(xa + 0.5, y0 + 0.5, Math.max(0, xb - xa - 1), y1 - y0 - 1);
      ctx.globalAlpha = 1;
    }
    if (n.text) label(view, ctx, n.text, xa + 3, Math.max(plot.y, y0) + 2, color, plot);
  }
  for (const n of notes.arrows ?? []) drawArrow(view, ctx, n, plot, laneTop);
  const laid = layoutMeasures(view, ctx, measures, plot, laneTop);
  for (const d of laid) drawMeasure(view, ctx, d, plot, laneTop, d.m.id === view.selectedMeasure);
  view.measureHits = laid.filter((d) => !Number.isNaN(d.m.id));
  // the edge a measure's end would take: a short tick on it
  const snap = view.snapEdge;
  if (snap) {
    const x = endX(view, snap);
    const row = rowOf(view, snap.lane);
    if (x !== null && row !== null) {
      const yc = laneTop + (row + 0.5) * view.laneH;
      const half = Math.max(6, view.laneH * 0.35);
      ctx.strokeStyle = view.theme.accent;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(Math.round(px(x)) + 0.5, yc - half);
      ctx.lineTo(Math.round(px(x)) + 0.5, yc + half);
      ctx.stroke();
    }
  }
  ctx.restore();
  if (!lines.length) return;
  // lines across all lanes (a time such as now): dashed, the label on the background, as
  // markers once were; the label may sit over the axis's lower edge
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, 0, plot.w, plot.y + plot.h);
  ctx.clip();
  ctx.font = view.font(-1);
  ctx.textBaseline = "alphabetic";
  for (const n of lines) {
    const at = bandPlace(view, n.x0, n.r0);
    if (at === null) continue;
    const x = Math.round(px(at)) + 0.5;
    if (x < plot.x - 1 || x > plot.x + plot.w + 1) continue;
    const color = n.color ?? view.theme.select;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    ctx.moveTo(x, plot.y);
    ctx.lineTo(x, plot.y + plot.h);
    ctx.stroke();
    ctx.setLineDash([]);
    if (n.text) {
      const w = ctx.measureText(n.text).width + 8;
      const lx = Math.min(x + 3, plot.x + plot.w - w);
      const y = plot.y + 3;
      ctx.fillStyle = view.theme.bg;
      ctx.fillRect(lx, y, w, view.fs + 4);
      ctx.fillStyle = color;
      ctx.fillText(n.text, lx + 4, y + view.fs);
    }
  }
  ctx.restore();
}

/** Where the text of a new note is typed: an input over the plot, at the note. Enter keeps
 * it (`done(text)`), Esc or leaving it drops it (`done(null)`). */
export function askText(view: TimelineView, x: number, y: number, done: (text: string | null) => void): void {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "atl-note-input";
  input.placeholder = "Note (Enter keeps it, Esc drops it)";
  input.setAttribute("aria-label", "The annotation's text");
  input.style.left = `${Math.max(0, x)}px`;
  input.style.top = `${Math.max(0, y)}px`;
  let finished = false;
  const finish = (text: string | null) => {
    if (finished) return;
    finished = true;
    input.remove();
    done(text);
    view.root.focus({ preventScroll: true });
  };
  for (const type of ["pointerdown", "wheel", "dblclick"]) input.addEventListener(type, (e) => e.stopPropagation());
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      finish(input.value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      finish(null);
    }
  });
  input.addEventListener("blur", () => finish(null));
  view.stage.append(input);
  input.focus();
}
