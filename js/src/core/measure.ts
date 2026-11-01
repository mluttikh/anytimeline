// Measuring: the time between two ends, each a mark's start or end (snapped to within
// SNAP_PX of the pointer, in the lane under it; a sample of a values layer is a mark whose
// start and end are its time) or, with Shift, a free time. Between two samples of one layer
// a measure shows the change in value too. The Measure
// tool measures what a drag spans; the key `m` fixes one end and then the other, with the
// line following the pointer in between; `M` measures the mark pointed at; `>` and `<` move
// the selected (or newest) measure's second end to the next or previous edge in its lane.
// A measure goes to Python (onMeasure), which keeps it; a page keeps its own until closed.
// A measure's label, clicked, selects it: its ends can be dragged, its line too (to another
// level, place, lane or band), Up and Down move it a level, Enter edits its text, 0 puts it
// back where the layout would, Delete removes it, and a small menu offers the same and, in a
// page, copying it as Python. Each change goes to Python (onNoteChange), which replaces the
// note; a page changes its own.

import { globalIndex, type Hit } from "./common";
import { askText, bandHeight, between, changeOf, changeText, laneLevels, type MeasureChange, type MeasureLaid, type MeasurePlace, type NoteEnd, type NoteMeasure, type Side } from "./notes";
import { lowerBound, upperBound } from "./scene";
import { fmtNumber } from "./time";
import type { TimelineView } from "./view";

/** How near the pointer (CSS px) an edge must be to be taken. */
export const SNAP_PX = 8;
/** How near an end of the selected measure (px) a press must be to drag it. */
const HANDLE_PX = 7;

/** An end as Python takes it: a mark's edge (its layer, index and side) or a time (ticks). */
export type EndRef = { layer: string; index: number; side: Side } | { x: number };

/** A measure being made: its first end, the lane its line goes in when neither end is a
 * mark's, and its second end while it follows the pointer. */
export interface MeasureDraft {
  a: NoteEnd;
  lane: number | null;
  b: NoteEnd | null;
}

/** Ask Python for the edge nearest to a place in a lane (`within` it), or the next or
 * previous one (`forward`), on the scale shown. */
export type SnapAsk = (ask: { lane: number; at: number; within?: number; forward?: boolean; scale: string }) => Promise<NoteEnd | null>;

export function refOf(e: NoteEnd): EndRef {
  return e.layer !== undefined && e.index !== undefined && e.side ? { layer: e.layer, index: e.index, side: e.side } : { x: e.x };
}

/** The lane of the row at a height (null: none there). */
export function laneAtY(view: TimelineView, y: number): number | null {
  const plot = view.plot();
  if (y < plot.y || y > plot.y + plot.h) return null;
  const row = Math.floor((y - (plot.y - view.scrollY)) / view.laneH);
  return row >= 0 && row < view.laneAt.length ? view.laneAt[row] : null;
}

/** A place on the scale shown as a time (ticks): on the Order scale, the instant's at it. */
function timeOf(view: TimelineView, v: number): number {
  if (view.xscale !== "order") return v;
  const seq = view.seq;
  return seq?.count ? seq.time(Math.max(0, Math.min(seq.count - 1, Math.round(v)))) : v;
}

/** A free end at a place on the scale shown. */
export function freeEnd(view: TimelineView, v: number): NoteEnd {
  if (view.xscale === "order") return { x: timeOf(view, v), r: v, lane: null, side: null };
  const seq = view.seq;
  return { x: v, r: seq?.count ? seq.lower(v) - 0.5 : null, lane: null, side: null };
}

function eventEdge(view: TimelineView, li: number, i: number, side: Side): NoteEnd {
  const l = view.layers[li];
  return { x: l.data.time[i], r: l.data.rank[i], lane: l.data.lane[i], side, layer: l.data.spec.name, index: globalIndex(l, i) };
}

function barEdge(view: TimelineView, k: number, i: number, side: Side): NoteEnd | null {
  const b = view.bars[k];
  const index = b.globalIndex(i);
  if (index < 0) return null; // short bars merged
  const d = b.data;
  const first = side === "start";
  return { x: first ? d.start[i] : d.end[i], r: first ? d.rankStart[i] : d.rankEnd[i], lane: d.lane[i], side, layer: d.spec.name, index };
}

