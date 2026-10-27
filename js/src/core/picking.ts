// Picking: the event, bar or sample under the pointer, and its tooltip.

import { lowerBound, upperBound } from "./scene";
import { fmtNumber } from "./time";
import type { EventsLayerSpec, IntervalsLayerSpec, ValuesLayerSpec } from "./types";
import { div, type Hit, HOVER_PX, STATE_TIP_LANES } from "./common";
import * as drawing from "./drawing";
import type { TimelineView } from "./view";

/** The event nearest to a point (CSS px in the stage), within HOVER_PX. */
export function pick(view: TimelineView, px: number, py: number): Hit | null {
  if (!view.spec) return null;
  const plot = view.plot();
  if (px < plot.x || px > plot.x + plot.w || py < plot.y || py > plot.y + plot.h) return null;
  // a story's box stands for its event
  for (let k = view.stemHits.length - 1; k >= 0; k--) {
    const b = view.stemHits[k];
    if (px >= b.x0 && px <= b.x1 && py >= b.y0 && py <= b.y1) return { layer: b.layer, index: b.index };
  }
  const laneTop = plot.y - view.scrollY;
  const at = Math.floor((py - laneTop) / view.laneH);
  let best: { layer: number; index: number } | null = null;
  let bestD = HOVER_PX * HOVER_PX;
  view.layers.forEach((l, li) => {
    if (!l.data.spec.hover && !l.data.spec.select) return;
    const src = view.xsrc(l);
    const starts = l.data.laneStarts;
    const reach = (HOVER_PX + 12) / view.camera.scale;
    const x = view.camera.fromPx(px - plot.x);
    for (let r = Math.max(0, at - 1); r <= at + 1 && r < view.laneAt.length; r++) {
      const lane = view.laneAt[r];
      if (lane + 1 >= starts.length) continue;
      const i0 = lowerBound(src, x - reach, starts[lane], starts[lane + 1]);
      const i1 = upperBound(src, x + reach, i0, starts[lane + 1]);
      for (let i = i0; i < i1; i++) {
        const ex = plot.x + (src[i] - view.camera.left) * view.camera.scale;
        const ey = laneTop + (r + 0.5) * view.laneH + l.draw.dy.data[i];
        const radius = l.data.size[i] / 2;
        const d = Math.max(0, Math.hypot(ex - px, ey - py) - radius);
        if (d * d <= bestD) {
          bestD = d * d;
          best = { layer: li, index: i };
        }
      }
    }
  });
  if (best) return best;
  // samples of values layers near the pointer: a line is a small target, a bar (a state
  // filling its lane) a large one, so the line goes first
  const vv = drawing.valueView(view, plot);
  for (let k = view.values.length - 1; k >= 0; k--) {
    const layer = view.values[k];
    if (!layer.data.spec.hover) continue;
    const i = layer.pick(px, py, at, view.laneAt, vv, HOVER_PX);
    if (i >= 0) return { layer: k, index: i, val: true };
  }
  // bars, top layer first
  const v = drawing.barView(view, plot);
  for (let k = view.bars.length - 1; k >= 0; k--) {
    const b = view.bars[k];
    if (!b.data.spec.hover && !b.data.spec.select) continue;
    const i = b.pick(px, py, at, view.laneAt, v);
    if (i >= 0) return { layer: k, index: i, bar: true };
  }
  return null;
}

/** The spec of the layer a hit is in. */
export function specOf(view: TimelineView, h: Hit): EventsLayerSpec | IntervalsLayerSpec | ValuesLayerSpec | undefined {
  if (h.val) return view.values[h.layer]?.data.spec;
  return h.bar ? view.bars[h.layer]?.data.spec : view.layers[h.layer]?.data.spec;
}

export function setHovered(view: TimelineView, h: Hit | null): void {
  const same = h && view.hovered && h.layer === view.hovered.layer && h.index === view.hovered.index && !!h.bar === !!view.hovered.bar && !!h.val === !!view.hovered.val;
  if (same || (!h && !view.hovered)) return;
  view.hovered = h;
  view.requestRender();
  showTooltip(view);
}

