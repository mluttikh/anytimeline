// Stem labels (events layers with labels="stems"): a story timeline. Each event stays on its
// lane's line; its text goes in a box above or below the line, joined to the event by a
// line (a stem). The boxes take levels, alternating above and below (+1, −1, +2, −2, …), so
// none overlap: the most important first, then from left to right, each in the first level
// where it fits. A label gets no box only when no level has room for it.

export interface StemItem {
  /** The event (an index into its layer). */
  index: number;
  /** Where the event is (CSS px). */
  x: number;
  /** The box's size (CSS px). */
  w: number;
  importance: number;
}

export interface StemPlaced {
  index: number;
  x: number;
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
  /** The box's left edge sits this far left of its event (px), so the stem meets the box near
   * its start and the text reads from the event onwards. */
  inset: number;
  /** Boxes stay within left..right (px). */
  left: number;
  right: number;
}

/** The order levels are tried in: +1, −1, +2, −2, … */
export function levelOrder(levels: number): number[] {
  const out: number[] = [];
  for (let k = 1; k <= levels; k++) out.push(k, -k);
  return out;
}

/** Give each item a level and a box position; items that fit nowhere are left out. */
export function placeStems(items: StemItem[], space: StemSpace): StemPlaced[] {
  const order = [...items].sort((a, b) => b.importance - a.importance || a.x - b.x || a.index - b.index);
  const taken = new Map<number, [number, number][]>();
  const tries = levelOrder(space.levels);
  const placed: StemPlaced[] = [];
  for (const item of order) {
    const x0 = Math.max(space.left, Math.min(space.right - item.w, item.x - space.inset));
    const x1 = x0 + item.w;
    for (const level of tries) {
      const boxes = taken.get(level) ?? [];
      if (boxes.some(([a, b]) => x0 < b + space.gap && x1 + space.gap > a)) continue;
      boxes.push([x0, x1]);
      taken.set(level, boxes);
      placed.push({ index: item.index, x: item.x, level, x0, w: item.w });
      break;
    }
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
