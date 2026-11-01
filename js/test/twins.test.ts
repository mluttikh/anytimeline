// Twins: what Python computes the browser's way for pictures it draws itself (anytimeline
// axis, image, stems), checked on the same cases on both sides. This test computes the
// browser's answers and compares them with tests/fixtures/twins.json; tests/test_twins.py
// compares Python's with the same file. After a deliberate change on both sides, write the
// file again:
//
//     UPDATE_TWINS=1 npm test
//
// and check its diff: what changed is what the browser now does.

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { AUTO_LANE, GAP_PX, LABEL_BUDGET, MIN_LANE, PAD_BOTTOM, PAD_RIGHT, ROUTE_BUDGET } from "../src/core/common";
import { dodge, MAX_ROWS, MIN_STEP, rowsFor, spacing } from "../src/core/dodge";
import { MAX_ITEMS } from "../src/core/legend";
import { fillMeasure, formatNumber } from "../src/core/fields";
import { type MeasureGeom, type MeasureLabel, placeMeasures } from "../src/core/notes";
import { BIN_FILL, BIN_PX, barsLevel, eventsLevel, MERGE_PX, valuesLevel } from "../src/core/levels";
import { SYMBOLS } from "../src/core/scene";
import { clusterHidden, levelOffset, levelsFor, placeStems, type StemItem, wrapText } from "../src/core/stems";
import { fmtNumber, formatDuration, niceStep, TimeAxis } from "../src/core/time";
import type { TimeSpec } from "../src/core/types";

const FILE = fileURLToPath(new URL("../../tests/fixtures/twins.json", import.meta.url));

const ns = (iso: string) => String(BigInt(Date.parse(iso)) * 1_000_000n);
const UNIT: Record<string, number> = { s: 1e9, ms: 1e6, us: 1e3, ns: 1 };

/** Axis cases: time kinds, units, zones (with daylight saving and half hours), spans from
 * nanoseconds to millennia, narrow and wide plots. */
function axisCases(): { spec: TimeSpec; left: number; right: number; width: number }[] {
  const out: { spec: TimeSpec; left: number; right: number; width: number }[] = [];
  const zones = ["UTC", "Europe/Amsterdam", "America/New_York", "Asia/Kolkata", "Australia/Lord_Howe"];
  const origins = ["2026-10-24T22:13:07.123456789Z", "2026-03-29T00:30:00Z", "1999-12-31T23:59:58Z"];
  const spansNs = [40, 3e3, 7.5e5, 2.2e7, 9e8, 4e10, 3.3e12, 1.9e14, 6e15, 3.1e16, 8e17, 3e19];
  for (const tz of zones)
    for (const origin of origins)
      for (const unit of ["s", "ns"])
        for (const span of spansNs) {
          if (unit === "s" && span < 1e9) continue;
          // centuries back in a zone: before 1970 tz databases differ (in some builds
          // Europe/Amsterdam is Brussels), so Python's and the browser's may disagree
          if (tz !== "UTC" && span > 1e19) continue;
          const per = UNIT[unit];
          const left = -(span / per) * 0.37;
          out.push({ spec: { kind: "datetime", unit: unit as TimeSpec["unit"], origin_ns: exactNs(origin), origin: 0, timezone: tz, extent: [0, 1] }, left, right: left + span / per, width: span > 1e15 ? 640 : 900 });
        }
  // far from 1970: centuries and BC
  for (const iso of ["0005-06-01T00:00:00Z", "1066-10-14T09:00:00Z"])
    for (const span of [3e17, 3e19, 6e20]) out.push({ spec: { kind: "datetime", unit: "s", origin_ns: ns(iso), origin: 0, timezone: "UTC", extent: [0, 1] }, left: -span / 2e9, right: span / 2e9, width: 800 });
  for (const unit of ["s", "ms", "us", "ns"])
    for (const span of [55, 4e3, 3e6, 8e9, 5e12, 2e15]) {
      const per = UNIT[unit];
      if (span / per < 1e-6) continue;
      out.push({ spec: { kind: "duration", unit: unit as TimeSpec["unit"], origin_ns: "0", origin: 0, timezone: "UTC", extent: [0, 1] }, left: -(span / per) * 0.1, right: (span / per) * 0.9, width: 700 });
    }
  for (const [lo, hi] of [[0, 1], [-3.2, 7.9], [1e-7, 3e-7], [12345.6, 12399.1], [-5e9, 9e9], [0.1, 0.3]])
    out.push({ spec: { kind: "number", unit: "", origin_ns: "0", origin: 1000, timezone: "UTC", extent: [0, 1] }, left: lo, right: hi, width: 600 });
  for (const [lo, hi] of [[-0.5, 9.5], [-0.5, 11325.5], [100.2, 160.7], [-0.5, 2.5e6]])
    out.push({ spec: { kind: "order", unit: "", origin_ns: "0", origin: 0, timezone: "UTC", extent: [0, 1] }, left: lo, right: hi, width: 800 });
  return out;
}

