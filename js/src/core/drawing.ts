// The front canvas: the time axis, lane names and bands' text, labels, stems and their
// boxes, gaps, value scales, the hover ring and the zoom or selection box.

import type { BarView } from "./bars";
import { FLAG_SELECTED } from "./renderers/renderer";
import { clusterHidden, levelOffset, levelsFor, placeStems, type StemItem, type StemPlaced, type StemShape, wrapText } from "./stems";
import type { ValueView } from "./values";
import { lowerBound, parseHex, upperBound } from "./scene";
import { fmtNumber, TimeAxis } from "./time";
import { type Box, ellipsize, fontFamily, GAP_PX, isStems, LABEL_BUDGET, lowerBoundBy, MIN_BOX } from "./common";
import * as folding from "./folding";
import type { TimelineView } from "./view";

/** The other views' pointer: a dashed line across the lanes. */
export function drawLinkedCursor(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }): void {
  if (view.linkedCursor === null) return;
  const x = Math.round(plot.x + view.camera.toPx(view.xAt(view.linkedCursor))) + 0.5;
  if (x < plot.x || x > plot.x + plot.w) return;
  ctx.save();
  ctx.strokeStyle = view.theme.muted;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(x, plot.y);
  ctx.lineTo(x, plot.y + plot.h);
  ctx.stroke();
  ctx.restore();
}

export function drawAxis(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, ticks: ReturnType<TimeAxis["ticks"]>): void {
  ctx.save();
  ctx.fillStyle = view.theme.bg;
  ctx.fillRect(0, 0, view.width, view.axisH);
  ctx.strokeStyle = view.theme.muted;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(plot.x, view.axisH - 0.5);
  ctx.lineTo(plot.x + plot.w, view.axisH - 0.5);
  ctx.stroke();
  ctx.beginPath();
  ctx.rect(plot.x, 0, plot.w, view.axisH);
  ctx.clip();
  ctx.font = view.font(-1);
  ctx.fillStyle = view.theme.text;
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "center";
  ctx.beginPath();
  let lastEnd = -Infinity;
  for (const t of ticks.minor) {
    const x = plot.x + view.camera.toPx(t.x);
    ctx.moveTo(Math.round(x) + 0.5, view.axisH - 5);
    ctx.lineTo(Math.round(x) + 0.5, view.axisH);
    const w = ctx.measureText(t.label).width;
    // a label is shown whole: at the edges it moves inward, as long as it still covers its
    // tick; a tick off the plot gets no label
    if (x < plot.x || x > plot.x + plot.w) continue;
    const cx = Math.min(plot.x + plot.w - w / 2, Math.max(plot.x + w / 2, x));
    if (cx - w / 2 > lastEnd + 6) {
      ctx.fillText(t.label, cx, view.axisH - Math.round(view.fs * 0.75));
      lastEnd = cx + w / 2;
    }
  }
  ctx.strokeStyle = view.theme.muted;
  ctx.stroke();
  // context row: boundaries, and the unit of the left edge pinned there
  ctx.font = view.font(-1);
  ctx.fillStyle = view.theme.muted;
  ctx.textAlign = "left";
  const y = Math.round(view.fs * 1.25);
  let pinnedEnd = plot.x + 4 + ctx.measureText(ticks.pinned).width;
  const firstBoundary = ticks.context.length ? plot.x + view.camera.toPx(ticks.context[0].x) : Infinity;
  if (ticks.pinned && firstBoundary > pinnedEnd + 8) ctx.fillText(ticks.pinned, plot.x + 4, y);
  else pinnedEnd = -Infinity;
  for (const c of ticks.context) {
    const x = plot.x + view.camera.toPx(c.x);
    ctx.fillRect(Math.round(x), 4, 1, Math.round(view.fs * 1.17));
    ctx.fillText(c.label, x + 4, y);
  }
  ctx.restore();
}

