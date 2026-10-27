// Find and step: the search box (`/`, Ctrl/Cmd+F; Enter and Shift+Enter step through the
// matches), the keys `.` and `,` (the next or previous mark of a lane) and `F` (fit the view
// to the focused mark). Python answers from every mark (Timeline: find.py); a page without
// Python searches the marks it holds.

import { globalIndex } from "./common";
import * as folding from "./folding";
import type { TimelineView } from "./view";

/** A mark found: where it is on both scales, its lane and its text. */
export interface Match {
  layer: string;
  /** The mark's index among its layer's (Python's browser order). */
  index: number;
  x: number;
  /** A bar's end (an event: its time). */
  x2: number;
  r: number;
  r2: number;
  lane: number;
  text: string;
}

export interface Found {
  /** Lanes whose names hold the query. */
  lanes: number[];
  /** Marks whose text holds it, in order on the scale (at most a thousand). */
  matches: Match[];
  /** How many marks hold it. */
  total: number;
}

/** Where a step starts: a place on the scale, and the mark there (layer null: none). */
export interface StepFrom {
  x: number;
  layer: string | null;
  index: number;
}

export type FindAsk = (q: string, scale: string) => Promise<Found>;
export type StepAsk = (lane: number, after: StepFrom, forward: boolean, scale: string) => Promise<Match | null>;

interface Candidate extends Match {
  /** The layer's place among the plot's. */
  rank: number;
}

/** The marks the browser holds: every event and bar loaded (a window's, for layers sent as
 * levels). */
function held(view: TimelineView): Candidate[] {
  const names = (view.spec?.layers ?? []).map((l) => l.name);
  const out: Candidate[] = [];
  for (const l of view.layers) {
    const d = l.data;
    const rank = names.indexOf(d.spec.name);
    for (let i = 0; i < d.count; i++)
      out.push({ layer: d.spec.name, rank, index: globalIndex(l, i), x: d.time[i], x2: d.time[i], r: d.rank[i], r2: d.rank[i], lane: d.lane[i], text: d.text?.[i] ?? "" });
  }
  for (const b of view.bars) {
    const d = b.data;
    const rank = names.indexOf(d.spec.name);
    const text = d.text ?? d.states;
    for (let i = 0; i < d.count; i++) {
      const index = b.globalIndex(i);
      if (index < 0) continue; // short bars merged
      out.push({ layer: d.spec.name, rank, index, x: d.start[i], x2: d.end[i], r: d.rankStart[i], r2: d.rankEnd[i], lane: d.lane[i], text: text?.[i] ?? "" });
    }
  }
  return out;
}

function key(c: Candidate, order: boolean): [number, number, number] {
  return [order ? c.r : c.x, c.rank, c.index];
}

function before(a: [number, number, number], b: [number, number, number]): boolean {
  return a[0] < b[0] || (a[0] === b[0] && (a[1] < b[1] || (a[1] === b[1] && a[2] < b[2])));
}

/** Search what the browser holds (a page without Python). */
export function findHeld(view: TimelineView, query: string, scale: string): Found {
  const q = query.trim().toLowerCase();
  if (!q) return { lanes: [], matches: [], total: 0 };
  const names = view.spec?.lanes.names ?? [];
  const lanes = names.flatMap((n, i) => (String(n).toLowerCase().includes(q) ? [i] : []));
  const order = scale === "order";
  const hits = held(view).filter((c) => c.text && c.text.toLowerCase().includes(q));
  hits.sort((a, b) => (before(key(a, order), key(b, order)) ? -1 : before(key(b, order), key(a, order)) ? 1 : 0));
  return { lanes, matches: hits.slice(0, 1000), total: hits.length };
}

/** Step among what the browser holds (a page without Python). */
export function stepHeld(view: TimelineView, lane: number, from: StepFrom, forward: boolean, scale: string): Match | null {
  const order = scale === "order";
  const names = (view.spec?.layers ?? []).map((l) => l.name);
  const k0 = from.layer === null || !names.includes(from.layer) ? (forward ? -1 : 2 ** 31) : names.indexOf(from.layer);
  const i0 = from.layer === null ? (forward ? -1 : 2 ** 52) : from.index;
  const start: [number, number, number] = [from.x, k0, i0];
  let best: Candidate | null = null;
  for (const c of held(view)) {
    if (c.lane !== lane) continue;
    const k = key(c, order);
    if (forward ? !before(start, k) : !before(k, start)) continue;
    if (!best || (forward ? before(k, key(best, order)) : before(key(best, order), k))) best = c;
  }
  return best;
}

/** The search box: an input, where it is among the matches, and buttons to step. */
export class Finder {
  readonly el: HTMLDivElement;
  private readonly input: HTMLInputElement;
  private readonly status: HTMLSpanElement;
  private found: Found = { lanes: [], matches: [], total: 0 };
  /** The match shown: an index into the lanes, then the marks; -1: none. */
  private at = -1;
  private timer = 0;
  private asked = 0;
  /** The query the matches are of. */
  private query = "";

