// The time axis: ticks and labels from nanoseconds to centuries, in the plot's time zone.
//
// Positions are float64 ticks relative to the spec's origin (see TimeSpec). Datetimes are
// generated in BigInt nanoseconds so labels stay exact far from 1970, then turned back into
// ticks. Calendar steps (days, months, years) follow the local calendar of the time zone,
// so a day with a daylight-saving change has 23 or 25 hours.

import type { TimeSpec } from "./types";

export const UNIT_NS: Record<string, number> = { s: 1e9, ms: 1e6, us: 1e3, ns: 1, "": 1 };

export interface Tick {
  /** Position in ticks (the spec's unit, relative to its origin). */
  x: number;
  label: string;
}

export interface AxisTicks {
  /** The row of tick marks and labels. */
  minor: Tick[];
  /** Context labels (the day of hour ticks, the year of month ticks), at their boundaries. */
  context: Tick[];
  /** The context label of the unit that holds the left edge (shown pinned there). */
  pinned: string;
}

const SECOND = 1e9;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Sub-day steps in ns (fixed length in local time). */
const FIXED_STEPS = [
  1, 2, 5, 10, 20, 50, 100, 200, 500,
  1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5,
  1e6, 2e6, 5e6, 1e7, 2e7, 5e7, 1e8, 2e8, 5e8,
  SECOND, 2 * SECOND, 5 * SECOND, 10 * SECOND, 15 * SECOND, 30 * SECOND,
  MINUTE, 2 * MINUTE, 5 * MINUTE, 10 * MINUTE, 15 * MINUTE, 30 * MINUTE,
  HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR,
];

type CalendarStep = { kind: "day"; n: number } | { kind: "month"; n: number } | { kind: "year"; n: number };
const CALENDAR_STEPS: CalendarStep[] = [
  { kind: "day", n: 1 }, { kind: "day", n: 2 }, { kind: "day", n: 7 },
  { kind: "month", n: 1 }, { kind: "month", n: 3 }, { kind: "month", n: 6 },
  { kind: "year", n: 1 }, { kind: "year", n: 2 }, { kind: "year", n: 5 }, { kind: "year", n: 10 },
  { kind: "year", n: 20 }, { kind: "year", n: 50 }, { kind: "year", n: 100 }, { kind: "year", n: 200 },
  { kind: "year", n: 500 }, { kind: "year", n: 1000 },
];
const APPROX_NS: Record<CalendarStep["kind"], number> = { day: DAY, month: 30.44 * DAY, year: 365.25 * DAY };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Minimum pixels between tick labels, by the kind of label. */
const MIN_SPACING = { short: 56, medium: 72, long: 96 };

// ---------------------------------------------------------------------- time zones

interface Parts {
  y: number;
  mo: number; // 1-12
  d: number;
  h: number;
  mi: number;
  s: number;
}

const formats = new Map<string, Intl.DateTimeFormat>();

function formatter(tz: string): Intl.DateTimeFormat {
  let f = formats.get(tz);
  if (!f) {
    try {
      f = new Intl.DateTimeFormat("en-US", {
        timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric",
        hour: "numeric", minute: "numeric", second: "numeric", era: "short",
      });
    } catch {
      f = formatter("UTC");
    }
    formats.set(tz, f);
  }
  return f;
}

/** Local calendar parts of a UTC instant (milliseconds since the epoch). */
export function partsAt(ms: number, tz: string): Parts {
  if (tz === "UTC") {
    const d = new Date(ms);
    return { y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(), h: d.getUTCHours(), mi: d.getUTCMinutes(), s: d.getUTCSeconds() };
  }
  const out: Parts = { y: 1970, mo: 1, d: 1, h: 0, mi: 0, s: 0 };
  let bc = false;
  for (const p of formatter(tz).formatToParts(new Date(ms))) {
    if (p.type === "year") out.y = Number(p.value);
    else if (p.type === "month") out.mo = Number(p.value);
    else if (p.type === "day") out.d = Number(p.value);
    else if (p.type === "hour") out.h = Number(p.value) % 24;
    else if (p.type === "minute") out.mi = Number(p.value);
    else if (p.type === "second") out.s = Number(p.value);
    else if (p.type === "era") bc = p.value.startsWith("B");
  }
  if (bc) out.y = 1 - out.y;
  return out;
}

