// Rows and folding: which lane each row of the plot shows (folded lanes hide the lanes
// under them), the lanes in sight, and scrolling to a lane.

import type { SceneSpec } from "./types";
import { rowsOf, treeKey } from "./common";
import type { TimelineView } from "./view";

/** The names of the lanes at least half in sight, top to bottom. */
export function lanesInSight(view: TimelineView): string[] {
  const names = view.spec?.lanes.names ?? [];
  const h = view.plot().h;
  const r0 = Math.max(0, Math.round(view.scrollY / view.laneH));
  const r1 = Math.min(view.laneAt.length, Math.round((view.scrollY + h) / view.laneH));
  const out: string[] = [];
  for (let r = r0; r < r1; r++) out.push(String(names[view.laneAt[r]] ?? ""));
  return out;
}

/** Scroll the lane named `name` (its first, when names repeat over groups) to the top,
 * unfolding the lanes of the tree it is in; null: to the top. */
export function scrollToLane(view: TimelineView, name: string | null): void {
  if (!view.spec) return;
  const lane = name === null ? -1 : view.spec.lanes.names.findIndex((n) => String(n) === name);
  if (lane >= 0) {
    const tree = view.spec.lanes.tree;
    let opened = false;
    if (tree) {
      for (let k = 0; k < Math.min(lane, tree.size.length); k++) {
        if (k + tree.size[k] > lane && !view.open[k]) {
          view.open[k] = 1;
          opened = true;
        }
      }
    }
    if (opened) computeRows(view);
    view.scrollY = Math.max(0, view.slot[lane]) * view.laneH;
  } else view.scrollY = 0;
  clampScroll(view);
  view.layout();
  view.afterMove();
}

/** The header lanes of groups, or null. */
export function headerSet(view: TimelineView): Set<number> | null {
  const h = view.spec?.lanes.tree?.header;
  if (!h?.length) return null;
  if (view.headers?.list !== h) view.headers = { list: h, set: new Set(h) };
  return view.headers.set;
}

/** Where a tree lane's name starts (after its fold triangle), in px from the left. */
export function treeIndent(view: TimelineView, depth: number): number {
  return 6 + depth * Math.round(view.fs * 0.9) + Math.round(view.fs * 1.1);
}

/** The rows when a spec arrives: tree lanes open as the spec says, unless the same lanes
 * were shown before (a layer added, a note made): then they stay as the user left them. */
export function initRows(view: TimelineView, spec: SceneSpec): void {
  const tree = spec.lanes.tree;
  const names = spec.lanes.names;
  const key = treeKey(spec);
  const same = key !== "" && key === view.rowKey;
  if (!same) view.open = tree ? Uint8Array.from(tree.open, (o) => (o ? 1 : 0)) : new Uint8Array(0);
  view.rowKey = key;
  computeRows(view, names.length);
  if (!same) {
    if (tree) view.scrollY = 0;
    view.autoRows = view.laneAt.length;
  }
}

export function computeRows(view: TimelineView, n = view.spec?.lanes.names.length ?? 0): void {
  const tree = view.spec?.lanes.tree;
  const slot = new Int32Array(n).fill(-1);
  const at: number[] = [];
  for (let l = 0; l < n; ) {
    slot[l] = at.length;
    at.push(l);
    l += tree && l < tree.size.length && !view.open[l] ? tree.size[l] : 1;
  }
  view.laneAt = Int32Array.from(at);
  view.slot = slot;
  for (const l of view.layers) {
    l.draw.lane.data = rowsOf(l.data.lane, slot);
    l.draw.lane.version++;
    l.dodged = null;
  }
  for (const b of view.bars) b.setSlots(slot);
}

/** Fold or unfold a lane of the tree (`deep`: everything under it too). */
export function toggleLane(view: TimelineView, lane: number, deep = false): void {
  const tree = view.spec?.lanes.tree;
  if (!tree || lane < 0 || lane >= tree.size.length || tree.size[lane] < 2) return;
  const open = view.open[lane] ? 0 : 1;
  view.open[lane] = open;
  if (deep) for (let k = lane + 1; k < lane + tree.size[lane]; k++) view.open[k] = open;
  computeRows(view);
  view.hovered = null;
  clampScroll(view);
  view.layout();
  view.reportView();
}

/** Unfold every lane of the tree, or fold them all to their roots. */
export function expandAll(view: TimelineView, open: boolean): void {
  if (!view.spec?.lanes.tree) return;
  view.open.fill(open ? 1 : 0);
  computeRows(view);
  view.hovered = null;
  view.scrollY = 0;
  view.layout();
  view.reportView();
}

/** Whether a point is on the name of a lane that folds. */
export function foldableAt(view: TimelineView, p: { x: number; y: number }): boolean {
  const tree = view.spec?.lanes.tree;
  const plot = view.plot();
  if (!tree || p.x >= plot.x || p.y < plot.y || p.y > plot.y + plot.h) return false;
  const l = laneAtY(view, p.y);
  return l >= 0 && l < tree.size.length && tree.size[l] > 1;
}

/** The lane on the row at y (CSS px in the stage), or -1. */
export function laneAtY(view: TimelineView, y: number): number {
  const r = Math.floor((y - view.plot().y + view.scrollY) / view.laneH);
  return r >= 0 && r < view.laneAt.length ? view.laneAt[r] : -1;
}

export function clampScroll(view: TimelineView): void {
  const max = Math.max(0, view.laneAt.length * view.laneH - view.plot().h);
  view.scrollY = Math.max(0, Math.min(max, view.scrollY));
}
