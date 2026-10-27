// Building a frame: the events in view culled and dodged, routes as segments, and what
// the renderer draws; then the front canvas.

import { dodge, rowsFor, spacing } from "./dodge";
import type { FrameDraw, SegmentDraw } from "./renderers/renderer";
import { lowerBound, parseHex, upperBound } from "./scene";
import { TimeAxis } from "./time";
import { isStems, LABEL_BUDGET, type Layer, rgb01, ROUTE_BUDGET } from "./common";
import * as folding from "./folding";
import * as drawing from "./drawing";
import type { TimelineView } from "./view";

export function renderFrame(view: TimelineView): void {
  const t0 = performance.now();
  view.info.textContent = [view.infoText, view.renderer?.kind ?? ""].filter(Boolean).join(" · ");
  const plot = view.plot();
  const backCtx = view.back.getContext("2d")!;
  const frontCtx = view.front.getContext("2d")!;
  backCtx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
  frontCtx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
  backCtx.fillStyle = view.theme.bg;
  backCtx.fillRect(0, 0, view.width, view.height);
  frontCtx.clearRect(0, 0, view.width, view.height);
  if (!view.spec || !view.axis) {
    view.renderer?.render({ plot, bars: [], segments: [], layers: [], background: [1, 1, 1], selection: [1, 0, 0], hover: [0, 0, 0] });
    return;
  }
  view.rebase();
  const laneTop = plot.y - view.scrollY;
  // rows in view (with folded lanes, a row is not the lane of the same number)
  const l0 = Math.max(0, Math.floor((plot.y - laneTop) / view.laneH));
  const l1 = Math.min(view.laneAt.length - 1, Math.floor((plot.y + plot.h - laneTop) / view.laneH));

  // lane bands and grid lines
  backCtx.save();
  backCtx.beginPath();
  backCtx.rect(0, plot.y, view.width, plot.h);
  backCtx.clip();
  const headers = folding.headerSet(view);
  for (let l = l0; l <= l1; l++) {
    if (headers?.has(view.laneAt[l])) {
      // a group's header: a tinted band with a line above it
      backCtx.fillStyle = view.theme.grid;
      backCtx.globalAlpha = 0.55;
      backCtx.fillRect(0, laneTop + l * view.laneH, view.width, view.laneH);
      backCtx.globalAlpha = 1;
      backCtx.fillStyle = view.theme.muted;
      backCtx.fillRect(0, Math.round(laneTop + l * view.laneH), view.width, 1);
    } else if (l % 2 === 1) {
      backCtx.fillStyle = view.theme.band;
      backCtx.fillRect(0, laneTop + l * view.laneH, view.width, view.laneH);
    }
  }
  const ticks = axisTicks(view, plot.w);
  const gaps = view.xscale === "order" ? drawing.visibleGaps(view, frontCtx, plot, ticks.pinned) : [];
  if (gaps.length) {
    backCtx.strokeStyle = view.theme.grid;
    backCtx.setLineDash([2, 3]);
    backCtx.beginPath();
    for (const g of gaps) {
      backCtx.moveTo(Math.round(g.x) + 0.5, plot.y);
      backCtx.lineTo(Math.round(g.x) + 0.5, plot.y + plot.h);
    }
    backCtx.stroke();
    backCtx.setLineDash([]);
  }
  backCtx.strokeStyle = view.theme.grid;
  backCtx.lineWidth = 1;
  backCtx.beginPath();
  for (const t of ticks.minor) {
    const x = Math.round(plot.x + view.camera.toPx(t.x)) + 0.5;
    backCtx.moveTo(x, plot.y);
    backCtx.lineTo(x, plot.y + plot.h);
  }
  backCtx.stroke();
  if (view.layers.some(isStems)) {
    // a story's line through the middle of each lane
    backCtx.fillStyle = view.theme.muted;
    backCtx.globalAlpha = 0.5;
    for (let r = l0; r <= l1; r++) backCtx.fillRect(plot.x, Math.round(laneTop + (r + 0.5) * view.laneH) - 1, plot.w, 2);
    backCtx.globalAlpha = 1;
  }
  if (view.values.length) {
    const vv = drawing.valueView(view, plot);
    for (const v of view.values) v.draw(backCtx, vv, l0, l1);
  }
  backCtx.restore();

  // cull, dodge, routes
  const frame: FrameDraw = {
    plot,
    bars: [],
    segments: [],
    layers: [],
    background: rgb01(view.theme.bg),
    selection: rgb01(view.theme.select),
    hover: rgb01(view.theme.text),
  };
  const fade = Object.values(view.marks).some((m) => m.length > 0);
  let inView = 0;
  const bv = drawing.barView(view, plot);
  const seqScale = view.xscale === "order";
  for (const b of view.bars) {
    b.cull(view.laneAt, l0, l1, view.camera.left - 2 / view.camera.scale, view.camera.right + 2 / view.camera.scale, seqScale);
    inView += b.draw.visibleCount;
    const d = b.draw;
    d.offset = view.camera.left - view.base;
    d.scale = view.camera.scale;
    d.laneTop = laneTop;
    d.laneHeight = view.laneH;
    d.maxBar = b.maxBar(bv.maxBar);
    d.fade = fade;
    frame.bars.push(d);
  }
  for (const l of view.layers) {
    cull(view, l, l0, l1, plot.w);
    inView += l.draw.visibleCount;
    if (l.data.spec.overlap === "dodge" && view.dodgeOn && !isStems(l)) dodgeLayer(view, l, l0, l1);
    const d = l.draw;
    d.offset = view.camera.left - view.base;
    d.scale = view.camera.scale;
    d.laneTop = laneTop;
    d.laneHeight = view.laneH;
    d.fade = fade;
    frame.layers.push(d);
    const seg = segments(view, l, plot, laneTop, l0, l1);
    if (seg) frame.segments.push(seg);
  }
  view.renderer?.render(frame);

  // front: axis, lane names, labels, gaps, hover, box
  drawing.drawAxis(view, frontCtx, plot, ticks);
  drawing.drawLanes(view, frontCtx, plot, laneTop, l0, l1);
  drawing.drawBarText(view, frontCtx, bv, l0, l1, inView <= LABEL_BUDGET);
  drawing.drawStems(view, frontCtx, plot, laneTop, l0, l1);
  if (inView <= LABEL_BUDGET) drawing.drawLabels(view, frontCtx, plot, laneTop);
  drawing.drawMarkers(view, frontCtx, plot);
  drawing.drawValueScales(view, frontCtx, plot, l0, l1);
  drawing.drawLinkedCursor(view, frontCtx, plot);
  if (gaps.length) drawing.drawGaps(view, frontCtx, plot, gaps);
  drawing.drawHover(view, frontCtx, plot, laneTop);
  if (view.box) drawing.drawBox(view, frontCtx, plot, view.box);
  view.callbacks.onPerf?.({ frame_ms: Math.round((performance.now() - t0) * 100) / 100, in_view: inView });
}