/** The zone's offset from UTC at an instant, in milliseconds. */
export function offsetMs(ms: number, tz: string): number {
  if (tz === "UTC") return 0;
  const p = partsAt(ms, tz);
  const asUtc = utcOf(p.y, p.mo, p.d, p.h, p.mi, p.s);
  return asUtc - Math.floor(ms / 1000) * 1000;
}

/** The instant of a UTC wall time; months and days past their end carry over (13/1 is
 * January of the next year). */
function utcOf(y: number, mo: number, d: number, h = 0, mi = 0, s = 0): number {
  const date = new Date(Date.UTC(2000, 0, 1, h, mi, s));
  date.setUTCFullYear(y, mo - 1, d); // years 0-99 too
  return date.getTime();
}

/** The UTC instant (ms) of a local wall time; at a gap or overlap, the later reading. */
export function localToUtc(y: number, mo: number, d: number, h: number, mi: number, s: number, tz: string): number {
  const wall = utcOf(y, mo, d, h, mi, s);
  let guess = wall - offsetMs(wall, tz);
  guess = wall - offsetMs(guess, tz);
  return guess;
}

// ---------------------------------------------------------------------- axis

export class TimeAxis {
  readonly kind: TimeSpec["kind"];
  private readonly perNs: number;
  private readonly originNs: bigint;
  private readonly origin: number;
  readonly tz: string;

  constructor(spec: TimeSpec) {
    this.kind = spec.kind;
    this.perNs = UNIT_NS[spec.unit] ?? 1;
    this.originNs = BigInt(spec.origin_ns || "0");
    this.origin = spec.origin || 0;
    this.tz = spec.timezone || "UTC";
  }

  /** Absolute ns of a tick (datetime: since the epoch; duration: since zero). */
  nsOf(x: number): bigint {
    const whole = Math.floor(x);
    const frac = x - whole;
    return this.originNs + BigInt(whole) * BigInt(this.perNs) + BigInt(Math.round(frac * this.perNs));
  }

  /** A tick of an absolute ns value. */
  tickOf(ns: bigint): number {
    return Number(ns - this.originNs) / this.perNs;
  }

  ticks(left: number, right: number, widthPx: number): AxisTicks {
    if (!(right > left) || widthPx <= 0) return { minor: [], context: [], pinned: "" };
    if (this.kind === "datetime") return this.calendarTicks(left, right, widthPx);
    if (this.kind === "duration") return this.durationTicks(left, right, widthPx);
    if (this.kind === "order") return this.numberTicks(left, right, widthPx, (v) => `#${fmtNumber(v + 1)}`, 0);
    return this.numberTicks(left, right, widthPx, (v) => fmtNumber(v), this.origin);
  }

  // -- plain numbers and ranks

  private numberTicks(left: number, right: number, widthPx: number, label: (v: number) => string, offset: number): AxisTicks {
    const step = niceStep((right - left) * (MIN_SPACING.short / widthPx), this.kind === "order");
    const minor: Tick[] = [];
    const lo = Math.ceil((left + offset) / step);
    const hi = Math.floor((right + offset) / step);
    for (let k = lo; k <= hi && minor.length < 500; k++) {
      const v = k * step;
      minor.push({ x: v - offset, label: label(roundTo(v, step)) });
    }
    return { minor, context: [], pinned: "" };
  }

  // -- durations

  private durationTicks(left: number, right: number, widthPx: number): AxisTicks {
    const pxPerNs = widthPx / ((right - left) * this.perNs);
    const steps = [...FIXED_STEPS, DAY, 2 * DAY, 5 * DAY, 10 * DAY, 30 * DAY, 100 * DAY, 365 * DAY, 3650 * DAY];
    const step = steps.find((s) => s * pxPerNs >= MIN_SPACING.medium) ?? niceStep((right - left) * this.perNs * (MIN_SPACING.medium / widthPx), false);
    const stepB = BigInt(Math.round(step));
    const lo = this.nsOf(left);
    const hi = this.nsOf(right);
    let t = floorDiv(lo, stepB) * stepB;
    if (t < lo) t += stepB;
    const minor: Tick[] = [];
    for (; t <= hi && minor.length < 500; t += stepB) minor.push({ x: this.tickOf(t), label: formatDuration(Number(t), step) });
    return { minor, context: [], pinned: "" };
  }

