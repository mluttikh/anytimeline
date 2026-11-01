// Notes (Timeline.notes) as Python sends them (ticks, places in the order, lane indices):
// annotations (bands over a time range, or a line at a time), connections (arrows from an
// edge of a mark to an edge of another) and measures (dimension lines with the time between
// their ends). The key `a` and then a drag (or a click) makes a note; the key `c` on one mark
// and then on another makes an arrow; measuring (measure.ts) makes measures. They go to
// Python, which keeps them; a page keeps its own measures until it is closed.

import { globalIndex, type Hit } from "./common";
import { barView } from "./drawing";
import { lowerBound } from "./scene";
import { changeText, fillMeasure } from "./fields";
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
  /** A sample's value (an end that is a sample of a values layer; null: a gap). */
  value?: number | null;
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

/** Where a measure's line goes (Python's MeasurePlace). */
export type MeasurePlace = "auto" | "top" | "middle" | "bottom" | "between" | "header" | "footer";
export type MeasureLabel = "auto" | "on" | "above" | "below" | "start" | "end" | "hover";
export type MeasureEnds = "arrows" | "ticks" | "dots" | "none";
export type MeasureKind = "time" | "value" | "both";
export type MeasureExtend = "mark" | "lanes" | "none";

export interface NoteMeasure {
  a: NoteEnd;
  b: NoteEnd;
  /** b − a, ticks. */
  span: number;
  /** Instants of the order strictly between the ends (null: no order). */
  events: number | null;
  /** b's value − a's, when both are samples of one values layer (else null or absent). */
  change?: number | null;
  /** The lane its line is in when its ends say none; null: theirs, or the top. */
  lane: number | null;
  /** Its own text (`{time}`, `{events}`, `{change}` filled in); null: the time between. */
  text: string | null;
  color: string | null;
  /** Its index in Python's list of notes; a page's own measures: −1, −2, ... */
  id: number;
  /** Where its line goes: a place, or a value on a values layer (absent: "auto"). */
  at?: MeasurePlace | { value: number; layer: string };
  /** Its level (null or absent: the first free one). */
  level?: number | null;
  /** Pixels its line moves down after the layout. */
  nudge?: number;
  /** Where its label goes, what its line ends in, its extension lines (absent: "auto",
   * "arrows", "mark"). */
  label?: MeasureLabel;
  ends?: MeasureEnds;
  extend?: MeasureExtend;
  /** Its text as written, when Python filled in `{a.col}` or `{b.col}` (to edit it). */
  raw?: string | null;
  /** Made by a rule of measures (its note is the rule: `id`): which rule, and this one's
   * index among its measures. */
  rule?: "each" | "gaps" | "chain" | "from";
  part?: number;
  /** A chain's or a baseline's measure: its offset in levels in the rule's group. */
  group?: number;
  /** Longer than its limit: drawn in the theme's "over" colour. */
  over?: boolean;
  /** Between two samples: the time (absent), the change ("value"), or both (an L). */
  kind?: MeasureKind;
}

