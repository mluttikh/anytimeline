// Stem labels (events layers with labels="stems"): a story timeline. Each event stays on its
// lane's line; its text goes in a box above or below the line, joined to the event by a line
// (a stem). The boxes take levels, alternating above and below (+1, −1, +2, −2, …), so none
// overlap: the most important first, then from left to right, each in the first level where
// it fits.
//
// No stem passes behind a box (labella.js's "stubs"): a stem reserves a narrow corridor in
// every level it crosses on its way to its box, and a box goes neither over another box nor
// over a corridor. A box may slide sideways to fit:
// - straight stems: as long as its event stays under the box (the stem meets it from below);
// - curved stems: further, up to about a box's width; the stem then bends (an S-curve in the
//   band between the line and the first level) and rises straight to the box.
// A label gets no box only when no level has room for it.

export type StemShape = "straight" | "curved";

export interface StemItem {
  /** The event (an index into its layer). */
  index: number;
  /** Where the event is (CSS px). */
  x: number;
  /** The box's size (CSS px). */
  w: number;
  importance: number;
  /** A badge for events without a box: placed after every event, and not counted as an
   * event still to be placed. */
  badge?: boolean;
}

export interface StemPlaced {
  index: number;
  /** The event (CSS px). */
  x: number;
  /** Where the stem meets the box (CSS px): the event's x for a straight stem. */
  cx: number;
  /** The level: 1, 2, … above the line, −1, −2, … below. */
  level: number;
  /** The box's left edge (CSS px). */
  x0: number;
  w: number;
}

export interface StemSpace {
  /** Levels on each side of the line. */
  levels: number;
  /** The least room between two boxes of a level (px). */
  gap: number;
  /** Where a box starts, left of its event, when nothing is in the way (px). */
  inset: number;
  /** Boxes stay within left..right (px). */
  left: number;
  right: number;
  shape: StemShape;
}

/** Room kept on each side of a stem passing a level (px). */
const CORRIDOR = 4;
/** A stem meets its box at least this far from the box's ends (px). */
const MARGIN = 7;
/** What a level further from the line costs, against moving a stem sideways (px × 2). */
const LEVEL_COST = 60;

/** The order levels are tried in: +1, −1, +2, −2, … */
export function levelOrder(levels: number): number[] {
  const out: number[] = [];
  for (let k = 1; k <= levels; k++) out.push(k, -k);
  return out;
}

type Span = [number, number];

const hits = (spans: Span[] | undefined, a: number, b: number, pad: number) =>
  !!spans && spans.some(([s, e]) => a < e + pad && b + pad > s);

/** The levels a stem to `level` passes on its way: 1 … level − 1 on its side. */
function passes(level: number): number[] {
  const out: number[] = [];
  for (let k = 1; k < Math.abs(level); k++) out.push(Math.sign(level) * k);
  return out;
}