  // -- datetimes

  private calendarTicks(left: number, right: number, widthPx: number): AxisTicks {
    const nsPerPx = ((right - left) * this.perNs) / widthPx;
    const lo = this.nsOf(left);
    const hi = this.nsOf(right);
    const fixed = FIXED_STEPS.find((s) => s / nsPerPx >= spacingFor(s));
    if (fixed !== undefined) {
      const minor = this.fixedTicks(lo, hi, fixed).map((t) => ({ x: this.tickOf(t), label: this.fixedLabel(t, fixed) }));
      const contextStep: CalendarStep | number = fixed < SECOND ? SECOND : { kind: "day", n: 1 };
      const boundaries = typeof contextStep === "number" ? this.fixedTicks(lo, hi, contextStep) : this.calendarSteps(lo, hi, contextStep);
      const contextLabel = (t: bigint) => (fixed < SECOND ? this.secondContext(t) : this.dayContext(t));
      return {
        minor,
        context: boundaries.map((t) => ({ x: this.tickOf(t), label: contextLabel(t) })),
        pinned: contextLabel(lo),
      };
    }
    const cal = CALENDAR_STEPS.find((c) => (APPROX_NS[c.kind] * c.n) / nsPerPx >= MIN_SPACING.short) ?? CALENDAR_STEPS[CALENDAR_STEPS.length - 1];
    const minor = this.calendarSteps(lo, hi, cal).map((t) => ({ x: this.tickOf(t), label: this.calendarLabel(t, cal) }));
    let context: Tick[] = [];
    let pinned = "";
    if (cal.kind === "day") {
      context = this.calendarSteps(lo, hi, { kind: "month", n: 1 }).map((t) => ({ x: this.tickOf(t), label: this.monthContext(t) }));
      pinned = this.monthContext(lo);
    } else if (cal.kind === "month") {
      context = this.calendarSteps(lo, hi, { kind: "year", n: 1 }).map((t) => ({ x: this.tickOf(t), label: String(this.parts(t).y) }));
      pinned = String(this.parts(lo).y);
    }
    return { minor, context, pinned };
  }

  private parts(ns: bigint): Parts {
    return partsAt(Number(floorDiv(ns, 1_000_000n)), this.tz);
  }

  /** Fixed steps aligned in local time, as absolute ns. */
  private fixedTicks(lo: bigint, hi: bigint, step: number): bigint[] {
    const stepB = BigInt(Math.round(step));
    const offset = BigInt(offsetMs(Number(floorDiv(lo, 1_000_000n)), this.tz)) * 1_000_000n;
    let local = floorDiv(lo + offset, stepB) * stepB;
    const out: bigint[] = [];
    for (let guard = 0; guard < 1000; guard++, local += stepB) {
      let t = local - offset;
      if (step >= HOUR) {
        // keep hour ticks on the local clock across a daylight-saving change
        const off = BigInt(offsetMs(Number(floorDiv(t, 1_000_000n)), this.tz)) * 1_000_000n;
        t = local - off;
      }
      if (t > hi) break;
      if (t >= lo) out.push(t);
    }
    return out;
  }

