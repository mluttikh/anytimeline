// Annotations and connections (Timeline.annotate, Timeline.connect): notes on a time range or
// a time, over a lane or all, and arrows from one mark to another, as Python sends them
// (ticks, lane indices). The key `a` and then a drag (or a click) makes a note; the key `c`
// on one mark and then on another makes an arrow. Both go to Python, which keeps them.

import { globalIndex, type Hit } from "./common";
import type { TimelineView } from "./view";

export interface NoteBand {
  x0: number;
  x1: number;
  /** A note at one time (a line), not over a range. */
  point: boolean;
  /** The lane it is in; null: across all lanes. */
  lane: number | null;
  text: string;
  color: string | null;
}

/** A mark an arrow starts or ends at: where it is on both scales, and its lane. */
export interface NoteEnd {
  layer: string;
  index: number;
  x: number;
  x2: number;
  r: number;
  r2: number;
  lane: number;
}

export interface NoteArrow {
  a: NoteEnd;
  b: NoteEnd;
  text: string;
  color: string | null;
}

export interface Notes {
  bands?: NoteBand[];
  arrows?: NoteArrow[];
}

/** An annotation made in the plot, for Python (ticks; x1 null: at one time). */
export interface NewNote {
  x0: number;
  x1: number | null;
  lane: number | null;
  text: string;
}

/** A mark, as Python knows it: its layer's name and its index among the layer's. */
export interface MarkRef {
  layer: string;
  index: number;
}

type Rect = { x: number; y: number; w: number; h: number };

/** The mark of a hit, as Python knows it (null: a bin, or merged bars). */
export function markOf(view: TimelineView, h: Hit | null): MarkRef | null {
  if (!h || h.bin || h.val) return null;
  if (h.bar) {
    const b = view.bars[h.layer];
    const index = b?.globalIndex(h.index) ?? -1;
    return index >= 0 ? { layer: b.data.spec.name, index } : null;
  }
  const l = view.layers[h.layer];
  return l ? { layer: l.data.spec.name, index: globalIndex(l, h.index) } : null;
}

/** A time (ticks) on the scale shown: itself, or its place in the order. */
function place(view: TimelineView, t: number): number | null {
  if (view.xscale !== "order") return t;
  return view.seq?.count ? view.seq.lower(t) - 0.5 : null;
}

function label(view: TimelineView, ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string, plot: Rect): void {
  const w = ctx.measureText(text).width + 8;
  const lx = Math.max(plot.x + 1, Math.min(x, plot.x + plot.w - w - 1));
  ctx.globalAlpha = 0.9;
  ctx.fillStyle = view.theme.bg;
  ctx.fillRect(lx, y, w, view.fs + 4);
  ctx.globalAlpha = 1;
  ctx.fillStyle = color;
  ctx.fillText(text, lx + 4, y + view.fs);
}

/** The notes: translucent bands with their text at the top (a line for a note at one time),
 * and arrows with their text at the middle. */
export function drawNotes(view: TimelineView, ctx: CanvasRenderingContext2D, plot: Rect, laneTop: number): void {
  const notes = view.notes;
  if (!notes.bands?.length && !notes.arrows?.length) return;
  const c = view.camera;
  const px = (v: number) => plot.x + (v - c.left) * c.scale;
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  ctx.font = view.font(-1);
  ctx.textBaseline = "alphabetic";
  for (const n of notes.bands ?? []) {
    const a = place(view, n.x0);
    const b = place(view, n.x1);
    if (a === null || b === null) continue;
    let y0 = plot.y;
    let y1 = plot.y + plot.h;
    if (n.lane !== null) {
      const row = view.slot[n.lane];
      if (row === undefined || row < 0) continue;
      y0 = laneTop + row * view.laneH + 1;
      y1 = y0 + view.laneH - 2;
    }
    const xa = px(a);
    const xb = n.point ? xa : Math.max(px(b), xa + 1);
    if (xb < plot.x - 200 || xa > plot.x + plot.w || y1 < plot.y || y0 > plot.y + plot.h) continue;
    const color = n.color ?? view.theme.accent;
    ctx.strokeStyle = color;
    if (n.point) {
      ctx.lineWidth = 1.5;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(Math.round(xa) + 0.5, y0);
      ctx.lineTo(Math.round(xa) + 0.5, y1);
      ctx.stroke();
      ctx.setLineDash([]);
    } else {
      ctx.globalAlpha = 0.1;
      ctx.fillStyle = color;
      ctx.fillRect(xa, y0, xb - xa, y1 - y0);
      ctx.globalAlpha = 0.7;
      ctx.lineWidth = 1;
      ctx.strokeRect(xa + 0.5, y0 + 0.5, Math.max(0, xb - xa - 1), y1 - y0 - 1);
      ctx.globalAlpha = 1;
    }
    if (n.text) label(view, ctx, n.text, xa + 3, Math.max(plot.y, y0) + 2, color, plot);
  }
  for (const n of notes.arrows ?? []) {
    const order = view.xscale === "order";
    const ra = view.slot[n.a.lane];
    const rb = view.slot[n.b.lane];
    if (ra === undefined || rb === undefined || ra < 0 || rb < 0) continue;
    // from an event, or a bar's end; to an event, or a bar's start
    const xa = px(order ? n.a.r2 : n.a.x2);
    const xb = px(order ? n.b.r : n.b.x);
    const ya = laneTop + (ra + 0.5) * view.laneH;
    const yb = laneTop + (rb + 0.5) * view.laneH;
    if (Math.max(xa, xb) < plot.x || Math.min(xa, xb) > plot.x + plot.w) continue;
    const color = n.color ?? view.theme.accent;
    const bend = Math.max(24, Math.min(160, Math.abs(xb - xa) / 2));
    const end = { x: xb - 3, y: yb };
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(xa, ya);
    ctx.bezierCurveTo(xa + bend, ya, end.x - bend, end.y, end.x, end.y);
    ctx.stroke();
    // the head, along the curve's end (horizontal)
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(xb, yb);
    ctx.lineTo(xb - 8, yb - 4);
    ctx.lineTo(xb - 8, yb + 4);
    ctx.closePath();
    ctx.fill();
    if (n.text) {
      const w = ctx.measureText(n.text).width + 8;
      label(view, ctx, n.text, (xa + xb) / 2 - w / 2, (ya + yb) / 2 - view.fs / 2 - 2, color, plot);
    }
  }
  ctx.restore();
}

/** Where the text of a new note is typed: an input over the plot, at the note. Enter keeps
 * it (`done(text)`), Esc or leaving it drops it (`done(null)`). */
export function askText(view: TimelineView, x: number, y: number, done: (text: string | null) => void): void {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "atl-note-input";
  input.placeholder = "Note (Enter keeps it, Esc drops it)";
  input.setAttribute("aria-label", "The annotation's text");
  input.style.left = `${Math.max(0, x)}px`;
  input.style.top = `${Math.max(0, y)}px`;
  let finished = false;
  const finish = (text: string | null) => {
    if (finished) return;
    finished = true;
    input.remove();
    done(text);
    view.root.focus({ preventScroll: true });
  };
  for (const type of ["pointerdown", "wheel", "dblclick"]) input.addEventListener(type, (e) => e.stopPropagation());
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      finish(input.value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      finish(null);
    }
  });
  input.addEventListener("blur", () => finish(null));
  view.stage.append(input);
  input.focus();
}
