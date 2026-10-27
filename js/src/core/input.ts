// Input: the pointer (pan, zoom and select drags, clicks, the wheel, taps) and keys.

import { type Box, type BoxKind, boxMode, clickMode, DOUBLE_CLICK_MS, type DragMode, globalIndex, MIN_BOX, type SelectMode } from "./common";
import * as folding from "./folding";
import * as drawing from "./drawing";
import * as picking from "./picking";
import type { TimelineView } from "./view";

export function cancelDrag(view: TimelineView): void {
  view.drag = null;
  view.box = null;
  view.stage.classList.remove("atl-panning");
  view.requestRender();
}

export function bindInput(view: TimelineView): void {
  const stage = view.stage;
  const local = (e: MouseEvent) => {
    const r = stage.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  stage.addEventListener("wheel", (e) => {
    const active = view.root.contains(document.activeElement) || view.isFullscreen() || view.root.matches(":focus-within");
    if (!active && !e.ctrlKey && !e.metaKey) {
      view.flashNotice("Click the plot, then scroll to zoom");
      return;
    }
    e.preventDefault();
    const now = performance.now();
    if (now - view.lastWheel > 500) view.pushHistory();
    view.lastWheel = now;
    const p = local(e);
    const plot = view.plot();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    if (e.shiftKey) {
      view.scrollY += (e.deltaY || e.deltaX) * unit;
      folding.clampScroll(view);
    } else {
      if (e.deltaY) view.camera.zoomAt(Math.max(0, Math.min(plot.w, p.x - plot.x)), Math.exp(-e.deltaY * unit * 0.0022));
      if (e.deltaX) view.camera.pan(-e.deltaX * unit);
    }
    view.afterMove();
  }, { passive: false });

  stage.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    view.root.focus({ preventScroll: true });
    const p = local(e);
    const plot = view.plot();
    stage.setPointerCapture(e.pointerId);
    let mode: DragMode;
    if (view.spaceDown) mode = "pan";
    else if (p.y < plot.y && p.x >= plot.x) mode = "axis";
    else if (view.tool === "zoom") mode = "zoom";
    else if (view.tool === "select") mode = "select";
    else mode = e.shiftKey ? "zoom" : "pan";
    view.drag = { x: p.x, y: p.y, left: view.camera.left, scrollY: view.scrollY, mode, moved: false };
  });

  stage.addEventListener("pointermove", (e) => {
    const p = local(e);
    view.pointer = p;
    const d = view.drag;
    if (d) {
      const dx = p.x - d.x;
      const dy = p.y - d.y;
      if (!d.moved && Math.abs(dx) + Math.abs(dy) > 4) {
        d.moved = true;
        if (d.mode === "pan") {
          view.pushHistory();
          stage.classList.add("atl-panning");
        }
        picking.setHovered(view, null);
      }
      if (!d.moved) return;
      if (d.mode === "pan") {
        view.camera.left = d.left;
        view.camera.pan(dx);
        view.scrollY = d.scrollY - dy;
        folding.clampScroll(view);
        view.afterMove();
      } else {
        view.box = { x0: d.x, y0: d.y, x1: p.x, y1: p.y, kind: boxKind(view, d.mode) };
        view.requestRender();
      }
      return;
    }
    if (view.hoverEnabled) picking.setHovered(view, picking.pick(view, p.x, p.y));
    const plotNow = view.plot();
    view.shareCursor(p.x >= plotNow.x && p.x <= plotNow.x + plotNow.w ? p.x : null);
    view.stage.classList.toggle("atl-foldable", folding.foldableAt(view, p) || !!drawing.badgeAt(view, p));
    // a states tooltip shows the lanes at the pointer's time: it changes with the pointer
    if (view.hovered?.bar && view.bars[view.hovered.layer]?.data.states) picking.showTooltip(view);
    else if (view.hovered) picking.placeTooltip(view);
  });

  const end = (e: PointerEvent) => {
    const d = view.drag;
    const box = view.box;
    view.drag = null;
    view.box = null;
    stage.classList.remove("atl-panning");
    if (!d) return;
    const p = local(e);
    const wide = box && Math.abs(box.x1 - box.x0) >= MIN_BOX;
    if (d.moved && box && d.mode !== "pan") {
      if (box.kind === "select" || box.kind === "range-select") {
        if (wide || box.kind === "select") selectBox(view, box, boxMode(e));
      } else if (wide) {
        zoomToBox(view, box);
      }
      view.requestRender();
      return;
    }
    if (d.moved) return;
    click(view, p, e, d.mode);
  };
  stage.addEventListener("pointerup", end);
  stage.addEventListener("pointercancel", () => cancelDrag(view));
  stage.addEventListener("pointerleave", () => {
    view.pointer = null;
    view.shareCursor(null);
    if (!view.drag) picking.setHovered(view, null);
  });

  view.root.addEventListener("keydown", (e) => key(view, e));
  view.root.addEventListener("keyup", (e) => {
    if (e.key === " ") {
      view.spaceDown = false;
      view.root.classList.remove("atl-space");
    }
  });
  view.root.addEventListener("blur", () => {
    view.spaceDown = false;
    view.root.classList.remove("atl-space");
  });
  document.addEventListener("fullscreenchange", view.onFullscreenChange);
}