/** What a change of a measure in the plot sets (absent: unchanged). */
export interface MeasureChange {
  at?: MeasurePlace | { value: number; layer: string };
  /** A lane's index; null: its ends' lane. */
  lane?: number | null;
  level?: number | null;
  /** null: the time between. */
  text?: string | null;
  label?: MeasureLabel;
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
/** Half the length of a measure's oblique tick, and the radius of its end dot (px). */
const TICK = 4;
const END_DOT = 3;
/** The radius of the dot on a sample a measure ends at (px). */
const SAMPLE_DOT = 2.5;

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

/** A measure's label: its text with its fields filled in (fields.ts); without text the
 * time, on the Order scale the events between too, and between samples the change in value. */
export function measureText(view: TimelineView, m: NoteMeasure): string {
  const values = { span: m.span, a: m.a.x, b: m.b.x, events: m.events, change: m.change ?? null };
  return fillMeasure(view.axis, m.text ?? null, values, view.xscale === "order");
}

export { changeText };

/** The change in value from end a to end b: both samples of one values layer (else null). */
export function changeOf(a: NoteEnd, b: NoteEnd): number | null {
  if (a.value === undefined || a.value === null || b.value === undefined || b.value === null || a.layer !== b.layer) return null;
  return b.value - a.value;
}

/** What laying out a measure needs: where its ends are (px, and on the scale shown), the
 * rows of their marks and of its line (null: none shown), where it goes (`valueY`: the
 * height of its value, for `at` "value"), its level and nudge, its text and its width. */
export interface MeasureGeom {
  xa: number;
  xb: number;
  ua: number;
  ub: number;
  rows: [number | null, number | null];
  /** Where an end that is a sample is (px; null: the middle of its mark's row). */
  ys: [number | null, number | null];
  row: number | null;
  at: MeasurePlace | "value";
  valueY: number | null;
  level: number | null;
  nudge: number;
  text: string;
  tw: number;
  /** Where its label goes (absent: "auto"). */
  label?: MeasureLabel;
  /** A group laid out as one (a rule's chain or baseline: its note's index), and this
   * one's offset in levels in it (absent: none, 0). */
  group?: number | null;
  off?: number;
}

/** A measure as drawn: its geometry, the band or lane edge it stacks from (`place`), its
 * level, its line's height and its label's left (null: no room; shown when hovered or
 * selected). */
export type Laid<G extends MeasureGeom> = G & { place: string; k: number; y: number; lx: number | null; ly: number };

export interface MeasureLaid extends MeasureGeom {
  m: NoteMeasure;
  color: string;
  place: string;
  k: number;
  y: number;
  lx: number | null;
  /** Its label's top. */
  ly: number;
}

/** Where the plot is, for measures: the lanes' top (scrolled), their height, and the tops of
 * the header band (above the lanes) and the footer band (below them). */
export interface MeasureFrame {
  fs: number;
  plot: Rect;
  laneTop: number;
  laneH: number;
  headTop: number;
  footTop: number;
}

/** How many levels of measures a lane holds at the top before "auto" ones go to the header. */
export function laneLevels(laneH: number, fs: number): number {
  return Math.max(1, Math.floor((laneH - 6 - (fs + 4)) / (fs + 8)) + 1);
}

/** The height of a band of `levels` levels of measures (0: none, no band). */
export function bandHeight(levels: number, fs: number): number {
  return levels > 0 ? 6 + fs + 4 + (levels - 1) * (fs + 8) : 0;
}

type StackItem = { lo: number; hi: number; level: number | null; i: number; cap?: number; group?: number | null; off?: number };

/** Levels for measures of one place: those with a level keep it; the others, by their
 * earlier end (on the scale shown, so zooming never changes them), take the first level
 * where they overlap none (touching ends may share one). A group (a chain, a baseline) goes
 * as one: each member at the first level free for all, plus its offset. One whose level
 * would be `cap` or more takes none (-1): it goes elsewhere, with its group. */
function stack(items: StackItem[]): Map<number, number> {
  const out = new Map<number, number>();
  const ends: number[] = [];
  const pinned: [number, number][][] = [];
  for (const it of items) {
    if (it.level === null) continue;
    (pinned[it.level] ??= []).push([it.lo, it.hi]);
    out.set(it.i, it.level);
  }
  const units: { lo: number; i: number; members: StackItem[] }[] = [];
  const grouped = new Map<number, { lo: number; i: number; members: StackItem[] }>();
  for (const it of items) {
    if (it.level !== null) continue;
    const g = it.group ?? null;
    let u = g === null ? undefined : grouped.get(g);
    if (!u) {
      u = { lo: it.lo, i: it.i, members: [] };
      units.push(u);
      if (g !== null) grouped.set(g, u);
    }
    u.members.push(it);
    u.lo = Math.min(u.lo, it.lo);
    u.i = Math.min(u.i, it.i);
  }
  units.sort((p, q) => p.lo - q.lo || p.i - q.i);
  for (const u of units) {
    const free = (k: number) =>
      u.members.every((m) => {
        const l = k + (m.off ?? 0);
        return (ends[l] ?? -Infinity) <= u.lo && !(pinned[l] ?? []).some(([lo, hi]) => lo < m.hi && m.lo < hi);
      });
    let k = 0;
    while (!free(k)) k++;
    const top = k + Math.max(...u.members.map((m) => m.off ?? 0));
    const cap = u.members[0].cap;
    if (cap !== undefined && top >= cap) {
      for (const m of u.members) out.set(m.i, -1);
      continue;
    }
    for (const m of u.members) {
      const l = k + (m.off ?? 0);
      ends[l] = Math.max(ends[l] ?? -Infinity, m.hi);
      out.set(m.i, l);
    }
  }
  return out;
}

/** What takes room on a level of measures: their lines, and the labels put beside them.
 * `free(a, b)`: whether [a, b], with 4 px either side, overlaps none (a label beside a line
 * never overlaps its own line). Lines are sorted with the furthest right end so far, labels
 * kept sorted; so a level of thousands of measures is quick (Python's `_LevelSpans`). */
class LevelSpans {
  private lineL: number[];
  private lineR: number[];
  private labL: number[] = [];
  private labR: number[] = [];
  private widest = 0;

  constructor(lines: [number, number][]) {
    lines.sort((p, q) => p[0] - q[0]);
    this.lineL = lines.map((s) => s[0]);
    let most = -Infinity;
    this.lineR = lines.map((s) => (most = Math.max(most, s[1])));
  }

  free(a: number, b: number): boolean {
    const lo = a - 4;
    const hi = b + 4;
    const n = firstAtLeast(this.lineL, hi); // lines with l < hi
    if (n > 0 && this.lineR[n - 1] > lo) return false;
    for (let j = firstAtLeast(this.labL, hi) - 1; j >= 0 && this.labL[j] >= lo - this.widest - 1; j--) {
      if (this.labR[j] > lo) return false;
    }
    return true;
  }