/** Sample i of values layer k as an end: its time is its start (and its end). */
function sampleEdge(view: TimelineView, k: number, i: number, lane: number): NoteEnd {
  const v = view.values[k];
  const d = v.data;
  const t = d.time[i];
  const value = d.value[i];
  const r = view.seq?.count ? view.seq.position(t) : null;
  return { x: t, r, lane, side: "start", layer: d.spec.name, index: v.globalIndex(i), value: Number.isNaN(value) ? null : value };
}

/** Every edge of the marks held in a lane from `lo` to `hi` on the scale shown, with its
 * place there (a sample's: its time, its place between the events). */
function edgesIn(view: TimelineView, lane: number, lo: number, hi: number): { at: number; edge: NoteEnd }[] {
  const out: { at: number; edge: NoteEnd }[] = [];
  const order = view.xscale === "order";
  view.layers.forEach((l, li) => {
    const starts = l.data.laneStarts;
    if (lane + 1 >= starts.length) return;
    const src = view.xsrc(l);
    const i0 = lowerBound(src, lo, starts[lane], starts[lane + 1]);
    const i1 = upperBound(src, hi, i0, starts[lane + 1]);
    for (let i = i0; i < i1; i++) out.push({ at: src[i], edge: eventEdge(view, li, i, "start") });
  });
  view.bars.forEach((b, k) => {
    const d = b.data;
    const starts = d.laneStarts;
    if (lane + 1 >= starts.length) return;
    const [s, e] = b.ends(order);
    const reach = (order ? d.maxDurRank : d.maxDur)[lane] ?? 0;
    const i0 = lowerBound(s, lo - reach, starts[lane], starts[lane + 1]);
    const i1 = upperBound(s, hi, i0, starts[lane + 1]);
    for (let i = i0; i < i1; i++) {
      for (const side of ["start", "end"] as const) {
        const at = side === "start" ? s[i] : e[i];
        if (at < lo || at > hi) continue;
        const edge = barEdge(view, k, i, side);
        if (edge) out.push({ at, edge });
      }
    }
  });
  if (view.values.length) {
    const vv = view.valueView();
    view.values.forEach((v, k) => {
      const d = v.data;
      const xs = order ? v.xs(vv) : d.time;
      for (let run = 0; run < d.runLane.length; run++) {
        if (d.runLane[run] !== lane) continue;
        const i0 = lowerBound(xs, lo, d.runStarts[run], d.runStarts[run + 1]);
        const i1 = upperBound(xs, hi, i0, d.runStarts[run + 1]);
        for (let i = i0; i < i1; i++) if (!Number.isNaN(d.value[i])) out.push({ at: xs[i], edge: sampleEdge(view, k, i, lane) });
      }
    });
  }
  return out;
}

/** The edge of a held mark nearest to place `v` in a lane, within `within` (null: none). */
export function nearestHeld(view: TimelineView, lane: number, v: number, within: number): NoteEnd | null {
  let best: NoteEnd | null = null;
  let bestD = within;
  for (const { at, edge } of edgesIn(view, lane, v - within, v + within)) {
    const d = Math.abs(at - v);
    if (d < bestD || (d === bestD && !best)) {
      bestD = d;
      best = edge;
    }
  }
  return best;
}

/** The edge of a held mark in a lane next after (or before) place `v`. */
export function stepHeld(view: TimelineView, lane: number, v: number, forward: boolean): NoteEnd | null {
  const lo = forward ? v : -Infinity;
  const hi = forward ? Infinity : v;
  let best: { at: number; edge: NoteEnd } | null = null;
  for (const c of edgesIn(view, lane, lo, hi)) {
    if (forward ? c.at <= v : c.at >= v) continue;
    if (!best || (forward ? c.at < best.at : c.at > best.at)) best = c;
  }
  return best?.edge ?? null;
}

/** The end at a point (CSS px): the nearest edge in the lane there, else (or with `free`)
 * the time there. */
export function endAt(view: TimelineView, p: { x: number; y: number }, free: boolean): NoteEnd {
  const plot = view.plot();
  const v = view.camera.fromPx(Math.max(0, Math.min(plot.w, p.x - plot.x)));
  if (!free) {
    const lane = laneAtY(view, p.y);
    if (lane !== null) {
      const edge = nearestHeld(view, lane, v, SNAP_PX / view.camera.scale);
      if (edge) return edge;
    }
  }
  return freeEnd(view, v);
}

/** Whether a layer in sight holds bins, not marks, there, or some of its samples (Python
 * then finds the edge). */
