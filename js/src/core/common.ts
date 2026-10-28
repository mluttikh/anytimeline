// What the view's modules share: what is under the pointer, boxes, layers and the theme,
// sizes, and small helpers.

import type { Detail } from "./levels";
import type { MarkLayerDraw } from "./renderers/renderer";
import { type EventsData, parseHex } from "./scene";
import type { SceneSpec, XScale } from "./types";

/** What is under the pointer: an event, a bar (`bar`), a sample of a values layer (`val`) or
 * a bin of an events layer sent as levels (`bin`: `index` is the bin's in the level drawn);
 * `layer` indexes the view's events layers, bars or values accordingly. */
export type Hit = { layer: number; index: number; bar?: boolean; val?: boolean; bin?: boolean };

export const PAD_RIGHT = 10;
export const PAD_BOTTOM = 8;
export const MIN_LANE = 18;
export const AUTO_LANE = 30;
/** A zoom or selection box narrower than this (px) is a click. */
export const MIN_BOX = 8;
export const DOUBLE_CLICK_MS = 300;
/** Views remembered for Back. */
export const HISTORY = 20;
export const HOVER_PX = 9;
/** The most lanes a states layer's tooltip lists. */
export const STATE_TIP_LANES = 16;
export const LABEL_BUDGET = 3000;
export const ROUTE_BUDGET = 60_000;
/** Break marks of long gaps (Order scale) at least this far apart (px); the longest win. */
export const GAP_PX = 28;

export type Gesture =
  | { kind: "click"; layer: string; index: number; mode: SelectMode }
  | { kind: "box"; x: [number, number]; lanes: [number, number]; shown?: number[]; xscale: XScale; mode: SelectMode; layer?: string }
  | { kind: "clear" };
export type SelectMode = "replace" | "add" | "remove" | "toggle";

/** What a drag does: set when it starts, from the tool, the keys held and where it starts. */
export type DragMode = "pan" | "zoom" | "select" | "axis" | "note" | "measure" | "handle";
/** A zoom range (a band over all lanes), a selection box, or a time range to select. */
export type BoxKind = "range" | "select" | "range-select";
export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  kind: BoxKind;
}

export interface Layer {
  /** The events: all of the layer's, or a window's (a layer sent as levels). */
  data: EventsData;
  /** A layer sent as levels: its levels and windows. */
  detail?: Detail;
  /** A window's events: each one's index among the layer's (null: the events are all). */
  index?: Uint32Array | null;
  draw: MarkLayerDraw;
  /** Screen x per event (CSS px, plot-relative) of the last cull. */
  xs: Float64Array;
  /** The range in x units that dodging covered, and at which scale. */
  dodged: { left: number; right: number; scale: number; laneH: number } | null;
  /** The marks' sizes as the layer gives them (data.size holds them × the mark scale). */
  baseSize: Float32Array;
}

export interface Theme {
  bg: string;
  text: string;
  muted: string;
  grid: string;
  band: string;
  select: string;
  accent: string;
}

// ---------------------------------------------------------------------- helpers

/** Attributes by which hosts switch light and dark: JupyterLab (data-jp-theme-light), VS Code
 * (class vscode-dark, data-vscode-theme-kind), marimo and others (class dark, data-theme),
 * Material for MkDocs / Zensical (data-md-color-scheme). */
export const THEME_ATTRIBUTES = ["class", "data-jp-theme-light", "data-vscode-theme-kind", "data-theme", "data-md-color-scheme"];

export const fontFamily = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

export function div(cls: string): HTMLDivElement {
  const d = document.createElement("div");
  d.className = cls;
  return d;
}

export function canvas(cls: string): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.className = `atl-canvas ${cls}`;
  return c;
}

export function rgb01(css: string): [number, number, number] {
  const m = css.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const [r, g, b] = m[1].split(/[ ,/]+/).map(Number);
    return [r / 255, g / 255, b / 255];
  }
  const [r, g, b] = parseHex(css);
  return [r / 255, g / 255, b / 255];
}

export function ellipsize(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  if (ctx.measureText(text).width <= width) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ctx.measureText(text.slice(0, mid) + "…").width <= width) lo = mid;
    else hi = mid - 1;
  }
  return text.slice(0, lo) + "…";
}

/** A click: Shift/Ctrl/⌘ add or remove the event, Alt removes it, else it replaces. */
export function clickMode(e: MouseEvent): SelectMode {
  if (e.altKey) return "remove";
  if (e.shiftKey || e.ctrlKey || e.metaKey) return "toggle";
  return "replace";
}

/** A box: Shift/Ctrl/⌘ add what is inside, Alt removes it, else it replaces. */
export function boxMode(e: MouseEvent): SelectMode {
  if (e.altKey) return "remove";
  if (e.shiftKey || e.ctrlKey || e.metaKey) return "add";
  return "replace";
}

/**
 * Long gaps between consecutive events (sequence scale): at rank k + 0.5 when the time
 * from event k to k + 1 is over 20× the median gap; at most one gap per 50 events (the
 * longest).
 */
export function findGaps(times: Float64Array | null): { at: number; span: number }[] {
  if (!times || times.length < 3) return [];
  const diffs = new Float64Array(times.length - 1);
  for (let i = 0; i < diffs.length; i++) diffs[i] = times[i + 1] - times[i];
  const sorted = Float64Array.from(diffs).sort();
  const median = sorted[Math.floor(sorted.length / 2)];
  const mean = sorted.reduce((a, b) => a + b, 0) / sorted.length;
  let threshold = median > 0 ? median * 20 : mean * 10;
  const most = Math.max(1, Math.floor(diffs.length / 50));
  if (sorted.length > most) threshold = Math.max(threshold, sorted[sorted.length - most - 1]);
  if (!(threshold > 0)) return [];
  const out: { at: number; span: number }[] = [];
  for (let i = 0; i < diffs.length; i++) if (diffs[i] > threshold) out.push({ at: i + 0.5, span: diffs[i] });
  return out;
}

/** Gaps Python found (plots with layers sent as levels): rows of rank and span. */
export function gapsOf(rows: Float64Array): { at: number; span: number }[] {
  const out: { at: number; span: number }[] = [];
  for (let i = 0; i + 1 < rows.length; i += 2) out.push({ at: rows[i], span: rows[i + 1] });
  return out;
}

export function lowerBoundBy(a: { at: number }[], x: number): number {
  let lo = 0;
  let hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (a[mid].at < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The row of each event's lane (a float per event, for the GPU); -1 for hidden lanes. */
export function rowsOf(lane: Uint32Array, slot: Int32Array): Float32Array {
  const out = new Float32Array(lane.length);
  for (let i = 0; i < lane.length; i++) out[i] = slot[lane[i]] ?? -1;
  return out;
}

/** What identifies a plot's lanes: when it is the same, folding is kept. */
export function treeKey(spec: SceneSpec): string {
  const t = spec.lanes.tree;
  return t ? `${spec.lanes.names.length}:${t.depth.length}:${spec.lanes.names.slice(0, 50).join("\u0001")}` : "";
}

/** Event i of a layer as Python knows it: its index among the layer's events (a window's
 * events are some of them). */
export function globalIndex(l: Layer, i: number): number {
  return l.index ? l.index[i] : i;
}

/** Whether an events layer puts its text in boxes on stems (a story timeline). */
export function isStems(l: Layer): boolean {
  return l.data.spec.labels === "stems";
}