export function boxKind(view: TimelineView, mode: DragMode): BoxKind {
  if (mode === "select") return "select";
  if (mode === "axis") return view.tool === "select" ? "range-select" : "range";
  return "range";
}

/** A click (a press that did not move) with the drag mode it started in. */
export function click(view: TimelineView, p: { x: number; y: number }, e: MouseEvent, mode: DragMode): void {
  const plot = view.plot();
  const inPlot = p.x >= plot.x && p.x <= plot.x + plot.w && p.y >= plot.y && p.y <= plot.y + plot.h;
  if (mode !== "axis" && p.x < plot.x && p.y >= plot.y && p.y <= plot.y + plot.h) {
    // a lane's name: a click folds or unfolds it, a double-click shows all of it
    const lane = folding.laneAtY(view, p.y);
    const now = performance.now();
    if (now - view.lastNameTap.at < DOUBLE_CLICK_MS && lane === view.lastNameTap.lane) {
      view.lastNameTap = { at: 0, lane: -1 };
      folding.toggleLane(view, lane, e.altKey); // undo the first click's fold
      view.zoomToLane(lane);
    } else {
      view.lastNameTap = { at: now, lane };
      folding.toggleLane(view, lane, e.altKey);
    }
    return;
  }
  if (mode === "axis" || !inPlot) return;
  const badge = drawing.badgeAt(view, p);
  if (badge) {
    drawing.zoomToBadge(view, badge);
    return;
  }
  const selecting = view.selectionMode !== "none";
  const hit = picking.pick(view, p.x, p.y);
  // a bin of a layer sent as levels: a bin of one event is that event; selecting another
  // selects the events in it
  const bins = hit?.bin ? view.layers[hit.layer]?.detail?.shown : null;
  const select = (m: SelectMode) => {
    const spec = hit && selecting ? picking.specOf(view, hit) : undefined;
    if (!hit || !spec?.select) return;
    if (bins) {
      const d = bins.data;
      const i = hit.index;
      if (d.n[i] > 1) view.callbacks.onGesture?.({ kind: "box", x: [d.lo[i], d.hi[i]], lanes: [d.lane[i], d.lane[i]], shown: [d.lane[i]], xscale: d.scale, mode: m === "toggle" ? "add" : m, layer: spec.name });
      else view.callbacks.onGesture?.({ kind: "click", layer: spec.name, index: d.top[i], mode: m });
      return;
    }
    if (hit.bar && view.bars[hit.layer].globalIndex(hit.index) < 0) {
      // short bars merged: selecting selects the bars in it
      const b = view.bars[hit.layer];
      const [lo, hi] = b.ends(view.xscale === "order");
      const i = hit.index;
      const lane = b.data.lane[i];
      view.callbacks.onGesture?.({ kind: "box", x: [lo[i], hi[i]], lanes: [lane, lane], shown: [lane], xscale: view.xscale, mode: m === "toggle" ? "add" : m, layer: spec.name });
      return;
    }
    const index = hit.bar ? view.bars[hit.layer].globalIndex(hit.index) : hit.val ? hit.index : globalIndex(view.layers[hit.layer], hit.index);
    view.callbacks.onGesture?.({ kind: "click", layer: spec.name, index, mode: m });
  };
  if (view.tool === "zoom" && mode === "zoom") {
    view.pushHistory();
    view.camera.zoomAt(p.x - plot.x, e.altKey ? 0.5 : 2);
    view.afterMove();
    return;
  }
  if (view.tool === "select") {
    select(clickMode(e)); // a miss changes nothing
    return;
  }
  // Pan: a plain click does nothing (it may be a click to focus, or a stray one); modifier
  // clicks add and remove; a double-click shows the whole timeline
  if (e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) {
    select(clickMode(e));
    return;
  }
  const now = performance.now();
  if (now - view.lastTap < DOUBLE_CLICK_MS) {
    view.lastTap = 0;
    view.resetView();
    return;
  }
  view.lastTap = now;
}

