import { describe, expect, it } from "vitest";
import { TimeCamera } from "../src/core/camera";
import { dodge, MIN_STEP, rowOffset, rowsFor, spacing } from "../src/core/dodge";
import { lowerBound, upperBound } from "../src/core/scene";
import { TimeAxis, formatDuration, localToUtc, niceStep, offsetMs } from "../src/core/time";
import type { TimeSpec } from "../src/core/types";
import { findGaps } from "../src/core/view";
import { compatible, convert, type LinkFrame } from "../src/core/link";
import { clusterHidden, levelOffset, levelOrder, levelsFor, placeStems, type StemPlaced, wrapText } from "../src/core/stems";

const NS = 1_000_000_000n;

function datetimeAxis(isoUtc: string, unit: TimeSpec["unit"], timezone = "UTC"): TimeAxis {
  const originNs = BigInt(Date.parse(isoUtc)) * 1_000_000n;
  return new TimeAxis({ kind: "datetime", unit, origin_ns: String(originNs), origin: 0, timezone, extent: [0, 1] });
}

describe("time axis", () => {
  it("labels an hour of minutes with the day as context", () => {
    const axis = datetimeAxis("2026-10-12T08:00:00Z", "s");
    const t = axis.ticks(0, 3600, 800);
    expect(t.minor[0].label).toBe("08:00");
    expect(t.minor.map((m) => m.label)).toContain("08:30");
    expect(t.pinned).toBe("Mon Oct 12, 2026");
  });

  it("labels sub-second ticks as fractions with the second as context", () => {
    const axis = datetimeAxis("2026-10-12T08:00:00Z", "ns");
    const t = axis.ticks(1e9, 1e9 + 2_000_000, 800); // 2 ms after 08:00:01
    expect(t.minor.length).toBeGreaterThan(3);
    expect(t.minor[0].label).toMatch(/^\.000/);
    expect(t.pinned).toBe("Oct 12, 2026 08:00:01");
  });

  it("reaches single nanoseconds", () => {
    const axis = datetimeAxis("2026-10-12T00:00:00Z", "ns");
    const t = axis.ticks(100, 120, 800);
    const labels = t.minor.map((m) => m.label);
    expect(labels).toContain(".000 000 110");
  });

  it("ticks centuries as years, before 1677 too", () => {
    // 1066 in seconds: below what nanoseconds reach
    const originNs = BigInt(Date.UTC(1066, 9, 14)) * 1_000_000n;
    const axis = new TimeAxis({ kind: "datetime", unit: "s", origin_ns: String(originNs), origin: 0, timezone: "UTC", extent: [0, 1] });
    const span = 950 * 365.25 * 86400;
    const t = axis.ticks(0, span, 800);
    expect(t.minor.map((m) => m.label)).toEqual(expect.arrayContaining(["1100", "1500", "1900"]));
  });

  it("keeps hour ticks on the local clock across a daylight-saving change", () => {
    // Europe/Amsterdam: 2026-03-29 02:00 local jumps to 03:00 (UTC+1 → UTC+2)
    const axis = datetimeAxis("2026-03-28T22:00:00Z", "s", "Europe/Amsterdam");
    const t = axis.ticks(0, 8 * 3600, 900);
    const labels = t.minor.map((m) => m.label);
    expect(labels).not.toContain("02:00");
    expect(labels).toContain("03:00");
    expect(labels).toContain("04:00");
    // 23-hour day: midnight to midnight around the change
    const day0 = localToUtc(2026, 3, 29, 0, 0, 0, "Europe/Amsterdam");
    const day1 = localToUtc(2026, 3, 30, 0, 0, 0, "Europe/Amsterdam");
    expect((day1 - day0) / 3_600_000).toBe(23);
    expect(offsetMs(Date.UTC(2026, 6, 1), "Europe/Amsterdam")).toBe(2 * 3_600_000);
  });

  it("formats full precision for tooltips in the data's unit", () => {
    const axis = datetimeAxis("2026-10-12T08:00:00Z", "us");
    expect(axis.formatFull(1_500_250)).toBe("2026-10-12 08:00:01.500 250 UTC");
    const days = datetimeAxis("2026-10-12T00:00:00Z", "s");
    expect(days.formatFull(86_400)).toBe("2026-10-13"); // midnight: the date alone
    expect(days.formatFull(86_401)).toBe("2026-10-13 00:00:01 UTC");
    expect(axis.nsOf(1).toString()).toBe((BigInt(Date.parse("2026-10-12T08:00:00Z")) * 1_000_000n + 1000n).toString());
    expect(axis.nsOf(1) % NS).toBe(1000n);
  });

  it("formats durations", () => {
    expect(formatDuration(1_500_000, 0)).toBe("1.5 ms");
    expect(formatDuration(90e9, 0)).toBe("1.5 min");
    expect(formatDuration(5000, 1000)).toBe("5 µs");
    const axis = new TimeAxis({ kind: "duration", unit: "ns", origin_ns: "0", origin: 0, timezone: "UTC", extent: [0, 1] });
    const labels = axis.ticks(0, 50_000, 800).minor.map((m) => m.label);
    expect(labels).toContain("10 µs");
  });

  it("numbers and ranks", () => {
    expect(niceStep(0.13, false)).toBeCloseTo(0.2);
    expect(niceStep(0.3, true)).toBe(1);
    const order = new TimeAxis({ kind: "order", unit: "", origin_ns: "0", origin: 0, timezone: "UTC", extent: [0, 9] });
    expect(order.ticks(-0.5, 9.5, 800).minor[0].label).toBe("#1");
    const nums = new TimeAxis({ kind: "number", unit: "", origin_ns: "0", origin: 100, timezone: "UTC", extent: [0, 1] });
    expect(nums.ticks(0, 1, 800).minor[0].label).toBe("100");
  });
});