  add(l: number, r: number): void {
    let j = firstAtLeast(this.labL, l);
    while (j < this.labL.length && this.labL[j] === l) j++;
    this.labL.splice(j, 0, l);
    this.labR.splice(j, 0, r);
    this.widest = Math.max(this.widest, r - l);
  }
}

/** The first index of sorted `xs` whose value is `x` or more. */
function firstAtLeast(xs: number[], x: number): number {
  let lo = 0;
  let hi = xs.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Where measures' lines go (Python's place_measures): per place and row, levels from
 * `stack`; "auto" ones the lane cannot hold continue in the header; a measure with no row
 * shown goes to the header. Then labels: on the line where they fit, else beside it where
 * that is free on its level, else none (shown when hovered or selected). `head` and `foot`:
 * the heights of the bands (px; 0: none), with room for a label above a band's first level
 * or below its last. */
export function placeMeasures<G extends MeasureGeom>(geoms: G[], f: MeasureFrame): { laid: Laid<G>[]; head: number; foot: number } {
  const h = f.fs + 4;
  const step = f.fs + 8;
  const cap = laneLevels(f.laneH, f.fs);
  const kind = geoms.map((g) => {
    let at: string = g.at;
    if (at === "value" && g.valueY === null) at = "top";
    if (at !== "header" && at !== "footer" && g.row === null) at = "header";
    return at;
  });
  const lo = geoms.map((g) => Math.min(g.ua, g.ub));
  const hi = geoms.map((g) => Math.max(g.ua, g.ub));
  const key = (i: number) => {
    const at = kind[i] === "auto" ? "top" : kind[i];
    if (at === "header" || at === "footer") return at;
    return at === "value" ? `value ${geoms[i].row} ${geoms[i].valueY}` : `${at} ${geoms[i].row}`;
  };
  const groups = new Map<string, number[]>();
  geoms.forEach((_, i) => {
    const k = key(i);
    if (k === "header" || k === "footer") return;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(i);
  });
  const level = new Map<number, number>();
  const place = new Map<number, string>();
  const over: number[] = [];
  const item = (i: number, level: number | null, withCap: boolean): StackItem => ({ lo: lo[i], hi: hi[i], level, i, cap: withCap && kind[i] === "auto" ? cap : undefined, group: geoms[i].group ?? null, off: geoms[i].off ?? 0 });
  for (const [k, members] of groups) {
    const got = stack(members.map((i) => item(i, geoms[i].level, true)));
    for (const i of members) {
      const l = got.get(i)!;
      if (l < 0) over.push(i);
      else {
        level.set(i, l);
        place.set(i, k);
      }
    }
  }
  const bands = { header: 0, footer: 0 };
  for (const band of ["header", "footer"] as const) {
    const own = geoms.map((_, i) => i).filter((i) => key(i) === band);
    let got = stack(own.map((i) => item(i, geoms[i].level, false)));
    const members = [...own];
    if (band === "header" && over.length) {
      // the lanes' overflow comes after the header's own measures, around them
      members.push(...over);
      const lanes = new Set(over);
      got = stack(members.map((i) => item(i, lanes.has(i) ? null : got.get(i)!, false)));
    }
    for (const i of members) {
      level.set(i, got.get(i)!);
      place.set(i, band);
      bands[band] = Math.max(bands[band], got.get(i)! + 1);
    }
  }
  // a band makes room for a label above its first level and below its last
  const room = { header: [0, 0], footer: [0, 0] };
  for (const [i, p] of place) {
    if ((p !== "header" && p !== "footer") || !geoms[i].text) continue;
    if (geoms[i].label === "above" && level.get(i) === 0) room[p][0] = Math.ceil(h / 2);
    if (geoms[i].label === "below" && level.get(i) === bands[p] - 1) room[p][1] = Math.ceil(h / 2);
  }
  const bandPx = (b: "header" | "footer") => (bands[b] ? bandHeight(bands[b], f.fs) + room[b][0] + room[b][1] : 0);
  const laid: Laid<G>[] = geoms.map((g, i) => {
    const k = level.get(i)!;
    const p = place.get(i)!;
    const at = p.split(" ")[0];
    const top = g.row === null ? 0 : f.laneTop + g.row * f.laneH;
    let y: number;
    if (at === "header") y = f.headTop + room.header[0] + 3 + h / 2 + k * step;
    else if (at === "footer") y = f.footTop + room.footer[0] + 3 + h / 2 + k * step;
    else if (at === "bottom") y = top + f.laneH - 3 - h / 2 - k * step;
    else if (at === "middle") y = top + f.laneH / 2 + k * step;
    else if (at === "between") y = top + f.laneH - k * step;
    else if (at === "value") y = (g.valueY ?? top) + k * step;
    else y = top + 3 + h / 2 + k * step;
    y += g.nudge;
    return { ...g, place: p, k, y, lx: null, ly: y - h / 2 };
  });
  // labels, level by level: the lines first, then each label where it has room
  const spans = new Map<string, [number, number][]>();
  laid.forEach((d) => {
    const s = `${d.place} ${d.k}`;
    if (!spans.has(s)) spans.set(s, []);
    spans.get(s)!.push([Math.min(d.xa, d.xb), Math.max(d.xa, d.xb)]);
  });
  const levels = new Map([...spans].map(([k, lines]) => [k, new LevelSpans(lines)]));
  const right = f.plot.x + f.plot.w;
  const areaTop = f.headTop;
  const areaBottom = f.footTop + bandPx("footer");
  const centred = (l: number, r: number, tw: number) => Math.max(f.plot.x + 1, Math.min((l + r) / 2 - tw / 2, right - tw - 1));
  const byLeft = laid.map((_, i) => i).sort((p, q) => Math.min(laid[p].xa, laid[p].xb) - Math.min(laid[q].xa, laid[q].xb) || p - q);
  // labels put somewhere first (they take their room), then the automatic ones
  for (const i of byLeft) {
    const d = laid[i];
    const mode = d.label ?? "auto";
    if (!d.text || mode === "auto" || mode === "hover") continue;
    const l = Math.min(d.xa, d.xb);
    const r = Math.max(d.xa, d.xb);
    if (mode === "on" || mode === "above" || mode === "below") {
      d.lx = centred(l, r, d.tw);
      // above or below its line; in a lane at the edge of the plot, where that would be
      // cut off, on the other side
      const up = d.y - h - 1;
      const down = d.y + 2;
      if (mode === "above") d.ly = up < areaTop && down + h <= areaBottom ? down : up;
      else if (mode === "below") d.ly = down + h > areaBottom && up >= areaTop ? up : down;
    } else d.lx = mode === "start" ? l - 6 - d.tw : r + 6;
    if (mode !== "above" && mode !== "below" && (mode !== "on" || d.tw > r - l)) levels.get(`${d.place} ${d.k}`)!.add(d.lx, d.lx + d.tw);
  }
  for (const i of byLeft) {
    const d = laid[i];
    if (!d.text || (d.label ?? "auto") !== "auto") continue;
    const l = Math.min(d.xa, d.xb);
    const r = Math.max(d.xa, d.xb);
    const s = levels.get(`${d.place} ${d.k}`)!;
    if (d.tw + 2 * ARROW_LEN <= r - l) d.lx = centred(l, r, d.tw);
    else if (r + 6 + d.tw <= right && s.free(r + 6, r + 6 + d.tw)) d.lx = r + 6;
    else if (l - 6 - d.tw >= f.plot.x && s.free(l - 6 - d.tw, l - 6)) d.lx = l - 6 - d.tw;
    if (d.lx !== null && d.tw + 2 * ARROW_LEN > r - l) s.add(d.lx, d.lx + d.tw);
  }
  return { laid, head: bandPx("header"), foot: bandPx("footer") };
}

/** Each measure's geometry, as the view shows it now. */
export function measureGeoms(view: TimelineView, ctx: CanvasRenderingContext2D, measures: NoteMeasure[], plot: Rect): (MeasureGeom & { m: NoteMeasure; color: string })[] {
  const c = view.camera;
  const px = (v: number) => plot.x + (v - c.left) * c.scale;
  const out: (MeasureGeom & { m: NoteMeasure; color: string })[] = [];
  for (const m of measures) {
    const a = endX(view, m.a);
    const b = endX(view, m.b);
    if (a === null || b === null) continue;
    const rows: [number | null, number | null] = [rowOf(view, m.a.lane), rowOf(view, m.b.lane)];
    let row = m.lane !== null ? rowOf(view, m.lane) : null;
    let lane = m.lane;
    if (row === null) {
      const shown = rows.filter((r): r is number => r !== null);
      row = shown.length ? Math.min(...shown) : null;
      lane = row === null ? null : row === rows[0] ? m.a.lane : m.b.lane;
    }
    const text = measureText(view, m);
    const ys: [number | null, number | null] = [sampleY(view, m.a), sampleY(view, m.b)];
    const at = m.at ?? "auto";
    let valueY: number | null = null;
    if (typeof at === "object" && lane !== null) {
      const v = view.values.find((l) => l.data.spec.name === at.layer);
      const y = v ? v.yAt(lane, at.value, view.valueView()) : null;
      valueY = y !== null && Number.isFinite(y) ? y : null;
    }
    out.push({
      m,
      xa: px(a),
      xb: px(b),
      ua: a,
      ub: b,
      rows,
      ys,
      row,
      at: typeof at === "object" ? "value" : at,
      valueY,
      level: m.level ?? null,
      nudge: m.nudge ?? 0,
      text,
      tw: ctx.measureText(text).width + 8,
      label: m.label ?? "auto",
      group: m.group !== undefined ? m.id : null,
      off: m.group ?? 0,
      color: m.over ? view.theme.over : m.color ?? view.theme.accent,
    });
  }
  return out;
}

/** Where measures' lines and labels go, with the levels the header and footer bands use. */
export function layoutMeasures(view: TimelineView, ctx: CanvasRenderingContext2D, measures: NoteMeasure[], plot: Rect, laneTop: number): { laid: MeasureLaid[]; head: number; foot: number } {
  const geoms = measureGeoms(view, ctx, measures, plot);
  const headTop = plot.y - view.measureBands.head;
  return placeMeasures(geoms, { fs: view.fs, plot, laneTop, laneH: view.laneH, headTop, footTop: plot.y + plot.h });
}

/** Where an end that is a sample is drawn (null: it is not a sample, or not shown). */
function sampleY(view: TimelineView, e: NoteEnd): number | null {
  if (e.value === undefined || e.value === null || e.lane === null) return null;
  const v = view.values.find((l) => l.data.spec.name === e.layer);
  return v ? v.yAt(e.lane, e.value, view.valueView()) : null;
}

/** Where an end's mark is drawn: its middle and half its height (px). A bar in a lane of
 * bars that overlap has a row of its own; an event that is moved aside, its own height. Null:
 * not known (a bin, merged bars), so the middle of its lane's row. */
export function markY(view: TimelineView, e: NoteEnd, laneTop: number, plot: Rect): [number, number] | null {
  if (e.layer === undefined || e.index === undefined || e.index < 0) return null;
  const b = view.bars.find((x) => x.data.spec.name === e.layer);
  if (b) {
    const i = b.localIndex(e.index);
    if (i < 0) return null;
    const { cy, h } = b.box(i, { ...barView(view, plot), laneTop });
    return [cy, h / 2];
  }
  const l = view.layers.find((x) => x.data.spec.name === e.layer);
  if (!l || (l.detail && !l.index)) return null; // the layer's bins are shown
  let i = e.index;
  if (l.index) {
    const j = lowerBound(l.index, e.index);
    if (j >= l.index.length || l.index[j] !== e.index) return null;
    i = j;
  }
  if (i >= l.data.count) return null;
  const row = view.slot[l.data.lane[i]];
  if (row === undefined || row < 0) return null;
  return [laneTop + (row + 0.5) * view.laneH + (l.draw.dy.data[i] ?? 0), Math.min(6, view.laneH / 4)];
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

/** A measure: an extension line from each end's mark to the line's height (from a sample: a
 * dot on it; a short tick through the line at a time), or through every lane, or none; the
 * line with an arrowhead at each end (outside, pointing in, when the line is short), an
 * oblique tick, a dot, or nothing; the label on the background where it was put. Selected:
 * thicker, with handles. */
function drawMeasure(view: TimelineView, ctx: CanvasRenderingContext2D, d: MeasureLaid, plot: Rect, area: Rect, laneTop: number, selected: boolean): void {
  const y = d.y;
  const lo = Math.min(d.xa, d.xb);
  const hi = Math.max(d.xa, d.xb);
  if (hi < plot.x - 1 || lo > plot.x + plot.w + 1 || y < area.y || y > area.y + area.h) return;
  ctx.strokeStyle = d.color;
  ctx.fillStyle = d.color;
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 2]);
  const ends: [number, number | null, number | null, NoteEnd][] = [[d.xa, d.rows[0], d.ys[0], d.m.a], [d.xb, d.rows[1], d.ys[1], d.m.b]];
  const extend = d.m.extend ?? "mark";
  for (const [x, row, ys, e] of extend === "mark" ? ends : []) {
    let y0 = y - 5;
    let y1 = y + 5;
    if (ys !== null) {
      const away = y > ys ? 1 : -1;
      y0 = ys;
      y1 = y + away * 4;
    } else if (row !== null) {
      // from the mark's edge (its own row in a lane of bars that overlap), else the row's middle
      const [yc, half] = markY(view, e, laneTop, plot) ?? [laneTop + (row + 0.5) * view.laneH, Math.min(6, view.laneH / 4)];
      if (Math.abs(y - yc) < half + 2) continue; // through the mark: no extension line
      const away = y > yc ? 1 : -1;
      y0 = yc + away * half;
      y1 = y + away * 4;
    }
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + 0.5, y0);
    ctx.lineTo(Math.round(x) + 0.5, y1);
    ctx.stroke();
  }
  if (extend === "lanes") {
    // through every lane and band, as cursors
    for (const x of [d.xa, d.xb]) {
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, area.y);
      ctx.lineTo(Math.round(x) + 0.5, area.y + area.h);
      ctx.stroke();
    }
  }
  ctx.setLineDash([]);
  const style = d.m.ends ?? "arrows";
  const inside = hi - lo >= 2 * ARROW_LEN + 2;
  // a band of the background under the line and its heads: it shows over marks
  const reach = style === "arrows" ? (inside ? 0 : 2 * ARROW_LEN) : style === "none" ? 0 : 4;
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
    if (style === "ticks") {
      ctx.beginPath();
      ctx.moveTo(x - TICK, y + TICK);
      ctx.lineTo(x + TICK, y - TICK);
      ctx.stroke();
    } else if (style === "dots") {
      ctx.beginPath();
      ctx.arc(x, y, END_DOT, 0, Math.PI * 2);
      ctx.fill();
    } else if (style === "arrows") {
      if (inside) head(ctx, x, y, way);
      else {
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + way * 2 * ARROW_LEN, y);
        ctx.stroke();
        head(ctx, x, y, -way);
      }
    }
  }
  for (const [x, , ys] of ends) {
    if (ys === null || ys < plot.y || ys > plot.y + plot.h) continue;
    ctx.beginPath();
    ctx.arc(x, ys, SAMPLE_DOT, 0, Math.PI * 2);
    ctx.fill();
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
  // a label without room shows while its measure is hovered or selected
  const shown = d.lx ?? (selected || view.tooltipKey === `m${d.m.id}` ? (hi + 6 + d.tw <= plot.x + plot.w ? hi + 6 : lo - 6 - d.tw) : null);
  const top = d.lx === null ? y - (view.fs + 4) / 2 : d.ly;
  if (d.text && shown !== null) label(view, ctx, d.text, shown, top, d.color, plot);
}