export function drawLanes(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number, l0: number, l1: number): void {
  if (view.spec!.lanes.show_names === false) return;
  const names = view.spec!.lanes.names;
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, plot.y, plot.x, plot.h);
  ctx.clip();
  ctx.font = view.font(0);
  ctx.fillStyle = view.theme.text;
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  const tree = view.spec!.lanes.tree;
  const tri = Math.max(3, Math.round(view.fs * 0.32));
  for (let r = l0; r <= l1; r++) {
    const l = view.laneAt[r];
    const y = laneTop + (r + 0.5) * view.laneH;
    if (!tree || l >= tree.depth.length) {
      ctx.font = view.font(0);
      ctx.textAlign = "right";
      ctx.fillText(ellipsize(ctx, names[l], plot.x - 12), plot.x - 8, y);
      continue;
    }
    // a tree: names indented by depth, a triangle to fold the lanes under them
    const x = folding.treeIndent(view, tree.depth[l]);
    if (tree.size[l] > 1) {
      const cx = x - Math.round(view.fs * 0.6);
      ctx.beginPath();
      if (view.open[l]) {
        ctx.moveTo(cx - tri, y - tri * 0.6);
        ctx.lineTo(cx + tri, y - tri * 0.6);
        ctx.lineTo(cx, y + tri * 0.8);
      } else {
        ctx.moveTo(cx - tri * 0.6, y - tri);
        ctx.lineTo(cx + tri * 0.8, y);
        ctx.lineTo(cx - tri * 0.6, y + tri);
      }
      ctx.closePath();
      ctx.fillStyle = view.theme.muted;
      ctx.fill();
      ctx.fillStyle = view.theme.text;
    }
    ctx.textAlign = "left";
    const header = folding.headerSet(view)?.has(l) ?? false;
    ctx.font = header ? `600 ${view.fs}px ${fontFamily}` : view.font(0);
    const room = plot.x - 8 - x;
    let name = ellipsize(ctx, names[l], room);
    if (!view.open[l] && tree.size[l] > 1) {
      // folded: how many lanes it hides, when there is room
      const more = ` +${fmtNumber(tree.size[l] - 1)}`;
      if (ctx.measureText(name + more).width <= room && name === names[l]) {
        ctx.fillText(name, x, y);
        ctx.fillStyle = view.theme.muted;
        ctx.fillText(more, x + ctx.measureText(name).width, y);
        ctx.fillStyle = view.theme.text;
        continue;
      }
      name = ellipsize(ctx, names[l], room);
    }
    ctx.fillText(name, x, y);
  }
  ctx.restore();
  if (view.spec!.lanes.title) {
    ctx.save();
    ctx.font = view.font(-1);
    ctx.fillStyle = view.theme.muted;
    ctx.textAlign = "right";
    ctx.fillText(ellipsize(ctx, view.spec!.lanes.title, plot.x - 12), plot.x - 8, view.axisH - Math.round(view.fs * 0.75));
    ctx.restore();
  }
  // a scroll hint when lanes do not fit
  const total = view.laneAt.length * view.laneH;
  if (total > plot.h + 1) {
    const frac = plot.h / total;
    const top = plot.y + (view.scrollY / total) * plot.h;
    ctx.fillStyle = view.theme.grid;
    ctx.fillRect(view.width - 5, plot.y, 3, plot.h);
    ctx.fillStyle = view.theme.muted;
    ctx.fillRect(view.width - 5, top, 3, Math.max(12, frac * plot.h));
  }
}

export function drawLabels(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number): void {
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  ctx.font = view.font(-1);
  ctx.textBaseline = "middle";
  ctx.fillStyle = view.theme.text;
  ctx.strokeStyle = view.theme.bg;
  ctx.lineWidth = 3;
  ctx.lineJoin = "round";
  for (const l of view.layers) {
    if (isStems(l) && view.stemsFit.get(l) !== false) continue; // in boxes on stems
    const text = l.data.text;
    if (!text) continue;
    const vis = l.draw.visible;
    const order = Array.from(vis.subarray(0, l.draw.visibleCount));
    const imp = l.data.importance;
    if (imp) order.sort((a, b) => imp[b] - imp[a] || l.xs[a] - l.xs[b]);
    const taken: [number, number, number, number][] = [];
    for (const i of order) {
      const label = text[i];
      if (!label) continue;
      const x = plot.x + l.xs[i] + l.data.size[i] / 2 + 3;
      const y = laneTop + (view.slot[l.data.lane[i]] + 0.5) * view.laneH + l.draw.dy.data[i];
      const w = ctx.measureText(label).width;
      const half = view.fs / 2;
      const box: [number, number, number, number] = [x, y - half, x + w, y + half];
      if (taken.some((t) => box[0] < t[2] + 2 && box[2] + 2 > t[0] && box[1] < t[3] && box[3] > t[1])) continue;
      taken.push(box);
      ctx.strokeText(label, x, y);
      ctx.fillText(label, x, y);
      if (taken.length > LABEL_BUDGET) break;
    }
  }
  ctx.restore();
}

