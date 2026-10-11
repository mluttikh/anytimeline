// Linked plots: views in one group follow each other's time range and show each other's
// pointer as a line, and share the width of the lane names and of the legend so their time
// axes line up. The group lives in a registry on the page's global object, so plots of
// separately loaded bundles (each notebook output its own) find each other.
//
// Times go between views as positions in the sender's time base, with the base: each view
// converts them into its own (another origin, another unit). With align "start", each plot's
// first time is 0: plots of different periods (two traces, two weeks) line up from their start.

import type { TimeSpec } from "./types";
import { UNIT_NS } from "./time";

export type Align = "time" | "start";

export interface LinkSpec {
  group: string;
  align: Align;
}

/** A view's time base, as linking needs it. */
export interface LinkFrame {
  kind: TimeSpec["kind"];
  originNs: bigint;
  origin: number;
  /** Nanoseconds per tick (1 for plain numbers). */
  unitNs: number;
  /** The first time of the plot's data (ticks): 0 of align "start". */
  start: number;
}

/** What a view offers the others of its group. */
export interface LinkPeer {
  readonly group: string;
  frame(): LinkFrame | null;
  /** The plot's extent (ticks), for the group's limits. */
  extent(): [number, number] | null;
  /** The time range shown (ticks), or null before data. */
  range(): [number, number] | null;
  follow(range: [number, number], from: LinkFrame, align: Align): void;
  cursor(at: number | null, from: LinkFrame | null, align: Align): void;
  /** Its own gutter (lane names) and right padding (legend), before sharing. */
  sizes(): { gutter: number; padRight: number };
  relayout(): void;
}

type Registry = Map<string, Set<LinkPeer>>;

function registry(): Registry {
  const g = globalThis as unknown as { __anytimelineLinks?: Registry };
  g.__anytimelineLinks ??= new Map();
  return g.__anytimelineLinks;
}

export function join(peer: LinkPeer): void {
  const reg = registry();
  if (!reg.has(peer.group)) reg.set(peer.group, new Set());
  reg.get(peer.group)!.add(peer);
}

export function leave(peer: LinkPeer): void {
  const reg = registry();
  const set = reg.get(peer.group);
  set?.delete(peer);
  if (set && !set.size) reg.delete(peer.group);
}

/** The other views of `peer`'s group. */
export function others(peer: LinkPeer): LinkPeer[] {
  return [...(registry().get(peer.group) ?? [])].filter((p) => p !== peer);
}

export function frameOf(t: TimeSpec): LinkFrame {
  return {
    kind: t.kind,
    originNs: BigInt(t.origin_ns || "0"),
    origin: t.origin,
    unitNs: t.kind === "number" || t.kind === "order" ? 1 : (UNIT_NS[t.unit] ?? 1),
    start: t.extent[0],
  };
}

/** Whether times of the two bases can be compared. */
export function compatible(a: LinkFrame, b: LinkFrame, align: Align): boolean {
  if (a.kind === "order" || b.kind === "order") return false;
  if (align === "start") return (a.kind === "number") === (b.kind === "number");
  return a.kind === b.kind;
}

/** Position `x` of base `from` in base `to`. */
export function convert(x: number, from: LinkFrame, to: LinkFrame, align: Align): number {
  if (align === "start") return to.start + ((x - from.start) * from.unitNs) / to.unitNs;
  if (from.kind === "number") return from.origin + x - to.origin;
  // the origins' difference exactly (BigInt), then as a number
  const shift = Number(from.originNs - to.originNs);
  return (shift + x * from.unitNs) / to.unitNs;
}