/** The nanoseconds of an ISO time with up to nine decimals. */
function exactNs(iso: string): string {
  const m = iso.match(/^(.*?)(?:\.(\d+))?Z$/)!;
  const whole = BigInt(Date.parse(m[1] + "Z")) * 1_000_000n;
  return String(whole + BigInt((m[2] ?? "").padEnd(9, "0") || "0"));
}

function axisAnswers() {
  return axisCases().map((c) => {
    const axis = new TimeAxis(c.spec);
    const t = axis.ticks(c.left, c.right, c.width);
    const mid = (c.left + c.right) / 2;
    return {
      ...c,
      minor: t.minor.map((m) => [m.x, m.label]),
      context: t.context.map((m) => [m.x, m.label]),
      pinned: t.pinned,
      full: [axis.formatFull(c.left), axis.formatFull(mid)],
      span: [axis.formatSpan(c.right - c.left), axis.formatSpan((c.right - c.left) / 7)],
    };
  });
}

function numberAnswers() {
  const values = [0, 1, -1, 7, 1234567, -98765432, 1e15, 3.5e15, 0.1, 0.25, 2.5, -2.5, 1 / 3, 2 / 3, 123.456789, 1e-4, 9.99e-5, 1.5e-7, 6.02e23, 1e21, 0.000123456, 99999.95, 0.5, 1.005, 4.35];
  const out = [];
  for (const v of values) for (const p of [1, 3, 6, 10]) out.push([v, p, fmtNumber(v, p)]);
  return out;
}

function durationAnswers() {
  const out = [];
  for (const v of [0, 1, 999, 1000, 1500, 2.5e6, 999999, 59e9, 60e9, 3599e9, 86399e9, 864e11, 1.23456e14, -4.2e9, 0.4])
    for (const [step, exact, sig] of [[0, false, 3], [0, false, 2], [1e3, false, 3], [1e8, false, 3], [1, true, 3], [1e6, true, 3]] as [number, boolean, number][])
      out.push([v, step, exact, sig, formatDuration(v, step, exact, sig)]);
  return out;
}

function niceAnswers() {
  const out = [];
  for (const raw of [0, -1, 1e-12, 0.0007, 0.3, 1, 1.0000001, 2, 2.1, 4.99, 5, 7, 10, 33, 870, 1e9, 3.7e12])
    for (const integer of [false, true]) out.push([raw, integer, niceStep(raw, integer)]);
  return out;
}

function levelAnswers() {
  const out = [];
  for (const top of [1e-6, 0.37, 1, 250, 3.9e4, 1.2e9])
    for (const scale of [1e-12, 1e-9, 1e-6, 1e-3, 0.02, 1, 7, 300, 1e5]) out.push([top, scale, eventsLevel(top, scale), valuesLevel(top, scale), barsLevel(top, scale)]);
  return out;
}