export function zoomToBox(view: TimelineView, b: Box): void {
  const plot = view.plot();
  const xa = view.camera.fromPx(Math.min(b.x0, b.x1) - plot.x);
  const xb = view.camera.fromPx(Math.max(b.x0, b.x1) - plot.x);
  view.pushHistory();
  view.camera.fit(xa, xb, 0);
  view.afterMove();
}

export function key(view: TimelineView, e: KeyboardEvent): void {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (view.helpEl && e.key !== "?" && e.key !== "Escape") return;
  const plot = view.plot();
  const move = (fn: () => void) => {
    view.pushHistory();
    fn();
  };
  let handled = true;
  switch (e.key) {
    case "p":
      view.setTool("pan", true);
      break;
    case "z":
      view.setTool("zoom", true);
      break;
    case "s":
      view.setTool("select", true);
      break;
    case "t":
    case "T":
      view.setXScale(view.xscale === "time" ? "order" : "time", true);
      break;
    case "[":
    case "]":
      if (!view.spec?.lanes.tree) return;
      folding.expandAll(view, e.key === "]");
      break;
    case "0":
    case "Home":
      view.resetView();
      break;
    case "Backspace":
      view.previousView();
      break;
    case "+":
    case "=":
      move(() => view.camera.zoomAt(plot.w / 2, 2));
      break;
    case "-":
    case "_":
      move(() => view.camera.zoomAt(plot.w / 2, 0.5));
      break;
    case "ArrowLeft":
      view.camera.pan(plot.w * 0.2);
      break;
    case "ArrowRight":
      view.camera.pan(-plot.w * 0.2);
      break;
    case "ArrowUp":
      view.scrollY -= view.laneH * 3;
      break;
    case "ArrowDown":
      view.scrollY += view.laneH * 3;
      break;
    case "d":
      if (!view.layers.some((l) => l.data.spec.overlap === "dodge")) return;
      view.setDodge(!view.dodgeOn);
      view.callbacks.onDodge?.(view.dodgeOn);
      break;
    case "l":
      if (view.legendEl) view.toggleLegend();
      break;
    case "f":
      view.toggleFullscreen();
      break;
    case "?":
      view.toggleHelp();
      break;
    case " ":
      view.spaceDown = true;
      view.root.classList.add("atl-space");
      break;
    case "Escape":
      if (view.helpEl) view.toggleHelp();
      else if (view.drag) cancelDrag(view);
      else if (Object.values(view.marks).some((m) => m.length)) view.callbacks.onGesture?.({ kind: "clear" });
      else handled = false;
      break;
    default:
      handled = false;
  }
  if (handled) {
    // keep the key from the notebook (JupyterLab's command-mode shortcuts) and the page
    e.preventDefault();
    e.stopPropagation();
    folding.clampScroll(view);
    view.afterMove();
  }
}

export function selectBox(view: TimelineView, b: Box, mode: SelectMode): void {
  const plot = view.plot();
  const laneTop = plot.y - view.scrollY;
  const xa = view.camera.fromPx(Math.min(b.x0, b.x1) - plot.x);
  const xb = view.camera.fromPx(Math.max(b.x0, b.x1) - plot.x);
  const rows = view.laneAt.length;
  let ra = 0;
  let rb = rows - 1;
  if (b.kind === "select") {
    ra = Math.floor((Math.max(plot.y, Math.min(b.y0, b.y1)) - laneTop) / view.laneH);
    rb = Math.floor((Math.min(plot.y + plot.h, Math.max(b.y0, b.y1)) - laneTop) / view.laneH);
  }
  ra = Math.max(0, Math.min(rows - 1, ra));
  rb = Math.max(0, Math.min(rows - 1, rb));
  const lanes: [number, number] = [view.laneAt[ra] ?? 0, view.laneAt[rb] ?? 0];
  // with folded lanes, the rows in the box are not one range of lanes: list them
  const folded = view.laneAt.length < (view.spec?.lanes.names.length ?? 0);
  const shown = folded ? Array.from(view.laneAt.subarray(ra, rb + 1)) : undefined;
  view.callbacks.onGesture?.({ kind: "box", x: [xa, xb], lanes, shown, xscale: view.xscale, mode });
}