  constructor(private readonly view: TimelineView) {
    this.el = document.createElement("div");
    this.el.className = "atl-finder";
    this.el.hidden = true;
    this.el.setAttribute("role", "search");
    for (const type of ["pointerdown", "wheel", "dblclick"]) this.el.addEventListener(type, (e) => e.stopPropagation());
    this.input = document.createElement("input");
    this.input.type = "search";
    this.input.placeholder = "Find text or lanes";
    this.input.setAttribute("aria-label", "Find text or lanes");
    this.status = document.createElement("span");
    this.status.className = "atl-finder-status";
    this.status.setAttribute("aria-live", "polite");
    const button = (text: string, title: string, fn: () => void) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      b.title = title;
      b.setAttribute("aria-label", title);
      b.addEventListener("click", fn);
      return b;
    };
    this.el.append(
      this.input,
      this.status,
      button("↑", "Previous match · Shift+Enter", () => this.next(false)),
      button("↓", "Next match · Enter", () => this.next(true)),
      button("×", "Close · Esc", () => this.close()),
    );
    this.input.addEventListener("input", () => {
      window.clearTimeout(this.timer);
      this.timer = window.setTimeout(() => void this.search(), 150);
    });
    this.input.addEventListener("keydown", (e) => {
      // the plot's keys and the notebook's shortcuts stay out of the box
      e.stopPropagation();
      if (e.key === "Enter") {
        e.preventDefault();
        window.clearTimeout(this.timer);
        if (this.input.value !== this.query) void this.search().then(() => this.next(!e.shiftKey));
        else this.next(!e.shiftKey);
      } else if (e.key === "Escape") {
        e.preventDefault();
        this.close();
        view.root.focus({ preventScroll: true });
      }
    });
  }

  get isOpen(): boolean {
    return !this.el.hidden;
  }

  open(): void {
    this.el.hidden = false;
    this.input.focus();
    this.input.select();
  }

  close(): void {
    this.el.hidden = true;
    this.view.setFocus(null);
  }

  /** Search again (the plot changed, or the scale). */
  refresh(): void {
    if (this.isOpen && this.query) void this.search();
  }

  private async search(): Promise<void> {
    const q = this.input.value;
    this.query = q;
    const n = ++this.asked;
    const scale = this.view.xscale;
    let found: Found;
    try {
      found = this.view.callbacks.onFind ? await this.view.callbacks.onFind(q, scale) : findHeld(this.view, q, scale);
    } catch {
      found = findHeld(this.view, q, scale);
    }
    if (n !== this.asked) return; // a later search answered first
    this.found = found;
    this.at = -1;
    this.show();
  }

  next(forward: boolean): void {
    const n = this.found.lanes.length + this.found.matches.length;
    if (!n) return;
    this.at = this.at < 0 ? (forward ? 0 : n - 1) : (this.at + (forward ? 1 : n - 1)) % n;
    const lanes = this.found.lanes;
    if (this.at < lanes.length) this.view.focusLane(lanes[this.at]);
    else this.view.setFocus(this.found.matches[this.at - lanes.length], true);
    this.show();
  }

  private show(): void {
    const { lanes, matches, total } = this.found;
    const n = lanes.length + matches.length;
    if (!this.query.trim()) this.status.textContent = "";
    else if (!n) this.status.textContent = "no match";
    else {
      const more = total > matches.length ? ` (first ${matches.length.toLocaleString("en-US")} of ${total.toLocaleString("en-US")})` : "";
      this.status.textContent = this.at < 0 ? `${n.toLocaleString("en-US")} found${more}` : `${(this.at + 1).toLocaleString("en-US")} of ${n.toLocaleString("en-US")}${more}`;
    }
  }
}

/** Unfold the lanes of the tree `lane` is in, and scroll it into sight. */
export function revealLane(view: TimelineView, lane: number): void {
  const tree = view.spec?.lanes.tree;
  let opened = false;
  if (tree) {
    for (let k = 0; k < Math.min(lane, tree.size.length); k++) {
      if (k + tree.size[k] > lane && !view.open[k]) {
        view.open[k] = 1;
        opened = true;
      }
    }
  }
  if (opened) folding.computeRows(view);
  const row = view.slot[lane];
  if (row < 0) return;
  const plot = view.plot();
  const y = row * view.laneH;
  if (y < view.scrollY || y + view.laneH > view.scrollY + plot.h) view.scrollY = y - Math.max(0, (plot.h - view.laneH) / 2);
  folding.clampScroll(view);
  if (opened) view.layout();
}

/** Bring a mark into sight: its lane, and its place when it is out of the view (the view
 * keeps its span); with `fit`, the view fits the mark (a bar), or zooms in on it. */
export function reveal(view: TimelineView, m: Match, fit: boolean): void {
  revealLane(view, m.lane);
  const order = view.xscale === "order";
  const a = order ? m.r : m.x;
  const b = order ? m.r2 : m.x2;
  const c = view.camera;
  const span = c.span;
  if (fit) {
    if (b > a) c.fit(a, b, 0.15);
    else c.fit(a - span / 8, a + span / 8, 0);
  } else if (a < c.left + span * 0.05 || a > c.right - span * 0.05) c.fit(a - span / 2, a + span / 2, 0);
}