  /** Calendar steps (local midnights, month and year starts) in [lo, hi], as absolute ns. */
  private calendarSteps(lo: bigint, hi: bigint, step: CalendarStep): bigint[] {
    const p = this.parts(lo);
    const out: bigint[] = [];
    let y = p.y;
    let mo = p.mo;
    let d = p.d;
    if (step.kind === "year") {
      y = Math.floor(y / step.n) * step.n;
      mo = 1;
      d = 1;
    } else if (step.kind === "month") {
      mo = Math.floor((mo - 1) / step.n) * step.n + 1;
      d = 1;
    } else if (step.n === 7) {
      // weeks start on Monday
      const weekday = new Date(utcOf(y, mo, d)).getUTCDay();
      d -= (weekday + 6) % 7;
    } else if (step.n > 1) {
      const dayNumber = Math.floor(utcOf(y, mo, d) / 86_400_000);
      d -= ((dayNumber % step.n) + step.n) % step.n;
    }
    for (let guard = 0; guard < 2000; guard++) {
      const wall = new Date(utcOf(y, mo, d));
      const ms = localToUtc(wall.getUTCFullYear(), wall.getUTCMonth() + 1, wall.getUTCDate(), 0, 0, 0, this.tz);
      const t = BigInt(ms) * 1_000_000n;
      if (t > hi) break;
      if (t >= lo) out.push(t);
      if (step.kind === "year") y += step.n;
      else if (step.kind === "month") mo += step.n;
      else d += step.n;
    }
    return out;
  }

  private fixedLabel(t: bigint, step: number): string {
    if (step < SECOND) return fractionLabel(t, step);
    const p = this.parts(t);
    if (step < MINUTE) return `${pad(p.h)}:${pad(p.mi)}:${pad(p.s)}`;
    return `${pad(p.h)}:${pad(p.mi)}`;
  }

  private calendarLabel(t: bigint, step: CalendarStep): string {
    const p = this.parts(t);
    if (step.kind === "year") return yearLabel(p.y);
    if (step.kind === "month") return p.mo === 1 && step.n < 12 ? yearLabel(p.y) : MONTHS[p.mo - 1];
    return step.n >= 7 ? `${MONTHS[p.mo - 1]} ${p.d}` : String(p.d);
  }

  private secondContext(t: bigint): string {
    const p = this.parts(t);
    return `${MONTHS[p.mo - 1]} ${p.d}, ${yearLabel(p.y)} ${pad(p.h)}:${pad(p.mi)}:${pad(p.s)}`;
  }

  private dayContext(t: bigint): string {
    const p = this.parts(t);
    const weekday = WEEKDAYS[new Date(utcOf(p.y, p.mo, p.d)).getUTCDay()];
    return `${weekday} ${MONTHS[p.mo - 1]} ${p.d}, ${yearLabel(p.y)}`;
  }

  private monthContext(t: bigint): string {
    const p = this.parts(t);
    return `${MONTHS_LONG[p.mo - 1]} ${yearLabel(p.y)}`;
  }

  /** A time with all the precision of the data's unit (tooltips). */
  formatFull(x: number): string {
    if (this.kind === "order") return `#${fmtNumber(Math.round(x) + 1)}`;
    if (this.kind === "number") return fmtNumber(this.origin + x, 10);
    const ns = this.nsOf(x);
    const digits = { s: 0, ms: 3, us: 6, ns: 9, "": 9 }[unitOf(this.perNs)] ?? 9;
    if (this.kind === "duration") return formatDuration(Number(ns), Math.max(1, 10 ** (9 - digits)), true);
    const p = this.parts(ns);
    const sub = ((ns % 1_000_000_000n) + 1_000_000_000n) % 1_000_000_000n;
    // a time exactly at midnight is a date (data by day)
    if (p.h === 0 && p.mi === 0 && p.s === 0 && sub === 0n) return `${yearLabel(p.y)}-${pad(p.mo)}-${pad(p.d)}`;
    const frac = digits ? "." + groupDigits(String(Number(((ns % 1_000_000_000n) + 1_000_000_000n) % 1_000_000_000n)).padStart(9, "0").slice(0, digits)) : "";
    const zone = this.tz === "UTC" ? "UTC" : this.tz;
    return `${yearLabel(p.y)}-${pad(p.mo)}-${pad(p.d)} ${pad(p.h)}:${pad(p.mi)}:${pad(p.s)}${frac} ${zone}`;
  }

  /** A span of ticks as a duration ("2.5 s", "3 min"); for numbers and ranks as a number. */
  formatSpan(dx: number): string {
    if (this.kind === "order") return `${fmtNumber(dx)} events`;
    if (this.kind === "number") return fmtNumber(dx, 3);
    return formatDuration(dx * this.perNs, 0, false, 2);
  }