function binned(view: TimelineView): boolean {
  return view.layers.some((l) => !!l.detail?.shown) || view.bars.some((b) => !!b.detail) || view.values.some((v) => !!v.detail);
}

/** The end at a point, asking Python when what is held there are bins. */
export async function endAtExact(view: TimelineView, p: { x: number; y: number }, free: boolean): Promise<NoteEnd> {
  const held = endAt(view, p, free);
  const ask = view.callbacks.onSnap;
  if (free || held.side || !ask || !binned(view)) return held;
  const lane = laneAtY(view, p.y);
  if (lane === null) return held;
  const plot = view.plot();
  const at = view.camera.fromPx(Math.max(0, Math.min(plot.w, p.x - plot.x)));
  try {
    return (await ask({ lane, at, within: SNAP_PX / view.camera.scale, scale: view.xscale })) ?? held;
  } catch {
    return held;
  }
}

/** Keep a measure: in Python, or (a page) in the page until it is closed. */
export function commit(view: TimelineView, a: NoteEnd, b: NoteEnd, lane: number | null): void {
  if (a.x === b.x && a.r === b.r && a.layer === b.layer && a.index === b.index) return;
  if (view.measuresHidden) view.showMeasures(true); // a new measure shows them again
  if (view.callbacks.onMeasure) {
    view.callbacks.onMeasure(refOf(a), refOf(b), lane);
    return;
  }
  const id = -1 - view.localMeasures.length;
  view.localMeasures = [...view.localMeasures, { a, b, span: b.x - a.x, events: between(a.r, b.r), change: changeOf(a, b), lane, text: null, color: null, id }];
  view.showMeasures(true);
  view.selectMeasure(null);
}

/** The pointer, or the focused mark's middle, as a point to measure from (null: neither). */
function pointOf(view: TimelineView): { x: number; y: number } | null {
  if (view.pointer) return view.pointer;
  const f = view.focus;
  if (!f) return null;
  const plot = view.plot();
  const row = view.slot[f.lane];
  if (row === undefined || row < 0) return null;
  const at = view.xscale === "order" ? f.r : f.x;
  return { x: plot.x + view.camera.toPx(at), y: plot.y - view.scrollY + (row + 0.5) * view.laneH };
}

/** The key `m`: the first end, or the second (the measure is kept). An end is the edge
 * within SNAP_PX of the pointer, else the time there. */
export async function keyM(view: TimelineView): Promise<void> {
  const p = pointOf(view);
  if (!p) {
    view.flashNotice("Point at a mark, then press m");
    return;
  }
  const draft = view.measureDraft;
  if (!draft) {
    const a = await endAtExact(view, p, false);
    view.measureDraft = { a, lane: a.lane ?? laneAtY(view, p.y), b: null };
    view.annotating = false;
    view.connectFrom = null;
    view.setMode("Measure: point at the other end and press m · Esc cancels");
    view.requestRender();
    return;
  }
  const b = await endAtExact(view, p, false);
  view.measureDraft = null;
  view.setMode(null);
  commit(view, draft.a, b, draft.a.side || b.side ? null : draft.lane);
  view.requestRender();
}

/** The key `M` (or a double-click with the Measure tool): the pointed mark's own length. */
export function measureMark(view: TimelineView, h: Hit | null): boolean {
  if (!h || h.val || h.bin) return false;
  let a: NoteEnd | null;
  let b: NoteEnd | null;
  if (h.bar) {
    a = barEdge(view, h.layer, h.index, "start");
    b = barEdge(view, h.layer, h.index, "end");
  } else {
    a = eventEdge(view, h.layer, h.index, "start");
    b = eventEdge(view, h.layer, h.index, "end");
  }
  if (!a || !b || (a.x === b.x && a.r === b.r)) {
    view.flashNotice("An event has no length: measure from it to another mark (m, then m)");
    return true;
  }
  commit(view, a, b, null);
  return true;
}

/** The measure keys `>` and `<` act on: the selected one, else the newest. */
function target(view: TimelineView): NoteMeasure | null {
  const all = [...(view.notes.measures ?? []), ...view.localMeasures];
  const sel = all.find((m) => m.id === view.selectedMeasure);
  if (sel) return sel;
  const py = (view.notes.measures ?? []).reduce<NoteMeasure | null>((best, m) => (!best || m.id > best.id ? m : best), null);
  return view.localMeasures[view.localMeasures.length - 1] ?? py;
}