export function axisTicks(view: TimelineView, width: number) {
  if (view.xscale === "order" || !view.axis) {
    const order = new TimeAxis({ kind: "order", unit: "", origin_ns: "0", origin: 0, timezone: "UTC", extent: [0, 1] });
    const t = order.ticks(view.camera.left, view.camera.right, (width * 11) / (view.fs - 1));
    // the time of the first event in view gives the context
    if (view.seqTimes?.length && view.axis && view.spec?.time.kind !== "order") {
      const i = Math.max(0, Math.min(view.seqTimes.length - 1, Math.ceil(view.camera.left)));
      t.pinned = `from ${view.axis.formatFull(view.seqTimes[i])}`;
    }
    return t;
  }
  return view.axis.ticks(view.camera.left, view.camera.right, (width * 11) / (view.fs - 1));
}

/** Collect the events in view (lanes l0..l1, x within the view plus a margin). */
export function cull(view: TimelineView, l: Layer, l0: number, l1: number, width: number): void {
  const src = view.xsrc(l);
  const starts = l.data.laneStarts;
  const margin = 12 / view.camera.scale;
  const a = view.camera.left - margin;
  const b = view.camera.left + width / view.camera.scale + margin;
  const vis = l.draw.visible;
  let n = 0;
  for (let r = l0; r <= l1 && r < view.laneAt.length; r++) {
    const lane = view.laneAt[r];
    if (lane + 1 >= starts.length) continue;
    const i0 = lowerBound(src, a, starts[lane], starts[lane + 1]);
    const i1 = upperBound(src, b, i0, starts[lane + 1]);
    for (let i = i0; i < i1; i++) {
      vis[n++] = i;
      l.xs[i] = (src[i] - view.camera.left) * view.camera.scale;
    }
  }
  l.draw.visibleCount = n;
}