/**
 * The long gaps to show (Order scale): the longest first, their break marks at least
 * GAP_PX apart; a label (the time the gap skips) only where it fits in the axis' top row,
 * right of the pinned "from …" label and apart from the other labels.
 */
export function visibleGaps(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, pinned: string): { x: number; label: string | null }[] {
  if (!view.gaps.length || !view.axis) return [];
  const i0 = lowerBoundBy(view.gaps, view.camera.left);
  const candidates: { x: number; span: number }[] = [];
  for (let k = i0; k < view.gaps.length && view.gaps[k].at <= view.camera.right; k++) {
    const x = plot.x + view.camera.toPx(view.gaps[k].at);
    if (x > plot.x + 4 && x < plot.x + plot.w - 4) candidates.push({ x, span: view.gaps[k].span });
  }
  candidates.sort((a, b) => b.span - a.span);
  ctx.save();
  ctx.font = view.font(-1);
  const labelsFrom = pinned ? plot.x + 4 + ctx.measureText(pinned).width + 12 : plot.x;
  const shown: { x: number; label: string | null }[] = [];
  const labelled: [number, number][] = [];
  for (const c of candidates) {
    if (shown.some((g) => Math.abs(g.x - c.x) < GAP_PX)) continue;
    const text = view.axis.formatSpan(c.span);
    const half = ctx.measureText(text).width / 2 + 4;
    const fits = c.x - half >= labelsFrom && c.x + half <= plot.x + plot.w && !labelled.some(([a, b]) => c.x - half < b && c.x + half > a);
    if (fits) labelled.push([c.x - half, c.x + half]);
    shown.push({ x: c.x, label: fits ? text : null });
    if (shown.length >= 60) break;
  }
  ctx.restore();
  return shown;
}

/** Break marks on the axis line, and the gaps' labels in the axis' top row. */
export function drawGaps(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, gaps: { x: number; label: string | null }[]): void {
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, 0, plot.w, view.axisH + 4);
  ctx.clip();
  ctx.strokeStyle = view.theme.muted;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  const y = view.axisH - 1;
  for (const { x } of gaps) {
    ctx.moveTo(x - 4, y + 3);
    ctx.lineTo(x - 1, y - 3);
    ctx.moveTo(x + 1, y + 3);
    ctx.lineTo(x + 4, y - 3);
  }
  ctx.stroke();
  ctx.font = view.font(-1);
  ctx.textAlign = "center";
  ctx.fillStyle = view.theme.muted;
  const top = Math.round(view.fs * 1.25);
  for (const g of gaps) if (g.label) ctx.fillText(g.label, g.x, top);
  ctx.restore();
}

/** A zoom range (a band in the text colour) or a selection (dashed, in the selection colour). */
export function drawBox(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, b: Box): void {
  const x0 = Math.max(plot.x, Math.min(b.x0, b.x1));
  const x1 = Math.min(plot.x + plot.w, Math.max(b.x0, b.x1));
  ctx.save();
  if (b.kind === "select") {
    const y0 = Math.max(plot.y, Math.min(b.y0, b.y1));
    const y1 = Math.min(plot.y + plot.h, Math.max(b.y0, b.y1));
    ctx.strokeStyle = view.theme.select;
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(Math.round(x0) + 0.5, Math.round(y0) + 0.5, x1 - x0, y1 - y0);
  } else {
    const color = b.kind === "range-select" ? view.theme.select : view.theme.text;
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.08;
    ctx.fillRect(x0, 0, x1 - x0, plot.y + plot.h);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = color;
    ctx.beginPath();
    for (const x of [x0, x1]) {
      ctx.moveTo(Math.round(x) + 0.5, 0);
      ctx.lineTo(Math.round(x) + 0.5, plot.y + plot.h);
    }
    ctx.stroke();
    if (view.axis && x1 - x0 >= MIN_BOX) {
      // how long the range is
      const span = view.camera.fromPx(x1 - plot.x) - view.camera.fromPx(x0 - plot.x);
      const label = view.xscale === "order" ? `${fmtNumber(Math.round(span))} events` : view.axis.formatSpan(span);
      ctx.font = view.font(-1);
      ctx.textAlign = "center";
      ctx.fillStyle = view.theme.bg;
      const w = ctx.measureText(label).width + 8;
      const cx = (x0 + x1) / 2;
      ctx.fillRect(cx - w / 2, plot.y + 4, w, view.fs + 5);
      ctx.fillStyle = color;
      ctx.fillText(label, cx, plot.y + 4 + view.fs);
    }
  }
  ctx.restore();
}

