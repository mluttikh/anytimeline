// Picking: the event, bar or sample under the pointer, and its tooltip.

import { KIND_MERGED } from "./bars";
import { lowerBound, upperBound } from "./scene";
import { fmtNumber } from "./time";
import type { EventsLayerSpec, IntervalsLayerSpec, ValuesLayerSpec } from "./types";
import { div, globalIndex, type Hit, HOVER_PX, STATE_TIP_LANES } from "./common";
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
  // the bins of layers sent as levels
  const bv = drawing.barView(view, plot);
  for (let li = view.layers.length - 1; li >= 0; li--) {
    const bins = view.layers[li].detail?.shown;
    if (!bins || !view.layers[li].data.spec.hover) continue;
    const i = bins.pick(px, py, at, view.laneAt, bv, HOVER_PX);
    if (i >= 0) return { layer: li, index: i, bin: true };
  }
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
  const o = view.hovered;
  const same = h && o && h.layer === o.layer && h.index === o.index && !!h.bar === !!o.bar && !!h.val === !!o.val && !!h.bin === !!o.bin;
  if (same) return;
  if (!h && !view.hovered) {
    if (view.tooltipKey) showTooltip(view); // a tooltip left over: hide it
    return;
  }
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
  const bins = h.bin ? view.layers[h.layer]?.detail?.shown : null;
  if (h.bin && !bins) {
    view.tooltip.classList.remove("atl-show");
    view.tooltipKey = "";
    return;
  }
  const key = bins ? `n${h.layer}:${h.index}:${bins.data.spec.lo.id}` : `${h.val ? "v" : h.bar ? "b" : "e"}${h.layer}:${h.index}`;
  // the same mark again (a states tooltip follows the pointer): what Python sent stays
  const again = key === view.tooltipKey;
  view.tooltipKey = key;
  if (!again) view.tooltipExtra = [];
  /** [key, value], and a class for the row. */
  const rows: [string, string, string?][] = [];
  if (view.layers.length + view.bars.length + view.values.length > 1) rows.push(["layer", spec.name]);
  if (h.bar && view.bars[h.layer].data.states) rows.push(...statesAt(view, h));
  /** Tooltip columns Python has for this hit, if any. */
  let extra: (() => Promise<string[][]>) | null = null;
  if (bins) {
    const d = bins.data;
    const i = h.index;
    const order = d.scale === "order";
    const time = (x: number) => (order ? (view.seq?.count ? view.seq.time(Math.round(x)) : NaN) : x);
    const name = spec.name;
    if (view.spec.lanes.show_names !== false) rows.push([view.spec.lanes.title || "lane", view.spec.lanes.names[d.lane[i]] ?? ""]);
    if (d.n[i] === 1) {
      if ((spec as EventsLayerSpec).has_time && !Number.isNaN(time(d.lo[i]))) rows.push(["time", view.axis.formatFull(time(d.lo[i]))]);
      if (order) rows.push(["order", `#${fmtNumber(d.lo[i] + 1)}`]);
      const top = d.top[i];
      if (spec.tooltip.length && view.callbacks.onTooltip) extra = () => view.callbacks.onTooltip!(name, top);
    } else {
      rows.push(["events", fmtNumber(d.n[i])]);
      if ((spec as EventsLayerSpec).has_time && !Number.isNaN(time(d.lo[i]))) {
        rows.push(["from", view.axis.formatFull(time(d.lo[i]))]);
        rows.push(["to", view.axis.formatFull(time(d.hi[i]))]);
      }
      if (order) rows.push(["order", `#${fmtNumber(d.lo[i] + 1)} – #${fmtNumber(d.hi[i] + 1)}`]);
      const levels = view.layers[h.layer].detail!.levels;
      const lane = d.lane[i];
      const range: [number, number] = [d.lo[i], d.hi[i]];
      if (levels.categories && view.callbacks.onBinTooltip) extra = () => view.callbacks.onBinTooltip!(name, d.scale, lane, range);
    }
  } else if (h.val) {
    const v = view.values[h.layer];
    const d = v.data;
    rows.push([view.spec.lanes.title || "lane", view.spec.lanes.names[v.laneOf(h.index)] ?? ""]);
    const series = v.seriesOf(h.index);
    if (series) rows.push([d.spec.series_title || "series", series]);
    rows.push(["time", view.axis.formatFull(d.time[h.index])]);
    rows.push(["value", fmtNumber(d.value[h.index], 6)]);
  } else if (h.bar && view.bars[h.layer].data.kind[h.index] === KIND_MERGED) {
    // short bars merged (a layer sent as levels)
    const d = view.bars[h.layer].data;
    const i = h.index;
    const order = view.xscale === "order";
    if (!d.states) rows.push([view.spec.lanes.title || "lane", view.spec.lanes.names[d.lane[i]] ?? ""]);
    rows.push(["bars", fmtNumber(d.n ? d.n[i] : 1)]);
    rows.push(["from", view.axis.formatFull(d.start[i])], ["to", view.axis.formatFull(d.end[i])]);
    if (order) rows.push(["order", `#${fmtNumber(d.rankStart[i] + 1)} – #${fmtNumber(d.rankEnd[i] + 1)}`]);
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
  if (!bins && !h.bar && !h.val && spec.tooltip.length && view.callbacks.onTooltip) {
    // an event's index as Python knows it (a window's events are some of the layer's)
    const index = globalIndex(view.layers[h.layer], h.index);
    extra = () => view.callbacks.onTooltip!(spec.name, index);
  } else if (h.val && spec.tooltip.length && view.callbacks.onTooltip) {
    const index = view.values[h.layer].globalIndex(h.index);
    extra = () => view.callbacks.onTooltip!(spec.name, index);
  } else if (h.bar && spec.tooltip.length && view.callbacks.onTooltip) {
    // a bar's index as Python knows it (a level's bars are some of the layer's)
    const index = view.bars[h.layer].globalIndex(h.index);
    if (index >= 0) extra = () => view.callbacks.onTooltip!(spec.name, index);
  }
  if (!again && extra) extra().then(render, () => {});
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

/** A tooltip of rows of name and value (a measure's), under key `key`. */
export function showRows(view: TimelineView, key: string, rows: string[][]): void {
  if (view.tooltipKey === key) return placeTooltip(view);
  view.tooltipKey = key;
  view.tooltip.replaceChildren(
    ...rows.map(([k, v]) => {
      const row = div("atl-tip-row");
      const kk = document.createElement("span");
      kk.className = "atl-tip-key";
      kk.textContent = k;
      const vv = document.createElement("span");
      vv.textContent = v;
      row.append(kk, vv);
      return row;
    }),
  );
  view.tooltip.classList.add("atl-show");
  placeTooltip(view);
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