/** The step to the right of each level of a measure of a change (kind "value"), px. */
const VALUE_STEP = 12;

/** A measure of the change between two samples (kind "value" or "both"), as drawn (Python's
 * `_value_shape`): its ends' points on the later sample's lane's scale (`xa`, `ya`, `xb`,
 * `yb`), its vertical line's x (`xv`), its horizontal line's height (`yh`, "both"), and its
 * labels: the text (`lx`, `ly`) and, for "both", the change beside the vertical (`cx`,
 * `cy`). Null: not drawn here (an end or its value not shown). */
export interface ValueShape {
  kind: "value" | "both";
  xa: number;
  ya: number;
  xb: number;
  yb: number;
  xv: number;
  yh: number;
  change: string;
  cw: number;
  cx: number;
  cy: number;
}

export function valueShape(view: TimelineView, ctx: CanvasRenderingContext2D, m: NoteMeasure, plot: Rect): (MeasureLaid & { shape: ValueShape }) | null {
  const kind = m.kind;
  if (kind !== "value" && kind !== "both") return null;
  const ua = endX(view, m.a);
  const ub = endX(view, m.b);
  const v = view.values.find((l) => l.data.spec.name === m.a.layer);
  if (ua === null || ub === null || !v || m.a.value == null || m.b.value == null) return null;
  const c = view.camera;
  const px = (u: number) => plot.x + (u - c.left) * c.scale;
  const late = ub >= ua ? m.b : m.a;
  if (late.lane === null) return null;
  const vv = view.valueView();
  const ya = v.yAt(late.lane, m.a.value, vv);
  const yb = v.yAt(late.lane, m.b.value, vv);
  if (ya === null || yb === null || !Number.isFinite(ya) || !Number.isFinite(yb)) return null;
  const xa = px(ua);
  const xb = px(ub);
  const xl = Math.max(xa, xb);
  const xe = Math.min(xa, xb);
  const h = view.fs + 4;
  const right = plot.x + plot.w;
  const change = `Δ ${changeText(m.change ?? 0)}`;
  const cw = ctx.measureText(change).width + 8;
  const text = m.text === null ? (kind === "value" ? change : measureText(view, { ...m, text: "{time}" })) : measureText(view, m);
  const tw = ctx.measureText(text).width + 8;
  const yh = ub >= ua ? ya : yb; // "both": the time along at the earlier sample's value
  const mode = m.label ?? "auto";
  const beside = (x: number, w: number) => (x + 6 + w <= right ? x + 6 : x - 6 - w);
  let lx: number | null;
  let ly: number;
  let xv = xl;
  let cx = 0;
  let cy = 0;
  if (kind === "value") {
    xv = xl + 10 + (m.level ?? 0) * VALUE_STEP;
    lx = beside(xv, tw);
    ly = (ya + yb) / 2 - h / 2;
  } else {
    lx = Math.max(plot.x + 1, Math.min((xe + xl) / 2 - tw / 2, right - tw - 1));
    ly = mode === "below" ? yh + 2 : yh - h - 1;
    cx = beside(xl, cw);
    cy = (ya + yb) / 2 - h / 2;
  }
  if (mode === "hover") lx = null;
  const y = kind === "value" ? (ya + yb) / 2 : yh;
  return {
    m,
    color: m.over ? view.theme.over : m.color ?? view.theme.accent,
    xa: kind === "value" ? xv - 3 : xe,
    xb: kind === "value" ? xv + 3 : xl,
    ua,
    ub,
    rows: [null, null],
    ys: [ya, yb],
    row: null,
    at: "value",
    valueY: y,
    level: m.level ?? null,
    nudge: 0,
    text,
    tw,
    label: mode,
    place: "value",
    k: 0,
    y,
    lx,
    ly,
    shape: { kind, xa, ya, xb, yb, xv, yh, change, cw, cx, cy },
  };
}