/** Move a measure's end: in Python, or in the page. */
export function moveEnd(view: TimelineView, m: NoteMeasure, end: "a" | "b", to: NoteEnd): void {
  if (m.id >= 0) {
    view.callbacks.onNoteEnd?.(m.id, end, refOf(to));
    return;
  }
  view.localMeasures = view.localMeasures.map((n) => {
    if (n.id !== m.id) return n;
    const moved = { ...n, [end]: to };
    return { ...moved, span: moved.b.x - moved.a.x, events: between(moved.a.r, moved.b.r), change: changeOf(moved.a, moved.b) };
  });
  view.requestRender();
}

/** The keys `>` and `<`: the second end to the next or previous edge in its lane. */
export async function stepEnd(view: TimelineView, forward: boolean): Promise<void> {
  const m = target(view);
  if (!m) {
    view.flashNotice("Make a measure first (m on one end, m on the other)");
    return;
  }
  const lane = m.b.lane ?? m.a.lane;
  const at = view.xscale === "order" ? m.b.r : m.b.x;
  if (lane === null || at === null) {
    view.flashNotice("This measure's end is not in a lane");
    return;
  }
  let next = stepHeld(view, lane, at, forward);
  const ask = view.callbacks.onSnap;
  if (ask && binned(view)) {
    try {
      next = (await ask({ lane, at, forward, scale: view.xscale })) ?? next;
    } catch {
      // the edges held stand
    }
  }
  if (!next) {
    view.flashNotice(forward ? "No later edge in this lane" : "No earlier edge in this lane");
    return;
  }
  moveEnd(view, m, "b", next);
}

/** Whether a measure can be changed here: the page's own, or Python's in a notebook. */
export function editable(view: TimelineView, m: NoteMeasure): boolean {
  return m.id < 0 || !!view.callbacks.onNoteEnd;
}

/** Whether a measure's place, level and text can be changed here. */
export function changeable(view: TimelineView, m: NoteMeasure): boolean {
  return m.id < 0 || !!view.callbacks.onNoteChange;
}

/** Remove a measure: in Python, or from the page. */
export function remove(view: TimelineView, id: number): void {
  if (id >= 0) view.callbacks.onNoteRemove?.(id);
  else {
    view.localMeasures = view.localMeasures.filter((m) => m.id !== id);
    view.showMeasures(true);
  }
  view.selectMeasure(null);
  view.requestRender();
}

/** The selected measure as drawn (null: none selected, or not drawn). */
export function selectedLaid(view: TimelineView): MeasureLaid | null {
  return view.measureHits.find((h) => h.m.id === view.selectedMeasure) ?? null;
}

/** The selected measure, when its line or label is at a point and it can be changed: to drag
 * its line (null: not there). */
export function lineAt(view: TimelineView, p: { x: number; y: number }): MeasureLaid | null {
  const d = selectedLaid(view);
  if (!d || !changeable(view, d.m)) return null;
  const lo = Math.min(d.xa, d.xb);
  const hi = Math.max(d.xa, d.xb);
  if (p.x >= lo - 2 && p.x <= hi + 2 && Math.abs(p.y - d.y) <= 5) return d;
  return labelAt(view, p)?.id === d.m.id ? d : null;
}

/** Where a measure's line goes, as the layout says: its place, without the row or value. */
function placeOf(d: MeasureLaid): MeasurePlace | "value" {
  return d.place.split(" ")[0] as MeasurePlace | "value";
}

/** Where the line of measure `d`, dragged to height `y`, goes: a level of the header (above
 * the lanes) or footer (below them); in a row, the nearest of its top levels, middle,
 * bottom levels and the borders under it (a measure at a value: the value there, rounded to
 * about a pixel). The level is kept (pinned); the lane is the row's when that is another.
 * Null: where it is already. */