describe("camera", () => {
  it("zooms around a point and keeps it in place", () => {
    const c = new TimeCamera();
    c.width = 1000;
    c.setLimits([0, 1000], 1e-6);
    c.fit(0, 1000, 0);
    const before = c.fromPx(250);
    c.zoomAt(250, 4);
    expect(c.fromPx(250)).toBeCloseTo(before, 9);
    expect(c.span).toBeCloseTo(250, 6);
  });

  it("stops at the smallest span per pixel", () => {
    const c = new TimeCamera();
    c.width = 1000;
    c.setLimits([0, 1e9], 0.05);
    c.fit(0, 1e9, 0);
    for (let i = 0; i < 100; i++) c.zoomAt(500, 10);
    expect(c.span).toBeCloseTo(50, 6);
  });
});

describe("dodge", () => {
  it("spreads ties over sub-rows: centre, above, below", () => {
    expect([0, 1, 2, 3, 4].map(rowOffset)).toEqual([0, -1, 1, -2, 2]);
    const xs = new Float64Array([10, 10, 10, 30, 30.5]);
    const out = new Float32Array(5);
    dodge(xs, 0, 5, 8, 3, 5, out);
    expect(Array.from(out)).toEqual([0, -5, 5, 0, -5]);
  });

  it("overlays on the longest-free row when all are taken", () => {
    const xs = new Float64Array([0, 0, 0, 0]);
    const out = new Float32Array(4);
    dodge(xs, 0, 4, 8, 3, 5, out);
    expect(Array.from(out)).toEqual([0, -5, 5, 0]);
  });

  it("fits the rows to the lane", () => {
    expect(rowsFor(30, 8, 5)).toBe(5); // offsets up to ±10 px: marks stay in the lane
    expect(rowsFor(12, 8, 5)).toBe(1);
    expect(rowsFor(400, 8, 5)).toBe(79); // a full-screen lane: many sub-rows
    expect(rowsFor(2000, 8, 5)).toBe(101); // at most MAX_ROWS
  });
});

describe("helpers", () => {
  it("binary searches", () => {
    const a = [1, 2, 2, 2, 5];
    expect(lowerBound(a, 2)).toBe(1);
    expect(upperBound(a, 2)).toBe(4);
    expect(lowerBound(a, 2, 2, 4)).toBe(2);
  });

  it("finds long gaps in the order of events", () => {
    const t = new Float64Array([0, 1, 2, 3, 4, 1000, 1001, 1002]);
    const gaps = findGaps(t);
    expect(gaps).toEqual([{ at: 4.5, span: 996 }]);
  });
});