/** An arrowhead with its tip at (x, y), pointing along (dx, dy) (a unit vector). */
function headAlong(ctx: CanvasRenderingContext2D, x: number, y: number, dx: number, dy: number): void {
  const bx = x - dx * ARROW_LEN;
  const by = y - dy * ARROW_LEN;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(bx - dy * 3.5, by + dx * 3.5);
  ctx.lineTo(bx + dy * 3.5, by - dx * 3.5);
  ctx.closePath();
  ctx.fill();
}

/** A dimension line from (x0, y0) to (x1, y1), across or up: on the background, with its
 * ends (arrows inside, or outside pointing in when it is short; ticks; dots; none). */
function dimension(view: TimelineView, ctx: CanvasRenderingContext2D, x0: number, y0: number, x1: number, y1: number, style: MeasureEnds, color: string, selected: boolean): void {
  const len = Math.hypot(x1 - x0, y1 - y0);
  const ux = len ? (x1 - x0) / len : 1;
  const uy = len ? (y1 - y0) / len : 0;
  const inside = len >= 2 * ARROW_LEN + 2;
  ctx.globalAlpha = 0.85;
  ctx.strokeStyle = view.theme.bg;
  ctx.lineWidth = 7;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.stroke();
  ctx.globalAlpha = 1;
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = selected ? 2.5 : 1.5;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.stroke();
  for (const [x, y, way] of [[x0, y0, -1], [x1, y1, 1]] as const) {
    if (style === "ticks") {
      ctx.beginPath();
      ctx.moveTo(x - TICK, y + TICK);
      ctx.lineTo(x + TICK, y - TICK);
      ctx.stroke();
    } else if (style === "dots") {
      ctx.beginPath();
      ctx.arc(x, y, END_DOT, 0, Math.PI * 2);
      ctx.fill();
    } else if (style === "arrows") {
      if (inside) headAlong(ctx, x, y, way * ux, way * uy);
      else {
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + way * ux * 2 * ARROW_LEN, y + way * uy * 2 * ARROW_LEN);
        ctx.stroke();
        headAlong(ctx, x, y, -way * ux, -way * uy);
      }
    }
  }
}

