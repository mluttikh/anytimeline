// Dodging: events of one lane that would overlap are spread over sub-rows (a beeswarm), so
// ties and near-ties stay countable. Greedy from left to right: each event goes to the first
// sub-row (centre, above, below, two above, ...) whose last event is far enough left; when
// none is, to the sub-row that has been free longest.
//
// The sub-rows are as far apart as the lane allows (spacing): a mark and a pixel apart when
// there is room, so marks do not overlap; closer, down to 0.6 of a mark (neighbours overlap),
// when the rows the events need do not fit otherwise.

/** The most sub-rows a lane gets: a tall lane (full screen) spreads ties out this far. */
export const MAX_ROWS = 101;

/** The closest sub-rows get, as a fraction of the mark size. */
export const MIN_STEP = 0.6;

/** The distance between sub-rows (px) for marks of `size` in a lane of `laneHeight`, when
 * the events need `pairs` sub-rows on each side of the centre: as far apart as fits, from
 * MIN_STEP × size up to a mark and a pixel, keeping a margin at the lane's edges (a tenth
 * of the lane, at least 3 px) so the columns of neighbouring lanes stay apart. */
export function spacing(laneHeight: number, size: number, pairs: number): number {
  const min = Math.max(2.5, size * MIN_STEP);
  const max = size + 1;
  if (pairs <= 0) return max;
  const margin = Math.max(3, laneHeight * 0.1);
  const room = (laneHeight / 2 - size / 2 - margin) / pairs;
  return Math.max(min, Math.min(max, room));
}

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