/** A small deterministic generator, the same in every run. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function dodgeAnswers() {
  const out = [];
  for (const [seed, n, spread, laneH, size] of [[1, 30, 200, 30, 8], [2, 200, 300, 30, 8], [3, 80, 40, 60, 10], [4, 400, 900, 120, 6], [5, 12, 10, 18, 12]]) {
    const r = rng(seed);
    const xs = Array.from({ length: n }, () => r() * spread).sort((a, b) => a - b);
    const rows = rowsFor(laneH, size, spacing(laneH, size, Infinity));
    const dy = new Float32Array(n);
    dodge(xs, 0, n, size * 0.85, rows, 1, dy);
    let pairs = 0;
    for (const d of dy) pairs = Math.max(pairs, Math.abs(d));
    out.push({ xs, laneH, size, rows, dy: Array.from(dy), step: spacing(laneH, size, pairs) });
  }
  return out;
}

function stemAnswers() {
  const out = [];
  for (const [seed, n, width, levels, shape] of [[1, 6, 600, 2, "straight"], [2, 14, 700, 2, "straight"], [3, 14, 700, 3, "curved"], [4, 30, 900, 1, "curved"], [5, 9, 300, 2, "straight"]] as [number, number, number, number, string][]) {
    const r = rng(seed);
    const items: StemItem[] = Array.from({ length: n }, (_, i) => ({ index: i, x: Math.round(r() * width * 10) / 10, w: 40 + Math.round(r() * 120), importance: r() < 0.3 ? 1 : 0 }));
    const space = { levels, gap: 7, inset: 12, left: 0, right: width, shape: shape as "straight" | "curved" };
    const placed = placeStems(items, space);
    const boxed = new Set(placed.map((p) => p.index));
    const hidden = items.filter((it) => !boxed.has(it.index)).map((it) => ({ index: it.index, x: it.x }));
    const clusters = clusterHidden(hidden, 48, items.filter((it) => boxed.has(it.index)).map((it) => it.x));
    out.push({ items, space, placed, clusters });
  }
  return out;
}

function wrapAnswers() {
  const measure = (s: string) => s.length * 6.5 + (s.match(/[mwMW]/g)?.length ?? 0) * 3;
  const texts = ["Deploy checkout 4.12", "Queue of failed payments retried after the outage was resolved", "Supercalifragilisticexpialidocious and more", "", "a b c d e f g h i j k l m n o p q r s t u v w x y z"];
  const out = [];
  for (const t of texts) for (const [w, lines] of [[120, 2], [60, 1], [200, 3], [Infinity, 2], [30, 2]]) out.push([t, w === Infinity ? null : w, lines, wrapText(t, w, lines, measure)]);
  const levels = [];
  for (const [laneH, boxH, start] of [[300, 40, 14], [80, 40, 14], [450, 54, 30], [30, 40, 12]]) levels.push([laneH, boxH, start, levelsFor(laneH, boxH, 7, start), levelOffset(2, boxH, 7, start), levelOffset(-1, boxH, 7, start)]);
  return { wrap: out, stem_levels: levels };
}

/** Measures: places, given levels, rows in sight or not, labels with and without room, in
 * lanes of several heights, at several zooms. */