/** A measure of a change: "value", a vertical dimension line beside the later sample, with
 * an extension line from each sample (or across the plot, as cursors, for "lanes"); "both",
 * an L from the earlier sample: the time along, the change up. A dot on each sample; the
 * labels on the background. */
function drawValueMeasure(view: TimelineView, ctx: CanvasRenderingContext2D, d: MeasureLaid & { shape: ValueShape }, plot: Rect, selected: boolean): void {
  const s = d.shape;
  const style = d.m.ends ?? "arrows";
  const extend = d.m.extend ?? "mark";
  ctx.strokeStyle = d.color;
  ctx.fillStyle = d.color;
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 2]);
  if (s.kind === "value" && extend !== "none") {
    for (const [x, y] of [[s.xa, s.ya], [s.xb, s.yb]]) {
      ctx.beginPath();
      ctx.moveTo(extend === "lanes" ? plot.x : x, Math.round(y) + 0.5);
      ctx.lineTo(extend === "lanes" ? plot.x + plot.w : s.xv + 4, Math.round(y) + 0.5);
      ctx.stroke();
    }
  }
  if (s.kind === "both" && extend === "lanes") {
    for (const y of [s.ya, s.yb]) {
      ctx.beginPath();
      ctx.moveTo(plot.x, Math.round(y) + 0.5);
      ctx.lineTo(plot.x + plot.w, Math.round(y) + 0.5);
      ctx.stroke();
    }
  }
  ctx.setLineDash([]);
  const late = Math.max(s.xa, s.xb);
  const early = Math.min(s.xa, s.xb);
  const yLate = s.xb >= s.xa ? s.yb : s.ya;
  if (s.kind === "value") dimension(view, ctx, s.xv, s.ya, s.xv, s.yb, style, d.color, selected);
  else {
    dimension(view, ctx, early, s.yh, late, s.yh, style, d.color, selected);
    dimension(view, ctx, late, s.yh, late, yLate, style, d.color, selected);
  }
  ctx.fillStyle = d.color;
  for (const [x, y] of [[s.xa, s.ya], [s.xb, s.yb]]) {
    ctx.beginPath();
    ctx.arc(x, y, SAMPLE_DOT, 0, Math.PI * 2);
    ctx.fill();
  }
  const shown = selected || view.tooltipKey === `m${d.m.id}`;
  const h = view.fs + 4;
  if (d.lx !== null || shown) {
    const lx = d.lx ?? (s.kind === "value" ? s.xv + 6 : Math.min(s.xa, s.xb));
    label(view, ctx, d.text, lx, d.lx === null && s.kind === "value" ? (s.ya + s.yb) / 2 - h / 2 : d.ly, d.color, plot);
    if (s.kind === "both") label(view, ctx, s.change, s.cx, s.cy, d.color, plot);
  }
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

