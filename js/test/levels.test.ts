import { describe, expect, it } from "vitest";
import { type BinsData, BinsLayer } from "../src/core/levels";
import { FLAG_SELECTED } from "../src/core/renderers/renderer";
import type { LevelSpec } from "../src/core/types";

/** Bins of two lanes: lane 0 holds 0–2 (3 events), 5 (one) and 8–9 (2); lane 1 holds 1–4 (4).
 * Places in the order are ten times the times. */
function bins(scale: "time" | "order" = "time"): BinsData {
  const f = scale === "order" ? 10 : 1;
  return {
    spec: { lo: { id: "lo" } } as unknown as LevelSpec,
    scale,
    k: 0,
    count: 4,
    most: 4,
    laneStarts: new Uint32Array([0, 3, 4]),
    lane: new Uint32Array([0, 0, 0, 1]),
    lo: new Float64Array([0, 5, 8, 1].map((x) => x * f)),
    hi: new Float64Array([2, 5, 9, 4].map((x) => x * f)),
    n: new Uint32Array([3, 1, 2, 4]),
    top: new Uint32Array([0, 3, 4, 6]),
    color: new Uint8Array(16),
    themeColor: false,
    alpha: 1,
    symbol: new Uint8Array(4),
    size: new Float32Array(4).fill(8),
  };
}

/** Which bins are flagged selected, in bin order. */
function flagged(b: BinsLayer): number[] {
  const out: number[] = [];
  b.barBin.forEach((i, j) => b.bars.flags.data[4 * j] & FLAG_SELECTED && out.push(i));
  b.markBin.forEach((i, j) => b.marks.sf.data[4 * j + 1] & FLAG_SELECTED && out.push(i));
  return out.sort();
}

describe("levels: a selection over bins", () => {
  it("flags the bins that hold a selected event, in its lane", () => {
    const b = new BinsLayer(bins());
    // (time, place in the order, lane): 1.5 in lane 0, 5 in lane 0, 3 in lane 1, 7 (no bin)
    b.select(new Float64Array([1.5, 15, 0, 5, 50, 0, 3, 30, 1, 7, 70, 0]));
    expect(flagged(b)).toEqual([0, 1, 3]);
    b.select(undefined);
    expect(flagged(b)).toEqual([]);
  });

  it("takes the places in the order for bins of the Order scale", () => {
    const b = new BinsLayer(bins("order"));
    b.select(new Float64Array([0, 85, 0]));
    expect(flagged(b)).toEqual([2]);
  });
});