export function placeAt(view: TimelineView, d: MeasureLaid, y: number): MeasureChange | null {
  const plot = view.plot();
  const fs = view.fs;
  const h = fs + 4;
  const step = fs + 8;
  const level = (from: number) => Math.max(0, Math.round((y - from) / step));
  let change: MeasureChange;
  if (y < plot.y) change = { at: "header", level: level(plot.y - bandHeight(view.measureBands.head, fs) + 3 + h / 2) };
  else if (y > plot.y + plot.h) change = { at: "footer", level: level(plot.y + plot.h + 3 + h / 2) };
  else {
    const laneTop = plot.y - view.scrollY;
    const rows = view.laneAt.length;
    const row = Math.max(0, Math.min(rows - 1, Math.floor((y - laneTop) / view.laneH)));
    const lane = view.laneAt[row];
    if (lane === undefined || lane < 0) return null;
    const top = laneTop + row * view.laneH;
    const at = d.m.at;
    const v = typeof at === "object" ? view.values.find((l) => l.data.spec.name === at.layer) : undefined;
    const vv = v ? view.valueView() : null;
    const value = v && vv ? v.valueAtY(lane, y, vv) : null;
    let best: { row: number; at: MeasurePlace | "value"; level: number; y: number } | null = null;
    const take = (r: number, place: MeasurePlace | "value", k: number, cy: number) => {
      if (!best || Math.abs(cy - y) < Math.abs(best.y - y)) best = { row: r, at: place, level: k, y: cy };
    };
    if (value !== null && typeof at === "object") {
      const per = Math.abs((v && vv ? v.valueAtY(lane, y + 1, vv) ?? value : value) - value) || 1;
      const unit = 10 ** Math.floor(Math.log10(per));
      const rounded = Number((Math.round(value / unit) * unit).toPrecision(12));
      const out: MeasureChange = { at: { value: rounded, layer: at.layer }, level: null };
      if (row !== d.row) out.lane = lane;
      return out;
    }
    const cap = laneLevels(view.laneH, fs);
    for (let k = 0; k < cap; k++) take(row, "top", k, top + 3 + h / 2 + k * step);
    take(row, "middle", 0, top + view.laneH / 2);
    for (let k = 0; k < cap; k++) take(row, "bottom", k, top + view.laneH - 3 - h / 2 - k * step);
    take(row, "between", 0, top + view.laneH);
    if (row > 0) take(row - 1, "between", 0, top);
    const b = best as { row: number; at: MeasurePlace | "value"; level: number; y: number } | null;
    if (!b) return null;
    change = { at: b.at as MeasurePlace, level: b.level };
    if (b.row !== d.row) change.lane = view.laneAt[b.row];
  }
  if (change.lane === undefined && change.at === placeOf(d) && change.level === d.k) return null;
  return change;
}

/** Change a measure: in Python (which replaces the note), or in the page. */
export function changeMeasure(view: TimelineView, m: NoteMeasure, change: MeasureChange): void {
  if (m.id >= 0) {
    view.callbacks.onNoteChange?.(m.id, change);
    return;
  }
  view.localMeasures = view.localMeasures.map((n) => (n.id === m.id ? { ...n, ...change } : n));
  view.requestRender();
}

/** The keys Up and Down: the selected measure a level up or down the plot (its place's
 * levels go down from the top of a lane, a band and a value, and up from its bottom). */
export function stepLevel(view: TimelineView, up: boolean): boolean {
  const d = selectedLaid(view);
  if (!d || !changeable(view, d.m)) return false;
  const at = placeOf(d);
  const downward = at !== "bottom" && at !== "between";
  const k = d.k + (up === downward ? -1 : 1);
  if (k < 0) {
    view.flashNotice(up ? "This measure is as high as its place goes" : "This measure is as low as its place goes");
    return true;
  }
  changeMeasure(view, d.m, { at: at === "value" ? d.m.at : at, level: k });
  return true;
}

/** A measure back where the layout puts it: "auto", no level, and the lane of its ends when
 * one is a mark's. */
export function toAuto(view: TimelineView, m: NoteMeasure): void {
  const change: MeasureChange = { at: "auto", level: null };
  if (m.lane !== null && (m.a.lane !== null || m.b.lane !== null)) change.lane = null;
  changeMeasure(view, m, change);
}

/** Type a measure's text over its line (empty: the time between). */
export function editText(view: TimelineView, m: NoteMeasure): void {
  const d = view.measureHits.find((h) => h.m.id === m.id);
  const x = d ? Math.min(d.xa, d.xb) : view.plot().x;
  const y = d ? d.y - (view.fs + 4) : view.plot().y;
  askText(view, x, y, (text) => {
    if (text !== null) changeMeasure(view, m, { text: text || null });
  }, { value: m.text ?? "", placeholder: "Its text: {time}, {events}, {change} (empty: the time)", label: "The measure's text" });
}

/** The measure whose label is at a point, or whose line where it has no label (null:
 * none). */