/** The measures to draw: Python's and the page's own (none when hidden), one end or its
 * line moved while it is dragged, and the one being made (its second end at the pointer). */
/** Whether a measure is the one selected: its note, and of a rule, its part. */
export function isSelected(view: TimelineView, m: NoteMeasure): boolean {
  return m.id === view.selectedMeasure && (m.part ?? null) === view.selectedPart;
}

/** A measure as a change would make it: a rule's measures all change (a chain's and a
 * baseline's level is the group's, each a level above by its offset; those of marks keep
 * their lanes). */
function previewed(m: NoteMeasure, change: MeasureChange): NoteMeasure {
  if (!m.rule) return { ...m, ...change };
  const c = { ...change };
  if ((m.rule === "each" || m.rule === "gaps") && "lane" in c) delete c.lane;
  if (m.group !== undefined && c.level !== undefined && c.level !== null) c.level += m.group;
  return { ...m, ...c };
}

export function measuresShown(view: TimelineView): NoteMeasure[] {
  const draft = view.measureDraft;
  if (view.measuresHidden && !draft) return [];
  const all = view.measuresHidden ? [] : [...(view.notes.measures ?? []), ...view.localMeasures];
  const out = all.map((m) => {
    const line = view.lineDrag;
    if (line?.from.m.id === m.id && line.change) return previewed(m, line.change);
    const h = view.handleDrag;
    if (!h || h.id !== m.id) return m;
    const moved = { ...m, [h.end]: h.to };
    return { ...moved, span: moved.b.x - moved.a.x, events: between(moved.a.r, moved.b.r) };
  });
  if (draft?.b) out.push({ a: draft.a, b: draft.b, span: draft.b.x - draft.a.x, events: between(draft.a.r, draft.b.r), lane: draft.lane, text: null, color: null, id: Number.NaN });
  return out;
}

