// Typed-array views of a layer's buffers, and the per-event arrays the renderers draw.

import type { BufferRef, DataSource, EventsLayerSpec } from "./types";

export function view(ref: BufferRef, source: DataSource): ArrayBufferView & ArrayLike<number> {
  const buf = source.get(ref.id);
  switch (ref.dtype) {
    case "float64":
      return new Float64Array(buf);
    case "float32":
      return new Float32Array(buf);
    case "int32":
      return new Int32Array(buf);
    case "uint32":
      return new Uint32Array(buf);
    case "uint16":
      return new Uint16Array(buf);
    case "uint8":
      return new Uint8Array(buf);
    default:
      throw new Error(`cannot view a ${ref.dtype} buffer as numbers`);
  }
}

/** Strings encoded as count + 1 uint32 offsets, then UTF-8 bytes (Python encode_strings). */
export function decodeStrings(ref: BufferRef, source: DataSource): string[] {
  const buf = source.get(ref.id);
  const n = ref.count;
  const offsets = new Uint32Array(buf, 0, n + 1);
  const bytes = new Uint8Array(buf, 4 * (n + 1));
  const dec = new TextDecoder();
  const out = new Array<string>(n);
  for (let i = 0; i < n; i++) out[i] = dec.decode(bytes.subarray(offsets[i], offsets[i + 1]));
  return out;
}

/** Every buffer id a spec (or a part of one) refers to; the levels of layers sent as levels
 * (fetched when they are drawn) only with `levels`. */
export function specBufferIds(spec: unknown, levels = false): string[] {
  const ids: string[] = [];
  const walk = (v: unknown): void => {
    if (!v || typeof v !== "object") return;
    if (Array.isArray(v)) return v.forEach(walk);
    const o = v as Record<string, unknown>;
    if (typeof o.id === "string" && typeof o.byteLength === "number") ids.push(o.id);
    else for (const [k, x] of Object.entries(o)) if (levels || k !== "levels") walk(x);
  };
  walk(spec);
  return ids;
}

/** The symbol names the shaders know, in index order (Python's SYMBOLS). */
export const SYMBOLS = [
  "circle", "square", "diamond", "triangle", "triangle-down", "cross", "x", "tick",
  "circle-open", "square-open", "diamond-open", "triangle-open", "triangle-down-open",
];

/** One events layer, decoded: sorted by lane, then time. */
export interface EventsData {
  spec: EventsLayerSpec;
  count: number;
  time: Float64Array;
  rank: Float64Array;
  lane: Uint32Array;
  laneStarts: Uint32Array;
  /** Per event, ready for the GPU. */
  laneF: Float32Array;
  size: Float32Array;
  color: Uint8Array;
  symbol: Uint8Array;
  text: string[] | null;
  importance: Float32Array | null;
  /** Pairs of event indices. */
  segments: Uint32Array | null;
  /** True when colours follow the theme (filled at draw time). */
  themeColor: boolean;
}

export function decodeEvents(spec: EventsLayerSpec, source: DataSource): EventsData {
  const n = spec.count;
  const time = Float64Array.from(view(spec.time, source) as ArrayLike<number>);
  const rankRaw = view(spec.rank, source);
  const rank = rankRaw instanceof Float64Array ? rankRaw : Float64Array.from(rankRaw);
  const lane = view(spec.lane, source) as Uint32Array;
  const laneStarts = view(spec.lane_starts, source) as Uint32Array;
  const laneF = Float32Array.from(lane);
  const size = new Float32Array(n);
  if (spec.size.values) size.set(view(spec.size.values, source) as Float32Array);
  else size.fill(spec.size.value ?? 8);
  let color: Uint8Array;
  let themeColor = false;
  if (spec.color.rgba) color = new Uint8Array(view(spec.color.rgba, source) as Uint8Array);
  else {
    color = new Uint8Array(n * 4);
    if (spec.color.solid === "theme" || !spec.color.solid) themeColor = true;
    else fillSolid(color, spec.color.solid, spec.color.alpha);
  }
  const symbol = new Uint8Array(n);
  if (spec.symbol.values) symbol.set(view(spec.symbol.values, source) as Uint8Array);
  else symbol.fill(Math.max(0, SYMBOLS.indexOf(spec.symbol.value ?? "circle")));
  return {
    spec,
    count: n,
    time,
    rank,
    lane,
    laneStarts,
    laneF,
    size,
    color,
    symbol,
    text: spec.text ? decodeStrings(spec.text, source) : null,
    importance: spec.importance ? (view(spec.importance, source) as Float32Array) : null,
    segments: spec.route ? (view(spec.route.segments, source) as Uint32Array) : null,
    themeColor,
  };
}

/** Fill RGBA bytes with one colour (hex) and alpha (0–255). */
export function fillSolid(target: Uint8Array, hex: string, alpha = 255): void {
  const [r, g, b] = parseHex(hex);
  for (let i = 0; i < target.length; i += 4) {
    target[i] = r;
    target[i + 1] = g;
    target[i + 2] = b;
    target[i + 3] = alpha;
  }
}

export function parseHex(hex: string): [number, number, number] {
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3 || h.length === 4) h = [...h.slice(0, 3)].map((c) => c + c).join("");
  const v = parseInt(h.slice(0, 6), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

/** First index in sorted `a[lo, hi)` with a[i] >= x. */
export function lowerBound(a: ArrayLike<number>, x: number, lo = 0, hi = a.length): number {
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (a[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** First index in sorted `a[lo, hi)` with a[i] > x. */
export function upperBound(a: ArrayLike<number>, x: number, lo = 0, hi = a.length): number {
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (a[mid] <= x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}
