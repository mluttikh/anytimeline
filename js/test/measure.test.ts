import { describe, expect, it } from "vitest";
import { asPython, changeMeasure, commit, describe as describeMeasure, nearestHeld, placeAt, stepHeld, stepLevel, timePython, toAuto } from "../src/core/measure";
import { bandHeight, between, laneLevels, layoutMeasures, measureText, type MeasureChange, type NoteEnd, type NoteMeasure } from "../src/core/notes";
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
    showMeasures: () => {},
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
  const plot = { x: 0, y: 40, w: 1000, h: 300 };
  const at = (lane: number, x: number): NoteEnd => ({ x, r: null, lane, side: "start" });
  const m = (a: number, b: number, id: number, over: Partial<NoteMeasure> = {}): NoteMeasure => ({ a: at(0, a), b: at(0, b), span: b - a, events: null, lane: null, text: null, color: null, id, ...over });
  const view = (over: Partial<Record<string, unknown>> = {}) => fakeView({ measureBands: { head: 0, foot: 0 }, laneH: 100, ...over });
  const lay = (ms: NoteMeasure[], over: Partial<Record<string, unknown>> = {}) => layoutMeasures(view(over), ctx, ms, plot, 40);

  it("stack in a row when they overlap, and share a level when they do not", () => {
    const { laid } = lay([m(0, 30, 0), m(10, 40, 1), m(60, 90, 2), m(90, 95, 3)]);
    const k = Object.fromEntries(laid.map((d) => [d.m.id, d.k]));
    expect(k).toEqual({ 0: 0, 1: 1, 2: 0, 3: 0 }); // touching ends share a level
    expect(laid[1].y).toBe(laid[0].y + 20);
  });

  it("keep their levels at any zoom: labels without room are hidden, never lifted", () => {
    const ms = [m(0, 3, 0, { text: "a long label" }), m(4, 8, 1, { text: "another long one" })];
    for (const scale of [0.5, 10, 400]) {
      const { laid } = lay(ms, { camera: { left: 0, scale } });
      expect(laid.map((d) => d.k)).toEqual([0, 0]);
    }
    const near = lay(ms, { camera: { left: 0, scale: 10 } }).laid;
    expect(near[0].lx).toBeNull(); // 30 px: no room on the line, and the next line is beside it
    expect(near[1].lx).toBe(near[1].xb + 6);
  });

  it("put the label beyond the right end when the line is too short for it", () => {
    const [d] = lay([m(10, 11, 0)]).laid;
    expect(d.lx).toBe(d.xb + 6);
  });

  it("keep a level they are given, and the others go around it", () => {
    const { laid } = lay([m(0, 30, 0), m(10, 40, 1, { level: 0 })]);
    expect(laid.map((d) => d.k)).toEqual([1, 0]);
  });

  it("go where they are put: top, middle, bottom, between, with a nudge", () => {
    const ys = (["top", "middle", "bottom", "between"] as const).map((place) => lay([m(0, 30, 0, { at: place })]).laid[0].y);
    // lane 0 runs from 40 to 140; text 12 px: a label 16 high
    expect(ys).toEqual([40 + 3 + 8, 90, 140 - 3 - 8, 140]);
    expect(lay([m(0, 30, 0, { nudge: -4 })]).laid[0].y).toBe(47);
  });

  it("go to the header when their lane cannot hold them, or when they are in no lane", () => {
    // a lane of 30 px holds one level
    const { laid, head, foot } = lay([m(0, 30, 0), m(10, 40, 1), m(20, 50, 2, { at: "top" }), m(5, 6, 3, { a: end(5), b: end(6) })], { laneH: 30 });
    expect(laid.map((d) => d.place.split(" ")[0])).toEqual(["top", "header", "top", "header"]);
    expect(laid[2].k).toBe(1); // put at the top: it stays, over the lane's edge
    expect([head, foot]).toEqual([1, 0]); // the two in the header do not overlap
    expect(laid[1].y).toBe(40 + 3 + 8); // the band is above the lanes (here: none yet)
  });

  it("give the bands' heights: a band takes room only when used", () => {
    expect(bandHeight(0, 12)).toBe(0);
    expect(bandHeight(1, 12)).toBe(22);
    expect(bandHeight(3, 12)).toBe(62);
    expect(laneLevels(30, 12)).toBe(1);
    expect(laneLevels(100, 12)).toBe(4);
  });
});