/** Give each item a level and a box position; items that fit nowhere are left out. */
export function placeStems(items: StemItem[], space: StemSpace): StemPlaced[] {
  // events by importance, then from left to right; badges last
  const order = [...items].sort((a, b) => Number(!!a.badge) - Number(!!b.badge) || b.importance - a.importance || a.x - b.x || a.index - b.index);
  const boxes = new Map<number, Span[]>();
  const corridors = new Map<number, Span[]>();
  const tries = levelOrder(space.levels);
  const placed: StemPlaced[] = [];
  const add = (m: Map<number, Span[]>, level: number, span: Span) => {
    const list = m.get(level);
    if (list) list.push(span);
    else m.set(level, [span]);
  };
  const done = new Set<number>();
  for (const item of order) {
    done.add(item.index);
    const { x, w } = item;
    // where the box may start: the stem meets it MARGIN in from its ends; a curved stem may
    // also meet it away from the event, up to about a box's width
    // (a badge may always bend: it is small and goes wherever there is room nearby)
    const reach = space.shape === "curved" || item.badge ? Math.max(w, 120) : 0;
    // (a box may overhang the bounds by MARGIN: an event at the edge still gets its box)
    const lo = Math.max(space.left - MARGIN, x - reach - (w - MARGIN));
    const hi = Math.min(space.right - w + MARGIN, x + reach - MARGIN);
    if (hi < lo) continue;
    const want = Math.max(lo, Math.min(hi, x - space.inset));
    // the best place over all levels: few events still to be placed under the box (their
    // stems would have to go round it), then little sideways, then near the line
    let best: StemPlaced | null = null;
    let bestCost = Infinity;
    for (const level of tries) {
      // candidate starts: where we want it; just clear of each obstacle in this level; and,
      // for a stem that may meet the box away from its event, with the stem just clear of
      // each box on the levels it passes (through the gaps between them)
      const here = [...(boxes.get(level) ?? []), ...(corridors.get(level) ?? [])];
      const starts = [want];
      for (const [s, e] of here) starts.push(e + space.gap, s - space.gap - w);
      if (reach > 0) {
        for (const k of passes(level)) {
          for (const [s, e] of boxes.get(k) ?? []) {
            const right = e + CORRIDOR + 1;
            const left = s - CORRIDOR - 1;
            starts.push(right - MARGIN, right - (w - MARGIN), left - MARGIN, left - (w - MARGIN));
          }
        }
      }
      for (const x0 of starts) {
        if (x0 < lo - 0.01 || x0 > hi + 0.01) continue;
        const x1 = x0 + w;
        if (hits(boxes.get(level), x0, x1, space.gap) || hits(corridors.get(level), x0, x1, 1)) continue;
        // where the stem meets the box: under the event when it can, else the nearest end
        const cx = Math.max(x0 + MARGIN, Math.min(x1 - MARGIN, x));
        // its corridor through the levels it passes must be free of boxes
        if (passes(level).some((k) => hits(boxes.get(k), cx - CORRIDOR, cx + CORRIDOR, 0))) continue;
        let covered = 0;
        for (const other of order) {
          if (!other.badge && !done.has(other.index) && other.x > x0 - CORRIDOR && other.x < x1 + CORRIDOR) covered++;
        }
        const cost = covered * 1000 + Math.abs(x0 - want) * 0.25 + Math.abs(cx - x) * 2 + (Math.abs(level) - 1) * LEVEL_COST;
        if (cost < bestCost) {
          bestCost = cost;
          best = { index: item.index, x, cx, level, x0, w };
        }
      }
    }
    if (!best) continue;
    add(boxes, best.level, [best.x0, best.x0 + best.w]);
    for (const k of passes(best.level)) add(corridors, k, [best.cx - CORRIDOR, best.cx + CORRIDOR]);
    placed.push(best);
  }
  return placed;
}

/** How many levels fit on each side of the line in a lane of `laneH` (px), for boxes of
 * `boxH` with `gap` between them, starting `start` px from the line. */
export function levelsFor(laneH: number, boxH: number, gap: number, start: number): number {
  return Math.max(0, Math.floor((laneH / 2 - 3 - start + gap) / (boxH + gap)));
}

/** The middle of a box at `level` (px from the line; negative: above). */
export function levelOffset(level: number, boxH: number, gap: number, start: number): number {
  const k = Math.abs(level);
  const d = start + (k - 1) * (boxH + gap) + boxH / 2;
  return level > 0 ? -d : d;
}

/**
 * Wrap `text` into lines no wider than `width` (px), at spaces, at most `maxLines` lines;
 * the last line ends in "…" when text is left over. A word longer than the width is cut.
 */
export function wrapText(text: string, width: number, maxLines: number, measure: (s: string) => number): string[] {
  if (!Number.isFinite(width) || measure(text) <= width) return [text];
  const fit = (s: string) => {
    if (measure(s) <= width) return s;
    let lo = 0;
    let hi = s.length;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (measure(s.slice(0, mid) + "…") <= width) lo = mid;
      else hi = mid - 1;
    }
    return s.slice(0, lo).trimEnd() + "…";
  };
  if (maxLines <= 1) return [fit(text)];
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (let k = 0; k < words.length; k++) {
    const next = line ? `${line} ${words[k]}` : words[k];
    if (!line || measure(next) <= width) {
      line = next;
      continue;
    }
    lines.push(line);
    if (lines.length === maxLines - 1) {
      line = words.slice(k).join(" "); // the last line takes the rest
      break;
    }
    line = words[k];
  }
  lines.push(line);
  return lines.map(fit);
}

/** A group of events next to each other that got no box: a badge ("+N") stands for them. */
export interface StemCluster {
  /** The events (indices into their layer). */
  indices: number[];
  /** Their span (CSS px). */
  x0: number;
  x1: number;
}

/** Group the events that got no box: neighbours closer than `gap` px go together, unless an
 * event with a box (at `boxed`, px) lies between them. */
export function clusterHidden(hidden: { index: number; x: number }[], gap: number, boxed: number[] = []): StemCluster[] {
  const sorted = [...hidden].sort((a, b) => a.x - b.x);
  const out: StemCluster[] = [];
  for (const h of sorted) {
    const last = out[out.length - 1];
    if (last && h.x - last.x1 <= gap && !boxed.some((x) => x > last.x1 && x < h.x)) {
      last.indices.push(h.index);
      last.x1 = h.x;
    } else {
      out.push({ indices: [h.index], x0: h.x, x1: h.x });
    }
  }
  return out;
}