/** The notes: translucent bands with their text at the top (a line for a note at one time),
 * arrows with their text at the middle, measures, and lines across all lanes over them. */
export function drawNotes(view: TimelineView, ctx: CanvasRenderingContext2D, plot: Rect, laneTop: number): void {
  const notes = view.notes;
  const measures = measuresShown(view);
  view.measureHits = [];
  if (!measures.length) view.setMeasureBands(0, 0);
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
  ctx.restore();
  // measures: in the lanes, and in the header and footer bands around them; those of a
  // change between samples at their values
  const timed = measures.filter((m) => (m.kind ?? "time") === "time");
  const { laid, head, foot } = layoutMeasures(view, ctx, timed, plot, laneTop);
  const headH = view.measureBands.head;
  const footH = view.measureBands.foot;
  const area = { x: plot.x, y: plot.y - headH, w: plot.w, h: plot.h + headH + footH };
  ctx.save();
  ctx.fillStyle = view.theme.band;
  if (headH) ctx.fillRect(plot.x, plot.y - headH, plot.w, headH);
  if (footH) ctx.fillRect(plot.x, plot.y + plot.h, plot.w, footH);
  ctx.beginPath();
  ctx.rect(area.x, area.y, area.w, area.h);
  ctx.clip();
  ctx.font = view.font(-1);
  ctx.textBaseline = "alphabetic";
  for (const d of laid) drawMeasure(view, ctx, d, plot, area, laneTop, isSelected(view, d.m));
  ctx.restore();
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  ctx.font = view.font(-1);
  ctx.textBaseline = "alphabetic";
  const values: MeasureLaid[] = [];
  for (const m of measures) {
    if ((m.kind ?? "time") === "time") continue;
    const d = valueShape(view, ctx, m, plot);
    if (!d) continue;
    drawValueMeasure(view, ctx, d, plot, isSelected(view, m));
    values.push(d);
  }
  ctx.restore();
  view.measureHits = [...laid, ...values].filter((d) => !Number.isNaN(d.m.id));
  view.setMeasureBands(head, foot);
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  // the edge a measure's end would take: a short tick on it
  const snap = view.snapEdge;
  if (snap) {
    const x = endX(view, snap);
    const row = rowOf(view, snap.lane);
    if (x !== null && row !== null) {
      const mark = markY(view, snap, laneTop, plot);
      const yc = mark ? mark[0] : laneTop + (row + 0.5) * view.laneH;
      const half = mark ? Math.max(6, mark[1] + 3) : Math.max(6, view.laneH * 0.35);
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
export function askText(view: TimelineView, x: number, y: number, done: (text: string | null) => void, opts: { value?: string; placeholder?: string; label?: string } = {}): void {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "atl-note-input";
  input.value = opts.value ?? "";
  input.placeholder = opts.placeholder ?? "Note (Enter keeps it, Esc drops it)";
  input.setAttribute("aria-label", opts.label ?? "The annotation's text");

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
  view.placeInStage(input, x, y, y - 4);
  input.focus();
  input.select();
}