describe("measures: moved in the plot", () => {
  const ctx = { measureText: (t: string) => ({ width: 6 * t.length }) } as unknown as CanvasRenderingContext2D;
  const plot = { x: 0, y: 40, w: 1000, h: 300 };
  const at = (lane: number, x: number): NoteEnd => ({ x, r: null, lane, side: "start" });
  const m = (over: Partial<NoteMeasure> = {}): NoteMeasure => ({ a: at(0, 0), b: at(0, 30), span: 30, events: null, lane: null, text: null, color: null, id: 0, ...over });
  /** Three lanes of 100 px from y 40, a measure laid out and selected; what it sends. */
  const setup = (measure: NoteMeasure) => {
    const sent: [number, MeasureChange][] = [];
    const notices: string[] = [];
    const v = fakeView({
      measureBands: { head: 0, foot: 0 },
      laneH: 100,
      scrollY: 0,
      laneAt: new Int32Array([0, 1, 2]),
      slot: new Int32Array([0, 1, 2]),
      plot: () => plot,
      callbacks: { onNoteEnd: () => {}, onNoteChange: (id: number, c: MeasureChange) => sent.push([id, c]) },
      flashNotice: (t: string) => notices.push(t),
      localMeasures: [],
      requestRender: () => {},
    });
    v.measureHits = layoutMeasures(v, ctx, [measure], plot, 40).laid;
    v.selectedMeasure = measure.id;
    return { v, d: v.measureHits[0], sent, notices };
  };

  it("go to the nearest place in the row under the pointer, at a level that holds", () => {
    const { v, d } = setup(m());
    // lane 0 from 40 to 140: top levels at 51, 71, ...; the middle at 90; bottom levels at
    // 129, 109, ...; the border under it at 140
    expect(placeAt(v, d, 52)).toBeNull(); // where it is
    expect(placeAt(v, d, 73)).toEqual({ at: "top", level: 1 });
    expect(placeAt(v, d, 90)).toEqual({ at: "middle", level: 0 });
    expect(placeAt(v, d, 128)).toEqual({ at: "bottom", level: 0 });
    expect(placeAt(v, d, 141)).toEqual({ at: "between", level: 0 }); // just under the border
    expect(placeAt(v, d, 152)).toEqual({ at: "top", level: 0, lane: 1 }); // another lane
  });

  it("go into the header above the lanes, or the footer below them", () => {
    const { v, d } = setup(m());
    expect(placeAt(v, d, 10)).toEqual({ at: "header", level: 0 });
    expect(placeAt(v, d, 352)).toEqual({ at: "footer", level: 0 });
    expect(placeAt(v, d, 372)).toEqual({ at: "footer", level: 1 });
  });

  it("step a level with Up and Down: down from a top, up from a bottom", () => {
    const top = setup(m({ at: "top" }));
    expect(stepLevel(top.v, false)).toBe(true);
    expect(top.sent).toEqual([[0, { at: "top", level: 1 }]]);
    expect(stepLevel(top.v, true)).toBe(true); // already at level 0
    expect(top.notices).toHaveLength(1);
    const bottom = setup(m({ at: "bottom", level: 1 }));
    stepLevel(bottom.v, true);
    expect(bottom.sent).toEqual([[0, { at: "bottom", level: 2 }]]);
    // an "auto" one goes from where it is laid
    const auto = setup(m());
    stepLevel(auto.v, false);
    expect(auto.sent).toEqual([[0, { at: "top", level: 1 }]]);
  });

  it("go back to automatic, and a page changes its own", () => {
    const { v, sent } = setup(m({ at: "bottom", level: 2, lane: 1 }));
    toAuto(v, m({ at: "bottom", level: 2, lane: 1 }));
    expect(sent).toEqual([[0, { at: "auto", level: null, lane: null }]]); // its ends are marks
    const own = m({ id: -1, at: "top" });
    v.localMeasures = [own];
    changeMeasure(v, own, { at: "footer", level: 0, text: "x" });
    expect(v.localMeasures[0]).toMatchObject({ at: "footer", level: 0, text: "x" });
    expect(sent).toHaveLength(1);
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

  it("writes where it goes", () => {
    const v = fakeView({ spec: { time: DAYS, lanes: { names: ["api", "db"] } } });
    const m: NoteMeasure = { a: end(0), b: end(9), span: 9, events: 0, lane: 1, text: "wait {time}", color: null, id: -1, at: "bottom", level: 2, nudge: -3 };
    expect(asPython(v, m)).toBe('plot.measure("2024-01-01T00:00:00", "2024-01-01T00:00:09", "wait {time}", lane="db", at="bottom", level=2, nudge=-3)');
    expect(asPython(v, { ...m, text: null, lane: null, level: null, nudge: 0, at: { value: 80, layer: "cpu" } })).toBe('plot.measure("2024-01-01T00:00:00", "2024-01-01T00:00:09", at=atl.value(80, "cpu"))');
  });
});