describe("linked plots: times between time bases", () => {
  const base = (origin: string, unit: "s" | "ms" | "us" | "ns", start = 0): LinkFrame => ({ kind: "datetime", originNs: BigInt(origin), origin: 0, unitNs: { s: 1e9, ms: 1e6, us: 1e3, ns: 1 }[unit], start });

  it("aligns absolute times across origins and units", () => {
    const a = base("1791792000000000000", "us"); // 2026-10-12 08:00 UTC
    const b = base("1791795600000000000", "ms"); // an hour later, in ms
    // 90 minutes after a's origin is 30 minutes after b's
    expect(convert(90 * 60e6, a, b, "time")).toBeCloseTo(30 * 60e3, 6);
    expect(convert(30 * 60e3, b, a, "time")).toBeCloseTo(90 * 60e6, 6);
  });

  it("aligns plots from their own start with align 'start'", () => {
    const monday = base("1791792000000000000", "ms", 5_000);
    const tuesday = base("1791878400000000000", "us", 2_000_000);
    // 10 s after Monday's first time is 10 s after Tuesday's
    expect(convert(15_000, monday, tuesday, "start")).toBeCloseTo(12_000_000, 6);
  });

  it("links only comparable kinds", () => {
    const t = base("0", "ms");
    const n: LinkFrame = { kind: "number", originNs: 0n, origin: 10, unitNs: 1, start: 0 };
    expect(compatible(t, n, "time")).toBe(false);
    expect(compatible(t, { ...t, kind: "duration" }, "time")).toBe(false);
    expect(compatible(t, { ...t, kind: "duration" }, "start")).toBe(true);
    expect(convert(5, n, { ...n, origin: 12 }, "time")).toBe(3);
  });
});

describe("dodging: the spacing of sub-rows", () => {
  it("is a mark and a pixel apart when there is room (marks do not overlap)", () => {
    expect(spacing(184, 8, 6)).toBe(9);
    expect(spacing(184, 8, 0)).toBe(9);
  });
  it("closes up to fit the rows the events need, down to MIN_STEP of a mark", () => {
    expect(spacing(184, 8, 12)).toBeCloseTo((92 - 4 - 18.4) / 12, 6); // 5.8 px: fills the lane
    expect(spacing(30, 8, 2)).toBe(8 * MIN_STEP); // a normal lane: as before
    expect(spacing(30, 8, 40)).toBe(8 * MIN_STEP);
    expect(spacing(30, 2, 1)).toBe(3); // a tiny mark: at least 2.5 px, at most a mark + 1
  });
});

