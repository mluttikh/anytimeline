import { describe, expect, it } from "vitest";
import { asPython, commit, describe as describeMeasure, nearestHeld, stepHeld, timePython } from "../src/core/measure";
import { between, layoutMeasures, measureText, type NoteEnd, type NoteMeasure } from "../src/core/notes";
import { TimeAxis } from "../src/core/time";
import type { TimeSpec } from "../src/core/types";
import type { TimelineView } from "../src/core/view";

const DAYS: TimeSpec = { kind: "datetime", unit: "s", origin_ns: "1704067200000000000", origin: 0, timezone: "UTC", extent: [0, 86400 * 10] };

/** A view with one events layer (lane 0: times 1, 5, 9) and one intervals layer (lane 0:
 * bars 2–4 and 6–12), on the Time scale. */
function fakeView(over: Partial<Record<string, unknown>> = {}): TimelineView {
  const events = {
    data: { laneStarts: new Uint32Array([0, 3]), time: new Float64Array([1, 5, 9]), rank: new Float64Array([0, 3, 5]), lane: new Uint32Array([0, 0, 0]), spec: { name: "e" } },
    index: null,
  };
  const start = new Float64Array([2, 6]);
  const end = new Float64Array([4, 12]);
  const rankStart = new Float64Array([1, 4]);
  const rankEnd = new Float64Array([2, 6]);
  const bars = {
    data: { laneStarts: new Uint32Array([0, 2]), start, end, rankStart, rankEnd, lane: new Uint32Array([0, 0]), maxDur: new Float64Array([6]), maxDurRank: new Float64Array([2]), spec: { name: "b" } },
    ends: (order: boolean) => (order ? [rankStart, rankEnd] : [start, end]),
    globalIndex: (i: number) => i,
  };
  return {
    xscale: "time",
    layers: [events],
    bars: [bars],
    values: [],
    xsrc: (l: typeof events) => l.data.time,
    axis: new TimeAxis(DAYS),
    spec: { time: DAYS },
    tableRows: {},
    fs: 12,
    laneH: 30,
    camera: { left: 0, scale: 10 },
    slot: new Int32Array([0]),
    theme: { accent: "#1f77b4" },
    ...over,
  } as unknown as TimelineView;
}

const end = (x: number, r: number | null = null): NoteEnd => ({ x, r, lane: null, side: null });

describe("measures: the events between", () => {
  it("counts the instants strictly between two places", () => {
    expect(between(0, 3)).toBe(2); // two marks' own places: 1 and 2 between
    expect(between(3, 0)).toBe(2);
    expect(between(-0.5, 2.5)).toBe(3); // times between instants: 0, 1, 2
    expect(between(1, 1)).toBe(0);
    expect(between(null, 2)).toBeNull();
  });
});

describe("measures: the label", () => {
  const m = (span: number, events: number | null, text: string | null = null): NoteMeasure => ({ a: end(0), b: end(span), span, events, lane: null, text, color: null, id: 0 });

  it("is the time, to three digits; on the Order scale with the events between", () => {
    expect(measureText(fakeView(), m(5400, 3))).toBe("1.5 h");
    expect(measureText(fakeView({ xscale: "order" }), m(5400, 3))).toBe("1.5 h · 3 events");
    expect(measureText(fakeView({ xscale: "order" }), m(-90, 1))).toBe("1.5 min · 1 event");
  });

  it("fills in {time} and {events}", () => {
    expect(measureText(fakeView(), m(60, 2, "gap: {time} ({events})"))).toBe("gap: 1 min (2 events)");
  });
});

describe("measures: snapping to edges", () => {
  it("takes the nearest start or end in the lane, within reach", () => {
    const v = fakeView();
    expect(nearestHeld(v, 0, 4.3, 0.8)).toMatchObject({ x: 4, side: "end", layer: "b", index: 0 });
    expect(nearestHeld(v, 0, 5.2, 0.8)).toMatchObject({ x: 5, side: "start", layer: "e", index: 1 });
    expect(nearestHeld(v, 0, 7.5, 0.8)).toBeNull();
    expect(nearestHeld(v, 1, 5, 0.8)).toBeNull(); // no such lane
  });

  it("steps to the next or previous edge", () => {
    const v = fakeView();
    expect(stepHeld(v, 0, 4, true)).toMatchObject({ x: 5, layer: "e" });
    expect(stepHeld(v, 0, 9, true)).toMatchObject({ x: 12, side: "end", layer: "b", index: 1 });
    expect(stepHeld(v, 0, 2, false)).toMatchObject({ x: 1, layer: "e", index: 0 });
    expect(stepHeld(v, 0, 12, true)).toBeNull();
  });

  it("uses the places in the order on the Order scale", () => {
    const v = fakeView({ xscale: "order", xsrc: (l: { data: { rank: Float64Array } }) => l.data.rank });
    expect(nearestHeld(v, 0, 2.2, 0.5)).toMatchObject({ x: 4, r: 2, side: "end", layer: "b" });
  });
});

