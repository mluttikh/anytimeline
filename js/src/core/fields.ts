// A measure's text: its fields filled in (Python's measuring.py is the twin). `{time}` is the
// time between, `{events}` the events between in the order, `{change}` the change in value
// between two samples, `{rate}` that change per unit of time, `{a}` and `{b}` the ends'
// times; `{a.col}` and `{b.col}` (a column of an end's row) Python fills in before. A field
// takes a format after a colon: `{time:ms}` a unit, `{time:.2}` the digits, `{time:ms.4}`
// both; `{change:+.2f}` (and events and rate) a sign, `,` for thousands, digits, and `f`,
// `e`, `%` or `g` as in Python.

import { fmtNumber, formatDuration, type TimeAxis } from "./time";

export const FIELD = /\{(time|events|change|rate|a|b)(?::([^{}]*))?\}/g;
const TIME_SPEC = /^(ns|us|µs|ms|s|min|h|d)?(?:\.(\d{1,2}))?$/;
const NUMBER_SPEC = /^([+ -]?)(,?)(?:\.(\d{1,2}))?([fe%g]?)$/;
const UNITS: Record<string, [number, string]> = {
  ns: [1, "ns"], us: [1e3, "µs"], µs: [1e3, "µs"], ms: [1e6, "ms"], s: [1e9, "s"], min: [60e9, "min"], h: [3600e9, "h"], d: [86400e9, "d"],
};

/** What a measure's text is filled from. */
export interface MeasureValues {
  /** b − a, ticks. */
  span: number;
  /** Ticks of its ends. */
  a: number;
  b: number;
  events: number | null;
  change: number | null;
}

function group(int: string): string {
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** A number with a format as Python's (`+.2f`, `,`, `.1%`, `.3e`, `.4g`): the sign `−`. */
export function formatNumber(v: number, spec: string): string {
  const m = NUMBER_SPEC.exec(spec);
  if (!m || !Number.isFinite(v)) return fmtNumber(v);
  const [, sign, comma, digits, type] = m;
  const p = digits === undefined ? null : Number(digits);
  const a = Math.abs(v);
  let body: string;
  if (type === "f" || type === "%") body = (type === "%" ? a * 100 : a).toFixed(p ?? 6);
  else if (type === "e") body = a.toExponential(p ?? 6).replace(/e([+-])(\d)$/, "e$10$2");
  else body = fmtNumber(a, p ?? 6).replace(/ /g, comma ? "," : " ");
  if (comma && type !== "e" && type !== "g" && type !== "") {
    const [int, frac] = body.split(".");
    body = group(int) + (frac !== undefined ? `.${frac}` : "");
  }
  if (type === "%") body += "%";
  const negative = v < 0 && Number(body.replace(/[,%\u2009]/g, "")) !== 0;
  return (negative ? "−" : sign === "+" ? "+" : sign === " " ? " " : "") + body;
}

/** A time between ends (ticks, ≥ 0) with a format: a unit, digits (3 by default). */
export function formatTime(axis: TimeAxis, dx: number, spec: string): string {
  const m = TIME_SPEC.exec(spec);
  if (!spec || !m) return axis.formatMeasure(dx);
  const [, unit, digits] = m;
  const sig = digits === undefined ? 3 : Math.max(1, Number(digits));
  if (axis.kind === "order") return `${fmtNumber(dx, sig)} events`;
  if (axis.kind === "number") return fmtNumber(dx, sig);
  const ns = dx * axis.perNs;
  if (!unit) return formatDuration(ns, 0, false, sig);
  const [per, name] = UNITS[unit];
  return `${String(Number((ns / per).toPrecision(sig)))} ${name}`;
}

/** The events between, as the label writes them ("3 events"); with a format, the number. */
function eventsText(events: number | null, spec: string | undefined): string {
  if (events === null) return "";
  if (spec) return formatNumber(events, spec);
  return `${fmtNumber(events)} event${events === 1 ? "" : "s"}`;
}

/** A change in value, signed, to three digits; with a format, as it says. */
export function changeText(change: number, spec = ""): string {
  if (spec) return formatNumber(change, spec);
  return (change > 0 ? "+" : change < 0 ? "−" : "") + fmtNumber(Math.abs(change), 3);
}

/** A measure's text with its fields filled in; without text, the time (on the Order scale
 * with the events between, between samples with the change). */
export function fillMeasure(axis: TimeAxis | null, text: string | null, v: MeasureValues, order: boolean): string {
  const time = axis ? axis.formatMeasure(Math.abs(v.span)) : String(Math.abs(v.span));
  if (text === null) {
    const parts = [time, order ? eventsText(v.events, undefined) : "", v.change !== null ? `Δ ${changeText(v.change)}` : ""];
    return parts.filter((p) => p).join(" · ");
  }
  return text.replace(FIELD, (_all, name: string, spec: string | undefined) => {
    const s = spec ?? "";
    switch (name) {
      case "time":
        return axis ? formatTime(axis, Math.abs(v.span), s) : String(Math.abs(v.span));
      case "events":
        return eventsText(v.events, spec);
      case "change":
        return v.change === null ? "" : changeText(v.change, s);
      case "rate": {
        if (v.change === null || !axis) return "";
        const rate = axis.rate(v.change, v.span);
        if (!rate) return "";
        return s ? `${formatNumber(rate[0], s)} per ${rate[1]}` : axis.formatRate(v.change, v.span) ?? "";
      }
      default:
        return axis ? axis.formatFull(name === "a" ? v.a : v.b) : String(name === "a" ? v.a : v.b);
    }
  });
}
