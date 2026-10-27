// What every backend draws: instanced marks (events) and line segments (routes), in a plot
// rectangle. The view prepares per-event arrays; a backend caches them on the GPU by key and
// version, so only what changed is uploaded.

import type { RendererKind } from "../types";

/** An array with a version: the backend re-uploads it when the version changes. */
export interface Attr<T> {
  data: T;
  version: number;
}

/** Bits of the flags byte per event. */
export const FLAG_SELECTED = 1;
export const FLAG_HOVERED = 2;

export interface MarkLayerDraw {
  /** Identity of the layer's data (GPU caches are keyed by it). */
  key: string;
  count: number;
  /** Position along time, relative to the view's base (float32-safe). */
  x: Attr<Float32Array>;
  /** Lane index per event. */
  lane: Attr<Float32Array>;
  /** Vertical offset in CSS px (dodging). */
  dy: Attr<Float32Array>;
  /** Diameter in CSS px. */
  size: Attr<Float32Array>;
  /** RGBA bytes per event. */
  color: Attr<Uint8Array>;
  /** Per event 4 bytes: symbol index, flags, 0, 0. */
  sf: Attr<Uint8Array>;
  /** Screen x of an event: plot.x + (x − offset) × scale. */
  offset: number;
  scale: number;
  /** Screen y of lane l's centre: laneTop + (l + 0.5) × laneHeight. */
  laneTop: number;
  laneHeight: number;
  /** A selection exists: unselected events are drawn faded. */
  fade: boolean;
  /** The events in view (for backends that cull on the CPU), and how many of them. */
  visible: Uint32Array;
  visibleCount: number;
}

/** Bars (intervals): one instanced draw per layer, under the routes and events. */
export interface BarLayerDraw {
  key: string;
  count: number;
  /** Per bar: start and end, relative to the view's base (float32-safe). */
  x: Attr<Float32Array>;
  /** Per bar: lane, sub-row, sub-rows of its lane, progress (0-1, or −1 for none; −2 − f:
   * none, and the bar is f of its row's height, as the bins of levels of detail). */
  geom: Attr<Float32Array>;
  color: Attr<Uint8Array>;
  /** Per bar 4 bytes: flags (FLAG_SELECTED, BAR_MILESTONE, BAR_OPEN), 0, 0, 0. */
  flags: Attr<Uint8Array>;
  offset: number;
  scale: number;
  laneTop: number;
  laneHeight: number;
  /** The bars' height as a fraction of the lane, and their largest height in px. */
  fill: number;
  maxBar: number;
  fade: boolean;
  visible: Uint32Array;
  visibleCount: number;
}

export const BAR_MILESTONE = 4;
export const BAR_OPEN = 8;

/** Where a bar is drawn: centre y and height (px), from its lane and sub-row (and its
 * progress slot: −2 − f makes it f of the height). */
export function barBox(lane: number, row: number, rows: number, laneTop: number, laneHeight: number, fill: number, maxBar: number, progress = -1): { cy: number; h: number } {
  const pitch = (laneHeight * fill) / Math.max(1, rows);
  let h = Math.min(pitch * (rows > 1.5 ? 0.85 : 1), maxBar);
  if (progress < -1.5) h *= -progress - 2;
  return { cy: laneTop + (lane + 0.5) * laneHeight + (row - (rows - 1) * 0.5) * pitch, h };
}

export interface SegmentDraw {
  count: number;
  /** x1, y1, x2, y2 per segment, in CSS px. */
  coords: Float32Array;
  /** RGBA bytes per segment. */
  colors: Uint8Array;
  width: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface FrameDraw {
  plot: Rect;
  bars: BarLayerDraw[];
  segments: SegmentDraw[];
  layers: MarkLayerDraw[];
  /** Background, selection and hover colours, RGB 0-1. */
  background: [number, number, number];
  selection: [number, number, number];
  hover: [number, number, number];
}

export interface Renderer {
  readonly kind: RendererKind;
  readonly description: string;
  readonly canvas: HTMLCanvasElement;
  resize(cssWidth: number, cssHeight: number, dpr: number): void;
  render(frame: FrameDraw): void;
  /** Resolves when the GPU has finished the frames submitted so far. */
  finish(): Promise<void>;
  /**
   * The pixels of the next frame drawn (a snapshot), for backends whose canvas cannot be
   * copied into another canvas everywhere (WebGPU); others leave it out and are copied.
   */
  captureNext?(): Promise<ImageData>;
  /** Forget cached data whose key is not in `keys`. */
  retain(keys: Set<string>): void;
  destroy(): void;
  /** Called when the backend fails at run time (device lost, context lost). */
  onFailure: ((reason: string) => void) | null;
}

export interface RendererOptions {
  /** Accept a software implementation (a forced backend); "auto" refuses it. */
  allowSoftware: boolean;
}

/** Half the side of the quad drawn for a mark of diameter `size`: room for the rings. */
export function markExtent(size: number): number {
  return size / 2 + 4;
}