/**
 * The text of stems layers in boxes above and below their lanes' lines, joined to the events
 * by stems in their colour; no stem passes behind a box. Laid out again when the zoom, lane
 * height or text changes, over three view widths so panning keeps the boxes where they are.
 * Events without room for a box are counted in badges ("+N") that zoom in when clicked.
 */
export function drawStems(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number, l0: number, l1: number): void {
  view.stemHits = [];
  view.badgeHits = [];
  const cam = view.camera;
  const bg = parseHex(view.theme.bg);
  const ink = parseHex(view.theme.text);
  view.layers.forEach((l, li) => {
    if (!isStems(l) || !l.data.text) return;
    const text = l.data.text;
    const spec = l.data.spec;
    const shape: StemShape = spec.stem_shape === "curved" ? "curved" : "straight";
    const lineH = Math.round(view.fs * 1.3);
    const padX = 9;
    const padY = 5;
    const gap = 7;
    let markR = 2;
    for (let i = 0; i < Math.min(l.data.count, 1000); i++) markR = Math.max(markR, l.data.size[i] / 2);
    // curved stems bend in the band between the line and the first level: give it room
    const start = markR + (shape === "curved" ? 26 : 12);
    const titleFont = `500 ${Math.max(6, view.fs - 1)}px ${fontFamily}`;
    const timeFont = `500 ${Math.max(6, view.fs - 2.5)}px ${fontFamily}`;
    const badgeFont = `600 ${Math.max(6, view.fs - 2)}px ${fontFamily}`;
    // the widest a box gets: label_width, or 16 × the text size; 0: no limit
    const maxW = spec.label_width === 0 ? Infinity : spec.label_width ?? 16 * view.fs;
    const src = view.xsrc(l);
    const key = [cam.scale, view.laneH, view.fs, view.xscale, shape, maxW, view.laneAt.length, l0, l1].join(":");
    let cache = view.stemCache.get(l);
    if (!cache || cache.key !== key || cam.left < cache.a || cam.right > cache.b) {
      const span = cam.span;
      const a = cam.left - span;
      const b = cam.right + span;
      const rows = new Map<number, { text: string; head: boolean }[]>();
      const perRow = new Map<number, StemItem[]>();
      const starts = l.data.laneStarts;
      const measure = (font: string) => (t: string) => {
        ctx.font = font;
        return ctx.measureText(t).width;
      };
      let most = 1;
      for (let r = Math.max(0, l0 - 1); r <= l1 + 1 && r < view.laneAt.length; r++) {
        const lane = view.laneAt[r];
        if (lane + 1 >= starts.length) continue;
        const i0 = lowerBound(src, a, starts[lane], starts[lane + 1]);
        const i1 = upperBound(src, b, i0, starts[lane + 1]);
        const items: StemItem[] = [];
        for (let i = i0; i < i1; i++) {
          if (!text[i]) continue;
          // a first line of two or more is the box's head (e.g. the time); the rest is the
          // title, wrapped to at most two lines within the box's width
          const parts = text[i].split("\n");
          const head = parts.length > 1 ? parts[0] : null;
          const body = (head === null ? parts : parts.slice(1)).join(" ");
          const inner = maxW - 2 * padX;
          const lines = [
            ...(head === null ? [] : wrapText(head, inner, 1, measure(timeFont)).map((t) => ({ text: t, head: true }))),
            ...wrapText(body, inner, 2, measure(titleFont)).map((t) => ({ text: t, head: false })),
          ];
          rows.set(i, lines);
          most = Math.max(most, lines.length);
          const w = Math.max(...lines.map((ln) => measure(ln.head ? timeFont : titleFont)(ln.text)));
          items.push({ index: i, x: (src[i] - cam.left) * cam.scale, w: Math.ceil(w) + 2 * padX, importance: l.data.importance?.[i] ?? 0 });
        }
        perRow.set(r, items);
      }
      // one height for all boxes of the layer, so levels are rows
      const boxH = most * lineH + 2 * padY;
      const levels = levelsFor(view.laneH, boxH, gap, start);
      const placed = new Map<number, StemPlaced[]>();
      const clusters = new Map<number, { n: number; a: number; b: number; row: number; px0: number; px1: number }>();
      const onLine: number[] = [];
      if (levels > 0) {
        // boxes may reach past the view (laid out wider than it), not past the data
        const ext = view.xscale === "order" ? [-0.5, (view.seq?.count ?? 1) - 0.5] : view.spec!.time.extent;
        const left = (Math.max(a, ext[0]) - cam.left) * cam.scale;
        const right = Math.max(left, (Math.min(b, ext[1]) - cam.left) * cam.scale);
        const space = { levels, gap, inset: 12, left, right, shape };
        let badgeIndex = -1;
        for (const [r, items] of perRow) {
          const first = placeStems(items, space);
          const boxed = new Set(first.map((p) => p.index));
          const hidden = items.filter((it) => !boxed.has(it.index));
          if (!hidden.length) {
            placed.set(r, first);
            continue;
          }
          // a badge per group of events without a box, placed after the boxes
          const badges: StemItem[] = [];
          const boxedXs = items.filter((it) => boxed.has(it.index)).map((it) => it.x);
          for (const c of clusterHidden(hidden, 48, boxedXs)) {
            const index = badgeIndex--;
            const label = `+${c.indices.length}`;
            const w = Math.ceil(measure(badgeFont)(label)) + 16;
            badges.push({ index, x: (c.x0 + c.x1) / 2, w, importance: -Infinity, badge: true });
            const xs = c.indices.map((i) => src[i]);
            clusters.set(index, { n: c.indices.length, a: Math.min(...xs), b: Math.max(...xs), row: r, px0: c.x0, px1: c.x1 });
          }
          const all = placeStems([...items, ...badges], space);
          placed.set(r, all);
          // badges that found no place go on the line, around their events
          const put = new Set(all.map((p) => p.index));
          for (const bdg of badges) if (!put.has(bdg.index)) onLine.push(bdg.index);
        }
      }
      view.stemsFit.set(l, levels > 0);
      cache = { key, left: cam.left, a, b, boxH, start, placed, rows, clusters, onLine };
      view.stemCache.set(l, cache);
    }
    if (!view.stemsFit.get(l)) return; // too little room: the text goes beside the marks
    const { boxH } = cache;
    const shift = (cache.left - cam.left) * cam.scale;
    ctx.save();
    ctx.beginPath();
    ctx.rect(plot.x, plot.y, plot.w, plot.h);
    ctx.clip();
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    const sf = l.draw.sf.data;
    const color = l.data.color;
    const muted = parseHex(view.theme.muted);
    const rgb = (i: number): number[] => (i < 0 ? muted : [color[4 * i], color[4 * i + 1], color[4 * i + 2]]);
    const css = (c: number[], alpha = 1) => `rgba(${c.map((v) => Math.round(v)).join(",")},${alpha})`;
    const mix = (x: number[], y: number[], t: number) => x.map((v, k) => v + (y[k] - v) * t);
    const shown: { p: StemPlaced; cy: number; x0: number; top: number }[] = [];
    for (const [r, boxes] of cache.placed) {
      if (r < l0 || r > l1) continue;
      const cy = laneTop + (r + 0.5) * view.laneH;
      for (const p of boxes) {
        const x0 = plot.x + p.x0 + shift;
        if (x0 > plot.x + plot.w || x0 + p.w < plot.x) continue;
        shown.push({ p, cy, x0, top: cy + levelOffset(p.level, boxH, gap, cache.start) - boxH / 2 });
      }
    }
    // the stems first, in their event's colour (a badge's dashed, to the middle of its
    // events); no stem passes behind a box (corridors)
    ctx.lineCap = "round";
    for (const { p, cy, top } of shown) {
      const up = p.level > 0;
      const badge = p.index < 0;
      const x = plot.x + p.x + shift;
      const cx = plot.x + p.cx + shift;
      const y0 = cy + (up ? -markR - 2 : markR + 2);
      const badgeH = lineH + 4;
      const y1 = badge ? top + boxH / 2 + (up ? badgeH / 2 : -badgeH / 2) : up ? top + boxH : top;
      ctx.strokeStyle = css(rgb(p.index), badge ? 0.7 : 0.85);
      ctx.lineWidth = badge ? 1 : 1.4;
      ctx.setLineDash(badge ? [2, 3] : []);
      ctx.beginPath();
      ctx.moveTo(x, y0);
      if (Math.abs(cx - x) > 0.5) {
        // an S-curve in the band next to the line, then straight up (or down) to the box
        const bend = cy + (up ? -cache.start + 4 : cache.start - 4);
        const mid = (y0 + bend) / 2;
        ctx.bezierCurveTo(x, mid, cx, mid, cx, bend);
      }
      ctx.lineTo(cx, y1);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    // a ring around each event that has a box, so the dot stands off the line
    ctx.strokeStyle = view.theme.bg;
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (const { p, cy } of shown) {
      if (p.index < 0) continue;
      const x = plot.x + p.x + shift;
      ctx.moveTo(x + markR + 1, cy);
      ctx.arc(x, cy, markR + 1, 0, Math.PI * 2);
    }
    ctx.stroke();
    // the boxes: tinted with their event's colour, a soft shadow, the time in that colour
    for (const { p, x0, top } of shown) {
      const i = p.index;
      if (i < 0) {
        // a badge: "+N" events without a box here; a click zooms in on them
        const c = cache.clusters.get(i);
        if (!c) continue;
        const badgeH = lineH + 4;
        const by = Math.round(top + boxH / 2 - badgeH / 2) + 0.5;
        const bx = Math.round(x0) + 0.5;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(bx, by, p.w, badgeH, badgeH / 2);
        else ctx.rect(bx, by, p.w, badgeH);
        ctx.fillStyle = css(mix(bg, muted, 0.12));
        ctx.fill();
        ctx.strokeStyle = css(mix(bg, muted, 0.5));
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.font = badgeFont;
        ctx.fillStyle = view.theme.muted;
        ctx.textAlign = "center";
        ctx.fillText(`+${c.n}`, x0 + p.w / 2, by + badgeH / 2);
        ctx.textAlign = "left";
        view.badgeHits.push({ x0, y0: by, x1: x0 + p.w, y1: by + badgeH, a: c.a, b: c.b, n: c.n });
        continue;
      }
      const c = rgb(i);
      const selected = (sf[4 * i + 1] & FLAG_SELECTED) !== 0;
      const hovered = view.hovered && !view.hovered.bar && !view.hovered.val && view.hovered.layer === li && view.hovered.index === i;
      const bx = Math.round(x0) + 0.5;
      const by = Math.round(top) + 0.5;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(bx, by, p.w, boxH, 6);
      else ctx.rect(bx, by, p.w, boxH);
      ctx.save();
      ctx.shadowColor = "rgba(15, 23, 42, 0.14)";
      ctx.shadowBlur = hovered ? 10 : 6;
      ctx.shadowOffsetY = 1.5;
      ctx.fillStyle = css(mix(bg, c, 0.09));
      ctx.fill();
      ctx.restore();
      ctx.strokeStyle = selected ? view.theme.select : hovered ? css(mix(c, ink, 0.3)) : css(mix(bg, c, 0.45));
      ctx.lineWidth = selected ? 2 : 1;
      ctx.stroke();
      (cache.rows.get(i) ?? []).forEach((line, k) => {
        ctx.font = line.head ? timeFont : titleFont;
        ctx.fillStyle = line.head ? css(mix(c, ink, 0.35)) : view.theme.text;
        ctx.fillText(line.text, x0 + padX, top + padY + lineH * (k + 0.5));
      });
      view.stemHits.push({ layer: li, index: i, x0, y0: top, x1: x0 + p.w, y1: top + boxH });
    }
    // badges on the line: a capsule around their events, "+N" at its right end
    for (const index of cache.onLine) {
      const c = cache.clusters.get(index);
      if (!c || c.row < l0 || c.row > l1) continue;
      const cy = laneTop + (c.row + 0.5) * view.laneH;
      ctx.font = badgeFont;
      const label = `+${c.n}`;
      const tw = ctx.measureText(label).width;
      const h = Math.max(2 * markR + 8, view.fs + 4);
      const x0 = plot.x + c.px0 + shift - markR - 5;
      const x1 = plot.x + c.px1 + shift + markR + 7 + tw + 6;
      if (x1 < plot.x || x0 > plot.x + plot.w) continue;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(Math.round(x0) + 0.5, Math.round(cy - h / 2) + 0.5, x1 - x0, h, h / 2);
      else ctx.rect(x0, cy - h / 2, x1 - x0, h);
      ctx.strokeStyle = css(mix(bg, muted, 0.6));
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = view.theme.muted;
      ctx.textAlign = "right";
      ctx.fillText(label, x1 - 6, cy + 0.5);
      ctx.textAlign = "left";
      view.badgeHits.push({ x0, y0: cy - h / 2, x1, y1: cy + h / 2, a: c.a, b: c.b, n: c.n });
    }
    ctx.restore();
  });
}

/** The badge under a point (CSS px in the stage), or null. */
export function badgeAt(view: TimelineView, p: { x: number; y: number }): { a: number; b: number; n: number } | null {
  for (const h of view.badgeHits) if (p.x >= h.x0 && p.x <= h.x1 && p.y >= h.y0 && p.y <= h.y1) return h;
  return null;
}

/** Zoom in on the events a badge stands for, far enough that they get boxes (about 110 px
 * of time per event, at most most of the plot). */
export function zoomToBadge(view: TimelineView, h: { a: number; b: number; n: number }): void {
  const plot = view.plot();
  const want = Math.min(plot.w * 0.7, Math.max(240, h.n * 110));
  const center = (h.a + h.b) / 2;
  const now = view.camera.span;
  const spanPx = (h.b - h.a) * view.camera.scale;
  const span = spanPx > 1 ? ((h.b - h.a) * plot.w) / want : now / 4;
  view.pushHistory();
  view.camera.fit(center - span / 2, center + span / 2, 0);
  view.afterMove();
}

/** What the values layers need of the frame. */
export function valueView(view: TimelineView, plot = view.plot()): ValueView {
  return {
    left: view.camera.left,
    scale: view.camera.scale,
    plot,
    laneTop: plot.y - view.scrollY,
    laneH: view.laneH,
    slot: view.slot,
    sequence: view.xscale === "order",
    seq: view.seq,
  };
}

/** Each values lane's high and low, small at the left of its band. */
export function drawValueScales(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, l0: number, l1: number): void {
  if (!view.values.length) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  ctx.font = view.font(-3);
  ctx.fillStyle = view.theme.muted;
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  const vv = valueView(view, plot);
  for (const v of view.values) v.drawScales(ctx, vv, l0, l1, (x) => fmtNumber(x, 3), view.fs * 3);
  ctx.restore();
}

/** What the bars need of the frame. */
export function barView(view: TimelineView, plot = view.plot()): BarView {
  return {
    left: view.camera.left,
    scale: view.camera.scale,
    plot,
    laneTop: plot.y - view.scrollY,
    laneH: view.laneH,
    maxBar: Math.max(16, Math.round(view.fs * 2.2)),
    sequence: view.xscale === "order",
    slot: view.slot,
  };
}

/** The arrows of dependencies, and text in the bars (when not too many are in view). */
export function drawBarText(view: TimelineView, ctx: CanvasRenderingContext2D, v: BarView, l0: number, l1: number, labels: boolean): void {
  if (!view.bars.length) return;
  const { plot } = v;
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  for (const b of view.bars) b.drawLinks(ctx, v, l0, l1, view.theme.muted);
  for (const b of view.bars) b.drawCritical(ctx, v, l0, l1, view.theme.text);
  ctx.font = view.font(-1);
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  const span = (t: number) => (view.axis ? view.axis.formatSpan(t) : fmtNumber(t));
  if (labels) for (const b of view.bars) b.drawLabels(ctx, v, view.theme.text, view.theme.bg, view.theme.muted, span);
  ctx.restore();
}

export function drawHover(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number): void {
  const h = view.hovered;
  if (!h) return;
  if (h.val) {
    const v = view.values[h.layer];
    if (!v) return;
    const p = v.position(h.index, valueView(view, plot));
    ctx.save();
    ctx.beginPath();
    ctx.rect(plot.x, plot.y, plot.w, plot.h);
    ctx.clip();
    ctx.strokeStyle = view.theme.muted;
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(Math.round(p.x) + 0.5, p.y - view.laneH / 2);
    ctx.lineTo(Math.round(p.x) + 0.5, p.y + view.laneH / 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = p.color;
    ctx.strokeStyle = view.theme.bg;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
    return;
  }
  if (h.bar) {
    const b = view.bars[h.layer];
    if (!b) return;
    const box = b.box(h.index, barView(view, plot));
    ctx.save();
    ctx.beginPath();
    ctx.rect(plot.x, plot.y, plot.w, plot.h);
    ctx.clip();
    ctx.strokeStyle = view.theme.text;
    ctx.lineWidth = 1.5;
    if (box.milestone) {
      const r = box.h * 0.62 + 3;
      ctx.beginPath();
      ctx.moveTo(box.x0, box.cy - r);
      ctx.lineTo(box.x0 + r, box.cy);
      ctx.lineTo(box.x0, box.cy + r);
      ctx.lineTo(box.x0 - r, box.cy);
      ctx.closePath();
      ctx.stroke();
    } else {
      const a = Math.max(box.x0, plot.x - 4);
      const e = Math.min(box.x1, plot.x + plot.w + 4);
      ctx.strokeRect(a - 2, box.cy - box.h / 2 - 2, Math.max(1, e - a) + 4, box.h + 4);
    }
    ctx.restore();
    return;
  }
  const l = view.layers[h.layer];
  if (!l) return;
  const x = plot.x + (view.xsrc(l)[h.index] - view.camera.left) * view.camera.scale;
  const y = laneTop + (view.slot[l.data.lane[h.index]] + 0.5) * view.laneH + l.draw.dy.data[h.index];
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  ctx.strokeStyle = view.theme.text;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(x, y, l.data.size[h.index] / 2 + 3, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

/** The selected events of layers sent as levels, over their bins (rings in the selection
 * colour); once their events are drawn, those show the selection. */
export function drawMarked(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number, l0: number, l1: number): void {
  const order = view.xscale === "order";
  const r = Math.max(2.5, Math.min(5, view.laneH * 0.22));
  let started = false;
  for (const l of view.layers) {
    const at = view.marked[l.data.spec.name];
    if (!at?.length || !l.detail?.shown) continue;
    if (!started) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(plot.x, plot.y, plot.w, plot.h);
      ctx.clip();
      ctx.strokeStyle = view.theme.select;
      ctx.lineWidth = 2;
      ctx.beginPath();
      started = true;
    }
    for (let i = 0; i + 2 < at.length; i += 3) {
      const row = view.slot[at[i + 2]];
      if (row < l0 || row > l1 || row < 0) continue;
      const x = plot.x + ((order ? at[i + 1] : at[i]) - view.camera.left) * view.camera.scale;
      if (x < plot.x - r || x > plot.x + plot.w + r) continue;
      const y = laneTop + (row + 0.5) * view.laneH;
      ctx.moveTo(x + r, y);
      ctx.arc(x, y, r, 0, Math.PI * 2);
    }
  }
  if (!started) return;
  ctx.stroke();
  ctx.restore();
}

/** The mark found or stepped to (`view.focus`): a ring in the accent colour (a bar: a frame
 * around it) and, beside it, its text and time. */
export function drawFocus(view: TimelineView, ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number): void {
  const f = view.focus;
  if (!f || !view.axis) return;
  const row = view.slot[f.lane];
  if (row === undefined || row < 0) return;
  const order = view.xscale === "order";
  const c = view.camera;
  const x = plot.x + ((order ? f.r : f.x) - c.left) * c.scale;
  const x2 = plot.x + ((order ? f.r2 : f.x2) - c.left) * c.scale;
  const y = laneTop + (row + 0.5) * view.laneH;
  if (y < plot.y || y > plot.y + plot.h || x2 < plot.x - 12 || x > plot.x + plot.w + 12) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  ctx.strokeStyle = view.theme.accent;
  ctx.lineWidth = 2;
  ctx.beginPath();
  const r = Math.max(6, Math.min(10, view.laneH * 0.35));
  if (x2 - x > 2 * r) ctx.roundRect(x - 3, y - r, x2 - x + 6, 2 * r, 3);
  else ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.stroke();
  // its text and time, in a box beside it (left of it near the right edge)
  const time = order ? `#${Math.round(f.r) + 1}` : view.axis.formatFull(f.x);
  const label = f.text ? `${f.text} · ${time}` : time;
  ctx.font = view.font(-1);
  const w = ctx.measureText(label).width + 10;
  const h = view.fs + 6;
  let lx = x + r + 6;
  if (lx + w > plot.x + plot.w) lx = x - r - 6 - w;
  const ly = Math.max(plot.y + 2, Math.min(plot.y + plot.h - h - 2, y - r - h - 2));
  ctx.fillStyle = view.theme.bg;
  ctx.globalAlpha = 0.92;
  ctx.fillRect(lx, ly, w, h);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = view.theme.accent;
  ctx.lineWidth = 1;
  ctx.strokeRect(lx + 0.5, ly + 0.5, w - 1, h - 1);
  ctx.fillStyle = view.theme.text;
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.fillText(label, lx + 5, ly + h / 2);
  ctx.restore();
}