function measureAnswers() {
  let seed = 7;
  const rand = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const pick = <T,>(xs: readonly T[]) => xs[Math.floor(rand() * xs.length)];
  const places = ["auto", "auto", "auto", "top", "middle", "bottom", "between", "header", "footer", "value"] as const;
  const labels: MeasureLabel[] = ["auto", "auto", "auto", "on", "above", "below", "start", "end", "hover"];
  const out = [];
  for (const laneH of [30, 64, 120])
    for (const scale of [0.4, 3, 25]) {
      const geoms: MeasureGeom[] = [];
      for (let i = 0; i < 24; i++) {
        const ua = Math.round(rand() * 100);
        const ub = ua + Math.round((rand() - 0.2) * 40);
        const at = pick(places);
        const row = rand() < 0.15 ? null : Math.floor(rand() * 4);
        geoms.push({
          xa: 120 + ua * scale,
          xb: 120 + ub * scale,
          ua,
          ub,
          rows: [row, row],
          ys: [null, null],
          row,
          at,
          valueY: at === "value" && rand() < 0.8 ? Math.round(60 + rand() * 300) : null,
          level: rand() < 0.15 ? Math.floor(rand() * 3) : null,
          nudge: rand() < 0.1 ? -3 : 0,
          text: rand() < 0.1 ? "" : "x".repeat(1 + Math.floor(rand() * 12)),
          tw: 0,
          label: pick(labels),
        });
        geoms[i].tw = geoms[i].text.length * 7 + 8;
      }
      const frame = { fs: 12, plot: { x: 120, y: 66, w: 600, h: 4 * laneH }, laneTop: 66, laneH, headTop: 44, footTop: 66 + 4 * laneH };
      const { laid, head, foot } = placeMeasures(geoms, frame);
      out.push({ geoms, frame, head, foot, laid: laid.map((d) => [d.place.split(" ")[0], d.k, d.y, d.lx, d.ly]) });
    }
  // rules: chains (one level) and baselines (a level apart) among single measures
  for (const laneH of [30, 64, 120])
    for (const at of ["auto", "top", "header"] as const) {
      const geoms: MeasureGeom[] = [];
      const add = (ua: number, ub: number, row: number | null, group: number | null, off: number, level: number | null = null) => {
        const text = "x".repeat(1 + Math.floor(rand() * 8));
        geoms.push({ xa: 120 + ua * 3, xb: 120 + ub * 3, ua, ub, rows: [row, row], ys: [null, null], row, at, valueY: null, level, nudge: 0, text, tw: text.length * 7 + 8, label: "auto", group, off });
      };
      for (let i = 0; i < 10; i++) {
        const ua = Math.round(rand() * 150);
        add(ua, ua + 5 + Math.round(rand() * 40), Math.floor(rand() * 3), null, 0, rand() < 0.1 ? 1 : null);
      }
      for (let g = 0; g < 3; g++) {
        const row = Math.floor(rand() * 3);
        let t = Math.round(rand() * 120);
        for (let k = 0; k < 3; k++) {
          const next = t + 5 + Math.round(rand() * 20);
          add(t, next, row, 100 + g, 0); // a chain: touching ends, one level
          t = next;
        }
        const origin = Math.round(rand() * 120);
        const spans = [10, 30, 20].map((d) => d + Math.round(rand() * 10));
        const rank = [...spans.keys()].sort((p, q) => spans[p] - spans[q]);
        spans.forEach((d, k) => add(origin, origin + d, row, 200 + g, rank.indexOf(k))); // a baseline
      }
      const frame = { fs: 12, plot: { x: 120, y: 66, w: 600, h: 3 * laneH }, laneTop: 66, laneH, headTop: 44, footTop: 66 + 3 * laneH };
      const { laid, head, foot } = placeMeasures(geoms, frame);
      out.push({ geoms, frame, head, foot, laid: laid.map((d) => [d.place.split(" ")[0], d.k, d.y, d.lx, d.ly]) });
    }
  // many short measures (a rule's gaps), whose labels go beside their lines where there is room
  for (const scale of [0.5, 2, 6]) {
    const geoms: MeasureGeom[] = [];
    for (let i = 0; i < 300; i++) {
      const ua = Math.round(rand() * 300);
      const ub = ua + 1 + Math.round(rand() * 6);
      const row = Math.floor(rand() * 3);
      const text = "x".repeat(1 + Math.floor(rand() * 6));
      const label = pick(labels);
      geoms.push({ xa: 120 + ua * scale, xb: 120 + ub * scale, ua, ub, rows: [row, row], ys: [null, null], row, at: rand() < 0.5 ? "top" : "middle", valueY: null, level: rand() < 0.05 ? 0 : null, nudge: 0, text, tw: text.length * 7 + 8, label });
    }
    const frame = { fs: 12, plot: { x: 120, y: 66, w: 600, h: 3 * 64 }, laneTop: 66, laneH: 64, headTop: 44, footTop: 66 + 3 * 64 };
    const { laid, head, foot } = placeMeasures(geoms, frame);
    out.push({ geoms, frame, head, foot, laid: laid.map((d) => [d.place.split(" ")[0], d.k, d.y, d.lx, d.ly]) });
  }
  return out;
}