export function showTooltip(view: TimelineView): void {
  const h = view.hovered;
  const spec = h ? specOf(view, h) : undefined;
  if (!h || !spec || !view.pointer || !view.axis || !view.spec || !spec.hover) {
    view.tooltip.classList.remove("atl-show");
    view.tooltipKey = "";
    return;
  }
  const key = `${h.val ? "v" : h.bar ? "b" : "e"}${h.layer}:${h.index}`;
  // the same mark again (a states tooltip follows the pointer): what Python sent stays
  const again = key === view.tooltipKey;
  view.tooltipKey = key;
  if (!again) view.tooltipExtra = [];
  /** [key, value], and a class for the row. */
  const rows: [string, string, string?][] = [];
  if (view.layers.length + view.bars.length + view.values.length > 1) rows.push(["layer", spec.name]);
  if (h.bar && view.bars[h.layer].data.states) rows.push(...statesAt(view, h));
  if (h.val) {
    const v = view.values[h.layer];
    const d = v.data;
    rows.push([view.spec.lanes.title || "lane", view.spec.lanes.names[v.laneOf(h.index)] ?? ""]);
    const series = v.seriesOf(h.index);
    if (series) rows.push([d.spec.series_title || "series", series]);
    rows.push(["time", view.axis.formatFull(d.time[h.index])]);
    rows.push(["value", fmtNumber(d.value[h.index], 6)]);
  } else if (h.bar) {
    const d = view.bars[h.layer].data;
    const i = h.index;
    // (a states layer's rows above name the lanes)
    if (!d.states) rows.push([view.spec.lanes.title || "lane", view.spec.lanes.names[d.lane[i]] ?? ""]);
    if (d.kind[i] === 1) rows.push(["at", view.axis.formatFull(d.start[i])], ["", "milestone"]);
    else {
      rows.push(["start", view.axis.formatFull(d.start[i])]);
      rows.push(["end", d.kind[i] === 2 ? "open (not ended)" : view.axis.formatFull(d.end[i])]);
      if (d.kind[i] !== 2) rows.push(["duration", view.axis.formatSpan(d.end[i] - d.start[i])]);
    }
    if (d.progress && d.progress[i] >= 0) rows.push(["progress", `${Math.round(d.progress[i] * 100)}%`]);
    if (d.text?.[i] && d.text[i] !== d.states?.[i]) rows.push(["text", d.text[i]]);
  } else {
    const l = view.layers[h.layer];
    if (view.spec.lanes.show_names !== false) rows.push([view.spec.lanes.title || "lane", view.spec.lanes.names[l.data.lane[h.index]] ?? ""]);
    if (l.data.spec.has_time) rows.push(["time", view.axis.formatFull(l.data.time[h.index])]);
    rows.push(["order", `#${fmtNumber(l.data.rank[h.index] + 1)}`]);
    if (l.data.text?.[h.index]) rows.push(["text", l.data.text[h.index]]);
  }
  const render = (extra: string[][]) => {
    if (view.tooltipKey !== key) return;
    view.tooltipExtra = extra;
    view.tooltip.replaceChildren(
      ...[...rows, ...extra].map(([k, v, cls]) => {
        const row = div(cls ? `atl-tip-row ${cls}` : "atl-tip-row");
        const kk = document.createElement("span");
        kk.className = "atl-tip-key";
        kk.textContent = k;
        const vv = document.createElement("span");
        vv.textContent = v;
        row.append(kk, vv);
        return row;
      }),
    );
    placeTooltip(view);
  };
  render(view.tooltipExtra);
  view.tooltip.classList.add("atl-show");
  if (!again && spec.tooltip.length && view.callbacks.onTooltip) {
    view.callbacks.onTooltip(spec.name, h.index).then(render, () => {});
  }
}

/** A states layer's tooltip: the time at the pointer, and every lane's state then (the
 * hovered lane's marked), so lanes compare at one moment; at most STATE_TIP_LANES lanes,
 * those around the hovered one. Under them, the hovered state's own rows. */
export function statesAt(view: TimelineView, h: Hit): [string, string, string?][] {
  const b = view.bars[h.layer];
  const d = b.data;
  const sequence = view.xscale === "order";
  const x = view.pointer ? view.camera.fromPx(view.pointer.x - view.plot().x) : d.start[h.index];
  const rows: [string, string, string?][] = [];
  if (!sequence && view.axis) rows.push(["time", view.axis.formatFull(x)]);
  const lanes = [...view.laneAt].filter((l) => l + 1 < d.laneStarts.length && d.laneStarts[l + 1] > d.laneStarts[l]);
  const here = lanes.indexOf(d.lane[h.index]);
  const from = Math.max(0, Math.min(here - (STATE_TIP_LANES >> 1), lanes.length - STATE_TIP_LANES));
  const shown = lanes.slice(from, from + STATE_TIP_LANES);
  if (from > 0) rows.push(["", `… ${fmtNumber(from)} lanes above`]);
  for (const l of shown) {
    const i = b.at(x, l, sequence);
    const state = i >= 0 ? d.states![i] : "–";
    rows.push([view.spec!.lanes.names[l] ?? "", state, l === d.lane[h.index] ? "atl-tip-here" : undefined]);
  }
  const below = lanes.length - from - shown.length;
  if (below > 0) rows.push(["", `… ${fmtNumber(below)} lanes below`]);
  rows.push(["", "", "atl-tip-gap"]);
  return rows;
}

export function placeTooltip(view: TimelineView): void {
  if (!view.pointer) return;
  const tw = view.tooltip.offsetWidth;
  const th = view.tooltip.offsetHeight;
  let x = view.pointer.x + 14;
  let y = view.pointer.y + 14;
  if (x + tw > view.width - 4) x = view.pointer.x - tw - 14;
  if (y + th > view.height - 4) y = view.pointer.y - th - 14;
  view.tooltip.style.transform = `translate(${Math.max(4, x)}px, ${Math.max(4, y)}px)`;
}