  /** A measured span of ticks, to three significant digits (a measure's label). */
  formatMeasure(dx: number): string {
    if (this.kind === "order") return `${fmtNumber(dx)} events`;
    if (this.kind === "number") return fmtNumber(dx, 3);
    return formatDuration(dx * this.perNs, 0, false, 3);
  }

  /** A measured span of ticks with all the precision of the data's unit (its tooltip). */
  formatMeasureExact(dx: number): string {
    if (this.kind === "order") return `${fmtNumber(dx)} events`;
    if (this.kind === "number") return fmtNumber(dx, 10);
    return formatDuration(dx * this.perNs, 0, true);
  }
}

function spacingFor(stepNs: number): number {
  if (stepNs < 1e6) return MIN_SPACING.long; // ".250 300" and finer
  if (stepNs < SECOND) return MIN_SPACING.medium;
  return MIN_SPACING.medium;
}

function unitOf(perNs: number): string {
  return perNs >= 1e9 ? "s" : perNs >= 1e6 ? "ms" : perNs >= 1e3 ? "us" : "ns";
}

/** The fraction of a second of an instant, with as many digits as the step needs: ".25",
 * ".250 300". */
function fractionLabel(t: bigint, step: number): string {
  const digits = Math.min(9, Math.max(1, Math.ceil(-Math.log10(step / SECOND) - 1e-9)));
  const grouped = Math.min(9, Math.ceil(digits / 3) * 3);
  const sub = Number(((t % 1_000_000_000n) + 1_000_000_000n) % 1_000_000_000n);
  return "." + groupDigits(String(sub).padStart(9, "0").slice(0, grouped));
}

function groupDigits(s: string): string {
  return s.replace(/(\d{3})(?=\d)/g, "$1 ");
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function yearLabel(y: number): string {
  return y <= 0 ? `${1 - y} BC` : String(y);
}

function floorDiv(a: bigint, b: bigint): bigint {
  const q = a / b;
  return q * b > a ? q - 1n : q;
}

/** A 1-2-5 step at least `raw` (integers only when `integer`). */
export function niceStep(raw: number, integer: boolean): number {
  if (!(raw > 0) || !Number.isFinite(raw)) return 1;
  const exp = Math.floor(Math.log10(raw));
  const base = 10 ** exp;
  const m = raw / base;
  const step = (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * base;
  return integer ? Math.max(1, Math.round(step)) : step;
}

function roundTo(v: number, step: number): number {
  const decimals = Math.max(0, -Math.floor(Math.log10(step)));
  return Number(v.toFixed(Math.min(15, decimals)));
}

export function fmtNumber(v: number, precision = 6): string {
  if (!Number.isFinite(v)) return "–";
  if (Number.isInteger(v) && Math.abs(v) < 1e15) return v.toLocaleString("en-US").replace(/,/g, " ");
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-4 || a >= 1e15)) return v.toExponential(Math.max(0, precision - 1)).replace(/\.?0+e/, "e");
  return String(Number(v.toPrecision(precision)));
}

const DURATION_UNITS: [number, string][] = [
  [DAY, "d"], [HOUR, "h"], [MINUTE, "min"], [SECOND, "s"], [1e6, "ms"], [1e3, "µs"], [1, "ns"],
];

/**
 * A duration in ns as text. With `stepNs` > 0, enough decimals to tell steps apart; with
 * `exact`, the full value; else `sig` significant digits.
 */
export function formatDuration(ns: number, stepNs: number, exact = false, sig = 3): string {
  const sign = ns < 0 ? "−" : "";
  const a = Math.abs(ns);
  if (a === 0) return "0";
  const [per, name] = DURATION_UNITS.find(([u]) => a >= u) ?? DURATION_UNITS[DURATION_UNITS.length - 1];
  const value = a / per;
  let text: string;
  if (exact) text = String(Number(value.toPrecision(15)));
  else if (stepNs > 0) {
    const decimals = Math.max(0, Math.min(9, Math.ceil(-Math.log10(stepNs / per) - 1e-9)));
    text = value.toFixed(decimals);
  } else text = String(Number(value.toPrecision(sig)));
  return `${sign}${text} ${name}`;
}