describe("story timelines: stem labels", () => {
  const space = { levels: 3, gap: 6, inset: 8, left: 0, right: 1000, shape: "straight" as const };
  /** Boxes of a level that overlap, and stems that pass behind a box nearer the line. */
  const problems = (placed: StemPlaced[]) => {
    let overlaps = 0;
    let behind = 0;
    for (const a of placed) {
      for (const b of placed) {
        if (a === b) continue;
        if (a.level === b.level && a.x0 < b.x0 + b.w && b.x0 < a.x0 + a.w) overlaps++;
        const sameSide = Math.sign(a.level) === Math.sign(b.level);
        if (sameSide && Math.abs(b.level) < Math.abs(a.level) && a.cx > b.x0 && a.cx < b.x0 + b.w) behind++;
      }
    }
    return { overlaps, behind };
  };
  const random = (n: number, seed: number) => {
    let s = seed;
    const rnd = () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
    return Array.from({ length: n }, (_, index) => ({ index, x: rnd() * 1000, w: 60 + rnd() * 120, importance: Math.floor(rnd() * 3) }));
  };

  it("alternates levels above and below", () => {
    expect(levelOrder(2)).toEqual([1, -1, 2, -2]);
    const placed = placeStems([0, 20, 40, 60].map((x, index) => ({ index, x: 100 + x, w: 100, importance: 0 })), space);
    expect(placed.map((p) => p.level).slice(0, 2)).toEqual([1, -1]);
  });

  it("never overlaps boxes, and no stem passes behind a box (straight and curved)", () => {
    for (const shape of ["straight", "curved"] as const) {
      for (const seed of [1, 2, 3, 4, 5]) {
        const placed = placeStems(random(40, seed), { ...space, shape });
        expect(problems(placed)).toEqual({ overlaps: 0, behind: 0 });
        for (const p of placed) {
          if (shape === "straight") expect(p.cx).toBe(p.x); // the box is over its event
          expect(p.cx).toBeGreaterThanOrEqual(p.x0);
          expect(p.cx).toBeLessThanOrEqual(p.x0 + p.w);
        }
      }
    }
  });

  it("curved stems fit more boxes where events crowd", () => {
    const crowd = random(40, 7).map((it) => ({ ...it, x: 400 + it.x / 5 }));
    const straight = placeStems(crowd, space).length;
    const curved = placeStems(crowd, { ...space, shape: "curved" }).length;
    expect(curved).toBeGreaterThan(straight);
  });

  it("places the important first", () => {
    const crowded = [0, 10, 20].map((x, index) => ({ index, x: 300 + x, w: 80, importance: index === 2 ? 3 : 1 }));
    const placed = placeStems(crowded, { ...space, levels: 1 });
    expect(placed.find((p) => p.index === 2)?.level).toBe(1);
  });

  it("an event at the edge keeps its box, within a stem's margin of the bounds", () => {
    const [first] = placeStems([{ index: 0, x: 0, w: 120, importance: 0 }], space);
    expect(first.x0).toBeGreaterThanOrEqual(-7);
    expect(first.cx).toBe(0);
    const [last] = placeStems([{ index: 0, x: 1000, w: 120, importance: 0 }], space);
    expect(last.x0 + last.w).toBeLessThanOrEqual(1007);
  });

  it("fits as many levels as the lane holds", () => {
    expect(levelsFor(460, 38, 6, 14)).toBe(4); // (230 − 3 − 14 + 6) / 44
    expect(levelsFor(40, 38, 6, 14)).toBe(0);
    expect(levelOffset(1, 38, 6, 14)).toBe(-33);
    expect(levelOffset(-2, 38, 6, 14)).toBe(77);
  });
});

describe("story timelines: wrapping and badges", () => {
  const measure = (t: string) => t.length * 7; // 7 px a character

  it("keeps a title that fits on one line", () => {
    expect(wrapText("Rollback started", 200, 2, measure)).toEqual(["Rollback started"]);
    expect(wrapText("Rollback started", Infinity, 2, measure)).toEqual(["Rollback started"]);
  });

  it("wraps at spaces onto at most two lines, the rest cut with an ellipsis", () => {
    const lines = wrapText("Queue of failed payments retried after the fix was deployed", 140, 2, measure);
    expect(lines).toHaveLength(2);
    expect(lines[0]).toBe("Queue of failed");
    expect(lines[1].endsWith("…")).toBe(true);
    for (const l of lines) expect(measure(l)).toBeLessThanOrEqual(140);
    expect(wrapText("Supercalifragilistic", 70, 2, measure)[0].endsWith("…")).toBe(true);
  });

  it("groups events without a box, never across one with a box", () => {
    const hidden = [10, 20, 30, 200, 400].map((x, index) => ({ index, x }));
    expect(clusterHidden(hidden, 48).map((c) => c.indices)).toEqual([[0, 1, 2], [3], [4]]);
    expect(clusterHidden(hidden, 48, [25]).map((c) => c.indices)).toEqual([[0, 1], [2], [3], [4]]);
  });

  it("places badges after every event, and they do not push events out", () => {
    const space = { levels: 2, gap: 6, inset: 8, left: 0, right: 1000, shape: "straight" as const };
    const events = [100, 400, 700].map((x, index) => ({ index, x, w: 120, importance: 0 }));
    const without = placeStems(events, space);
    const withBadge = placeStems([...events, { index: -1, x: 110, w: 30, importance: -Infinity, badge: true }], space);
    expect(withBadge.filter((p) => p.index >= 0)).toEqual(without);
  });
});
