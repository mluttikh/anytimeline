// The horizontal camera: which part of the time axis the plot shows. Positions are float64
// in the axis's units (ticks, or ranks on the sequence scale).

export class TimeCamera {
  /** The position at the plot's left edge. */
  left = 0;
  /** Pixels per unit. */
  scale = 1;
  /** Plot width in CSS pixels. */
  width = 1;
  private minScale = 1e-300;
  private maxScale = 1e300;
  private extent: [number, number] = [0, 1];

  get right(): number {
    return this.left + this.width / this.scale;
  }

  get span(): number {
    return this.width / this.scale;
  }

  /**
   * The data's extent, and the smallest span one pixel may show (e.g. 1 ns as ticks). Zoom
   * out stops at 50× the extent.
   */
  setLimits(extent: [number, number], minUnitsPerPx: number): void {
    this.extent = extent;
    const span = Math.max(extent[1] - extent[0], minUnitsPerPx * 10);
    this.maxScale = 1 / minUnitsPerPx;
    this.minScale = 1 / ((span * 50) / Math.max(1, this.width));
  }

  setWidth(width: number): void {
    if (width <= 0) return;
    // keep the visible range when the plot is resized
    const span = this.span;
    this.width = width;
    this.scale = width / span;
    this.clamp();
  }

  /** Show [a, b] with `margin` (a fraction of the span) on each side. */
  fit(a: number, b: number, margin = 0.03): void {
    let lo = a;
    let hi = b;
    if (!(hi > lo)) {
      const pad = Math.max(Math.abs(lo) * 1e-6, 1 / this.maxScale) * 50;
      lo -= pad;
      hi += pad;
    }
    const pad = (hi - lo) * margin;
    this.left = lo - pad;
    this.scale = this.width / (hi - lo + 2 * pad);
    this.clamp();
  }

  fitExtent(): void {
    this.fit(this.extent[0], this.extent[1]);
  }

  toPx(x: number): number {
    return (x - this.left) * this.scale;
  }

  fromPx(px: number): number {
    return this.left + px / this.scale;
  }

  /** Zoom by `factor` (> 1 zooms in) keeping the position under `px` in place. */
  zoomAt(px: number, factor: number): void {
    const at = this.fromPx(px);
    this.scale = Math.min(this.maxScale, Math.max(this.minScale, this.scale * factor));
    this.left = at - px / this.scale;
    this.clamp();
  }

  pan(dpx: number): void {
    this.left -= dpx / this.scale;
    this.clamp();
  }

  /** Keep part of the data in view: the view may not leave the extent by more than 90%. */
  private clamp(): void {
    this.scale = Math.min(this.maxScale, Math.max(this.minScale, this.scale));
    const span = this.span;
    const [a, b] = this.extent;
    const lo = a - span * 0.9;
    const hi = b - span * 0.1;
    if (this.left < lo) this.left = lo;
    if (this.left > hi) this.left = hi;
  }
}