export function labelAt(view: TimelineView, p: { x: number; y: number }): NoteMeasure | null {
  const h = view.fs + 4;
  for (let k = view.measureHits.length - 1; k >= 0; k--) {
    const d = view.measureHits[k];
    const [l, r] = d.lx === null ? [Math.min(d.xa, d.xb), Math.max(d.xa, d.xb)] : [d.lx, d.lx + d.tw];
    const half = d.lx === null ? 5 : h / 2;
    if (p.x >= l && p.x <= r && p.y >= d.y - half && p.y <= d.y + half) return d.m;
  }
  return null;
}

/** The end of the selected measure at a point, to drag (null: none). */
export function handleAt(view: TimelineView, p: { x: number; y: number }): { m: NoteMeasure; end: "a" | "b" } | null {
  const d = view.measureHits.find((h) => h.m.id === view.selectedMeasure);
  if (!d || !editable(view, d.m)) return null;
  for (const [end, x] of [["a", d.xa], ["b", d.xb]] as const) {
    if (Math.hypot(p.x - x, p.y - d.y) <= HANDLE_PX) return { m: d.m, end };
  }
  return null;
}

/** A measure's tooltip: both ends' times and the time between, exactly; between samples,
 * their values, the change and its rate. */
export function describe(view: TimelineView, m: NoteMeasure): string[][] {
  const axis = view.axis;
  if (!axis) return [];
  const rows = [
    ["from", axis.formatFull(m.a.x)],
    ["to", axis.formatFull(m.b.x)],
    ["time", axis.formatMeasureExact(m.span)],
  ];
  if (m.events !== null) rows.push(["events between", String(m.events)]);
  if (m.change !== null && m.change !== undefined) {
    rows.push(["values", `${fmtNumber(m.a.value ?? NaN)} → ${fmtNumber(m.b.value ?? NaN)}`], ["change", changeText(m.change)]);
    const rate = axis.formatRate(m.change, m.span);
    if (rate) rows.push(["rate", rate]);
  }
  if (m.id >= 0) rows.push(["in Python", `plot.notes[${m.id}]`]);
  return rows;
}

// ---------------------------------------------------------------------- copy as Python

/** An end as Python: atl.start(row) or atl.end(row, "layer") for a mark whose table row the
 * page has; else its time. */
function endPython(view: TimelineView, e: NoteEnd): string {
  const rows = e.layer !== undefined ? view.tableRows[e.layer] : undefined;
  if (e.side && e.layer !== undefined && e.index !== undefined && rows) {
    const one = view.layers.length + view.bars.length + view.values.length === 1;
    const layer = one ? "" : `, ${JSON.stringify(e.layer)}`;
    return `atl.${e.side}(${rows[e.index]}${layer})`;
  }
  return timePython(view, e.x);
}

/** A time (ticks) as a Python value of the data's kind: ISO text in UTC (exact to the data's
 * unit), a numpy duration, or a number. */
export function timePython(view: TimelineView, x: number): string {
  const axis = view.axis;
  const kind = view.spec?.time.kind;
  if (!axis || kind === "number" || kind === "order") return String((view.spec?.time.origin ?? 0) + x);
  const ns = axis.nsOf(x);
  if (kind === "duration") return `np.timedelta64(${ns}, "ns")`;
  const ms = Number(ns / 1_000_000n);
  const sub = Number(((ns % 1_000_000_000n) + 1_000_000_000n) % 1_000_000_000n);
  const iso = new Date(ms - (((ms % 1000) + 1000) % 1000)).toISOString().slice(0, 19);
  const frac = sub ? `.${String(sub).padStart(9, "0").replace(/0+$/, "")}` : "";
  return JSON.stringify(`${iso}${frac}`);
}

/** A measure as a line of Python that makes it again, with where it goes. */
export function asPython(view: TimelineView, m: NoteMeasure): string {
  const args = [endPython(view, m.a), endPython(view, m.b)];
  if (m.text !== null) args.push(JSON.stringify(m.text));
  const names = view.spec?.lanes?.names ?? [];
  if (m.lane !== null && names[m.lane] !== undefined) args.push(`lane=${JSON.stringify(String(names[m.lane]))}`);
  const at = m.at ?? "auto";
  if (typeof at === "object") {
    const one = view.values.length === 1;
    args.push(`at=atl.value(${at.value}${one ? "" : `, ${JSON.stringify(at.layer)}`})`);
  } else if (at !== "auto") args.push(`at=${JSON.stringify(at)}`);
  if (m.level !== null && m.level !== undefined) args.push(`level=${m.level}`);
  if (m.nudge) args.push(`nudge=${m.nudge}`);
  return `plot.measure(${args.join(", ")})`;
}
