// Dodging: events of one lane that would overlap are spread over sub-rows (a narrow
// beeswarm), so ties and near-ties stay countable. Greedy from left to right: each event goes
// to the first sub-row (centre, above, below, two above, ...) whose last event is far enough
// left; when none is, to the sub-row that has been free longest.

/** The most sub-rows a lane gets: a tall lane (full screen) spreads ties out this far. */
export const MAX_ROWS = 31;

/** Offset of sub-row `r`, in steps: 0, −1, +1, −2, +2, ... */
export function rowOffset(r: number): number {
  return r === 0 ? 0 : r % 2 === 1 ? -(r + 1) / 2 : r / 2;
}

/**
 * Dodge events `start..end` (contiguous, sorted by x).
 *
 * @param xs screen x of each event (CSS px)
 * @param minDist the distance below which two events overlap (px)
 * @param rows the number of sub-rows available (odd: a centre row and pairs around it)
 * @param step the distance between sub-rows (px)
 * @param out receives each event's vertical offset (px)
 */
export function dodge(
  xs: ArrayLike<number>,
  start: number,
  end: number,
  minDist: number,
  rows: number,
  step: number,
  out: Float32Array,
): void {
  const last = new Float64Array(Math.max(1, rows)).fill(-Infinity);
  for (let i = start; i < end; i++) {
    const x = xs[i];
    let chosen = -1;
    for (let r = 0; r < last.length; r++) {
      if (x - last[r] >= minDist) {
        chosen = r;
        break;
      }
    }
    if (chosen < 0) {
      chosen = 0;
      for (let r = 1; r < last.length; r++) if (last[r] < last[chosen]) chosen = r;
    }
    last[chosen] = x;
    out[i] = rowOffset(chosen) * step;
  }
}

/** How many sub-rows fit in a lane of `laneHeight` for marks of `size` (odd, 1 to MAX_ROWS). */
export function rowsFor(laneHeight: number, size: number, step: number): number {
  const pairs = Math.floor((laneHeight / 2 - size / 2 - 1) / step);
  return Math.max(1, Math.min(MAX_ROWS, 1 + 2 * Math.max(0, pairs)));
}