/** fakeView with a values layer "cpu": lane 0, samples at 3 (10), 7 (NaN, a gap) and 11 (4). */
function withSamples(over: Partial<Record<string, unknown>> = {}): TimelineView {
  const cpu = {
    data: { spec: { name: "cpu" }, time: new Float64Array([3, 7, 11]), value: new Float32Array([10, NaN, 4]), runStarts: new Uint32Array([0, 3]), runLane: new Uint32Array([0]) },
    xs: () => new Float64Array([3, 7, 11]),
    globalIndex: (i: number) => i,
  };
  return fakeView({ values: [cpu], valueView: () => ({}), seq: null, localMeasures: [], callbacks: {}, selectMeasure: () => {}, ...over });
}

describe("measures: samples of a values layer", () => {
  it("are ends: their time, their value; gaps are not", () => {
    const v = withSamples();
    expect(nearestHeld(v, 0, 3.4, 0.8)).toMatchObject({ x: 3, side: "start", layer: "cpu", index: 0, value: 10 });
    expect(nearestHeld(v, 0, 7, 0.8)).toBeNull();
    expect(stepHeld(v, 0, 9.5, true)).toMatchObject({ x: 11, layer: "cpu", index: 2, value: 4 });
  });

  it("measured from one to another, show the change in value and its rate", () => {
    const v = withSamples();
    const a = nearestHeld(v, 0, 3, 0.5)!;
    const b = nearestHeld(v, 0, 11, 0.5)!;
    commit(v, a, b, null);
    const [m] = v.localMeasures;
    expect(m.change).toBe(-6);
    expect(measureText(v, m)).toBe("8 s · Δ \u22126");
    expect(measureText(v, { ...m, text: "{change} in {time}" })).toBe("\u22126 in 8 s");
    expect(describeMeasure(v, m)).toContainEqual(["change", "\u22126"]);
    expect(describeMeasure(v, m)).toContainEqual(["rate", "\u22120.75 per s"]);
    // a sample and a bar's edge: no change
    commit(v, a, nearestHeld(v, 0, 4, 0.5)!, null);
    expect(v.localMeasures[1].change).toBeNull();
    expect(measureText(v, v.localMeasures[1])).toBe("1 s");
  });
});

describe("measures: their lines", () => {
  const ctx = { measureText: (t: string) => ({ width: 6 * t.length }) } as unknown as CanvasRenderingContext2D;
  const plot = { x: 0, y: 0, w: 1000, h: 300 };
  const at = (lane: number, x: number): NoteEnd => ({ x, r: null, lane, side: "start" });
  const m = (a: number, b: number, id: number): NoteMeasure => ({ a: at(0, a), b: at(0, b), span: b - a, events: null, lane: null, text: null, color: null, id });

  it("stack in a row when they overlap, and share a level when they do not", () => {
    const laid = layoutMeasures(fakeView(), ctx, [m(0, 30, 0), m(10, 40, 1), m(60, 90, 2)], plot, 0);
    const y = Object.fromEntries(laid.map((d) => [d.m.id, d.y]));
    expect(y[1]).toBeGreaterThan(y[0]);
    expect(y[2]).toBe(y[0]);
  });

  it("put the label beyond the right end when the line is too short for it", () => {
    const [d] = layoutMeasures(fakeView(), ctx, [m(10, 11, 0)], plot, 0);
    expect(d.lx).toBe(d.xb + 6);
  });
});

describe("measures: copy as Python", () => {
  it("writes times in UTC, exactly", () => {
    const v = fakeView();
    expect(timePython(v, 0)).toBe('"2024-01-01T00:00:00"');
    expect(timePython(v, 90.5)).toBe('"2024-01-01T00:01:30.5"');
  });

  it("writes plain numbers as numbers", () => {
    const spec = { ...DAYS, kind: "number", unit: "", origin_ns: "0", origin: 100 } as TimeSpec;
    expect(timePython(fakeView({ axis: new TimeAxis(spec), spec: { time: spec } }), 2.5)).toBe("102.5");
  });

  it("writes marks' edges by their table rows", () => {
    const v = fakeView({ tableRows: { b: new Uint32Array([7, 3]), e: new Uint32Array([0, 1, 2]) } });
    const a: NoteEnd = { x: 2, r: 1, lane: 0, side: "start", layer: "b", index: 1 };
    const b: NoteEnd = { x: 9, r: 5, lane: 0, side: "end", layer: "e", index: 2 };
    expect(asPython(v, { a, b, span: 7, events: 0, lane: null, text: null, color: null, id: -1 })).toBe('plot.measure(atl.start(3, "b"), atl.end(2, "e"))');
    expect(asPython(v, { a: end(0), b, span: 9, events: 0, lane: null, text: null, color: null, id: -1 })).toBe('plot.measure("2024-01-01T00:00:00", atl.end(2, "e"))');
  });
});