/** Spread overlapping events of each lane over sub-rows; only when the scale or range changed. */
export function dodgeLayer(view: TimelineView, l: Layer, l0: number, l1: number): void {
  const cam = view.camera;
  const d = l.dodged;
  if (d && d.scale === cam.scale && d.laneH === view.laneH && cam.left >= d.left && cam.right <= d.right) return;
  const src = view.xsrc(l);
  const starts = l.data.laneStarts;
  const span = cam.span;
  const a = cam.left - span;
  const b = cam.right + span;
  const sizes = l.data.size;
  let maxSize = 1;
  const dy = l.draw.dy.data;
  dy.fill(0);
  const order: number[] = [];
  // dodge every lane in a wider range than the view, so panning needs no new pass
  for (let r = Math.max(0, l0 - 2); r <= l1 + 2 && r < view.laneAt.length; r++) {
    const lane = view.laneAt[r];
    if (lane + 1 >= starts.length) continue;
    const i0 = lowerBound(src, a, starts[lane], starts[lane + 1]);
    const i1 = upperBound(src, b, i0, starts[lane + 1]);
    for (let i = i0; i < i1; i++) {
      l.xs[i] = (src[i] - cam.left) * cam.scale;
      maxSize = Math.max(maxSize, sizes[i]);
    }
    order.push(i0, i1);
  }
  // the most sub-rows the lanes hold (at the closest spacing); dodge in sub-rows, then space
  // the rows the events needed as far apart as the lanes allow (one spacing for all lanes,
  // so a column's height still compares between lanes)
  const rows = rowsFor(view.laneH, maxSize, spacing(view.laneH, maxSize, Infinity));
  for (let k = 0; k < order.length; k += 2) dodge(l.xs, order[k], order[k + 1], maxSize * 0.85, rows, 1, dy);
  let pairs = 0;
  for (let k = 0; k < order.length; k += 2) for (let i = order[k]; i < order[k + 1]; i++) pairs = Math.max(pairs, Math.abs(dy[i]));
  const step = spacing(view.laneH, maxSize, pairs);
  for (let k = 0; k < order.length; k += 2) for (let i = order[k]; i < order[k + 1]; i++) dy[i] *= step;
  l.draw.dy.version++;
  l.dodged = { left: a, right: b, scale: cam.scale, laneH: view.laneH };
}

export function segments(view: TimelineView, l: Layer, plot: { x: number; y: number; w: number; h: number }, laneTop: number, l0: number, l1: number): SegmentDraw | null {
  const route = l.data.spec.route;
  const seg = l.data.segments;
  if (!route || !seg || !route.count) return null;
  const src = view.xsrc(l);
  const lane = l.data.lane;
  const dy = l.draw.dy.data;
  const color = l.data.color;
  const solid = route.color ? (route.color === "theme" ? parseHex(view.theme.text) : parseHex(route.color)) : null;
  const coords = new Float32Array(Math.min(route.count, ROUTE_BUDGET) * 4);
  const colors = new Uint8Array(coords.length);
  const cam = view.camera;
  let n = 0;
  const right = cam.left + plot.w / cam.scale;
  for (let k = 0; k < route.count && n < ROUTE_BUDGET; k++) {
    const i = seg[2 * k];
    const j = seg[2 * k + 1];
    const xa = src[i];
    const xb = src[j];
    if ((xa < cam.left && xb < cam.left) || (xa > right && xb > right)) continue;
    const la = view.slot[lane[i]];
    const lb = view.slot[lane[j]];
    if (la < 0 || lb < 0) continue; // a folded lane
    if ((la < l0 && lb < l0) || (la > l1 && lb > l1)) continue;
    coords[4 * n] = plot.x + (xa - cam.left) * cam.scale;
    coords[4 * n + 1] = laneTop + (la + 0.5) * view.laneH + dy[i];
    coords[4 * n + 2] = plot.x + (xb - cam.left) * cam.scale;
    coords[4 * n + 3] = laneTop + (lb + 0.5) * view.laneH + dy[j];
    if (solid) {
      colors[4 * n] = solid[0];
      colors[4 * n + 1] = solid[1];
      colors[4 * n + 2] = solid[2];
    } else {
      colors[4 * n] = color[4 * i];
      colors[4 * n + 1] = color[4 * i + 1];
      colors[4 * n + 2] = color[4 * i + 2];
    }
    colors[4 * n + 3] = 140;
    n++;
  }
  return { count: n, coords, colors, width: route.width };
}
