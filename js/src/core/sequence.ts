// The order of every instant of the plot (the Order scale): their times by rank. A plot with
// layers sent as levels has every `step`-th time (and the last); the windows Python sends
// bring the exact times of their range, and between those the times are interpolated.

import { lowerBound, upperBound } from "./scene";

export class Sequence {
  /** The exact times of a range of ranks (from a window), or null. */
  private slice: { offset: number; times: Float64Array } | null = null;
  /** Changes with the exact times known: positions computed from them are out of date. */
  version = 0;

  constructor(
    /** Every `step`-th time (and the last), or every time when `step` is 1. */
    readonly kept: Float64Array,
    readonly step: number,
    /** How many instants there are. */
    readonly count: number,
  ) {}

  get exact(): boolean {
    return this.step === 1;
  }

  /** The exact times of ranks offset .. offset + times.length - 1 (a window's). */
  setSlice(offset: number, times: Float64Array): void {
    if (this.exact) return;
    this.slice = { offset, times };
    this.version++;
  }

  /** The rank of kept time i. */
  private rankOf(i: number): number {
    return Math.min(i * this.step, this.count - 1);
  }

  /** The time of instant r (a whole rank from 0 to count - 1). */
  time(r: number): number {
    if (this.exact) return this.kept[r];
    const s = this.slice;
    if (s && r >= s.offset && r < s.offset + s.times.length) return s.times[r - s.offset];
    const i = Math.min(Math.floor(r / this.step), this.kept.length - 1);
    const j = Math.min(i + 1, this.kept.length - 1);
    const ri = this.rankOf(i);
    const rj = this.rankOf(j);
    if (rj <= ri) return this.kept[i];
    return this.kept[i] + ((this.kept[j] - this.kept[i]) * (r - ri)) / (rj - ri);
  }

  /** The first rank whose time is at least t (count when none). */
  lower(t: number): number {
    return this.bound(t, lowerBound);
  }

  /** The first rank whose time is after t (count when none). */
  upper(t: number): number {
    return this.bound(t, upperBound);
  }

  private bound(t: number, search: (a: ArrayLike<number>, x: number) => number): number {
    if (this.exact) return search(this.kept, t);
    const s = this.slice;
    // inside the exact range (not at its ends, where earlier ranks may share the time)
    if (s && s.times.length && t > s.times[0] && t < s.times[s.times.length - 1]) return s.offset + search(s.times, t);
    const j = search(this.kept, t);
    if (j <= 0) return 0;
    if (j >= this.kept.length) return this.count;
    const r0 = this.rankOf(j - 1);
    const r1 = this.rankOf(j);
    const t0 = this.kept[j - 1];
    const t1 = this.kept[j];
    const f = t1 > t0 ? (t - t0) / (t1 - t0) : 1;
    return Math.max(r0 + 1, Math.min(r1, Math.ceil(r0 + f * (r1 - r0))));
  }

  /** The x of time t on the Order scale: the rank of an instant at t, else its place between
   * the instants before and after it. */
  position(t: number): number {
    const n = this.count;
    const j = this.lower(t);
    if (j < n && this.time(j) === t) return j;
    if (j === 0) return -0.5;
    if (j >= n) return n - 0.5;
    const t0 = this.time(j - 1);
    const t1 = this.time(j);
    return j - 1 + (t1 > t0 ? (t - t0) / (t1 - t0) : 1);
  }
}