/** A measure's text with its fields and formats, on each kind of time. */
function fieldAnswers() {
  const specs: TimeSpec[] = [
    { kind: "datetime", unit: "ns", origin_ns: "1704067200000000000", origin: 0, timezone: "UTC", extent: [0, 1] },
    { kind: "duration", unit: "ms", origin_ns: "0", origin: 0, timezone: "UTC", extent: [0, 1] },
    { kind: "number", unit: "", origin_ns: "0", origin: 10, timezone: "UTC", extent: [0, 1] },
    { kind: "order", unit: "", origin_ns: "0", origin: 0, timezone: "UTC", extent: [0, 1] },
  ];
  const texts = [
    null, "{time}", "{time:ms}", "{time:s.2}", "{time:.5}", "{time:us.1}", "{time:min}", "{time:d.4}",
    "{events} between", "{events:,}", "{change}", "{change:+.2f}", "{change:.1%}", "{change:,.3f}", "{change:.2e}", "{change: .3g}",
    "{rate}", "{rate:+.3f}", "{a} → {b}", "wait {time:ms} ({events:d})", "{nothing} {time:xx}",
  ];
  const values = [
    { span: 1530, a: 20, b: 1550, events: 3, change: -0.125 },
    { span: 86_400_000_123, a: 0, b: 86_400_000_123, events: 1234567, change: 1234.5678 },
    { span: -2.5, a: 7.5, b: 5, events: 0, change: null },
    { span: 0, a: 1, b: 1, events: null, change: 0 },
  ];
  const out = [];
  for (const spec of specs) {
    const axis = new TimeAxis(spec);
    for (const v of values) for (const text of texts) for (const order of [false, true]) out.push([spec, text, v, order, fillMeasure(axis, text, v, order)]);
  }
  const numbers = [];
  for (const v of [0, -0.004, 0.125, -1.5, 12345.678, 1e-7, 6.02e23, Number.NaN]) for (const spec of ["", "+", ",", ".2f", "+.0f", ",.2f", ".1%", ".3e", ".4g", " .1f", "-,", "q"]) numbers.push([v, spec, formatNumber(v, spec)]);
  return { fields: out, number_formats: numbers };
}

function answers() {
  return {
    constants: { PAD_RIGHT, PAD_BOTTOM, MIN_LANE, AUTO_LANE, LABEL_BUDGET, ROUTE_BUDGET, GAP_PX, BIN_PX, BIN_FILL, MERGE_PX, MAX_ROWS, MIN_STEP, LEGEND_ITEMS: MAX_ITEMS, SYMBOLS },
    axis: axisAnswers(),
    numbers: numberAnswers(),
    durations: durationAnswers(),
    nice: niceAnswers(),
    levels: levelAnswers(),
    dodge: dodgeAnswers(),
    stems: stemAnswers(),
    measures: measureAnswers(),
    ...fieldAnswers(),
    ...wrapAnswers(),
  };
}

it("the browser's answers are those of tests/fixtures/twins.json", () => {
  const got = JSON.parse(JSON.stringify(answers(), (_k, v) => (v === Infinity ? "Infinity" : v === -Infinity ? "-Infinity" : v)));
  if (process.env.UPDATE_TWINS) writeFileSync(FILE, JSON.stringify(got, null, 1) + "\n");
  const want = JSON.parse(readFileSync(FILE, "utf8"));
  expect(got).toEqual(want);
});
