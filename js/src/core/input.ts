// Input: the pointer (pan, zoom and select drags, clicks, the wheel, taps) and keys.

import { type Box, type BoxKind, boxMode, clickMode, DOUBLE_CLICK_MS, type DragMode, globalIndex, MIN_BOX, type SelectMode } from "./common";
import * as folding from "./folding";
import * as drawing from "./drawing";
import * as picking from "./picking";
import { askText, markOf } from "./notes";
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

  // touch waits for a tap (as web maps do): before it, a finger scrolls the page; after it
  // (until the plot loses focus), one finger pans and two pinch to zoom
  const touches = new Map<number, { x: number; y: number }>();
  let pinch: { d: number } | null = null;
  let waiting = false; // a touch on the plot before its tap
  const active = () => view.root.contains(document.activeElement) || view.isFullscreen();
  const spread = () => {
    const [a, b] = [...touches.values()];
    return { d: Math.hypot(a.x - b.x, a.y - b.y), mid: (a.x + b.x) / 2 };
  };

  stage.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    if (e.pointerType === "touch") {
      if (!active()) {
        waiting = true;
        return;
      }
      touches.set(e.pointerId, local(e));
      if (touches.size >= 2) {
        // a second finger: pinch, not a drag
        cancelDrag(view);
        if (touches.size === 2) {
          view.pushHistory();
          pinch = { d: spread().d };
        }
        return;
      }
    }
    view.root.focus({ preventScroll: true });
    const p = local(e);
    const plot = view.plot();
    stage.setPointerCapture(e.pointerId);
    let mode: DragMode;
    if (view.annotating) mode = "note";
    else if (view.spaceDown) mode = "pan";
    else if (p.y < plot.y && p.x >= plot.x) mode = "axis";
    else if (view.tool === "zoom") mode = "zoom";
    else if (view.tool === "select") mode = "select";
    else mode = e.shiftKey ? "zoom" : "pan";
    view.drag = { x: p.x, y: p.y, left: view.camera.left, scrollY: view.scrollY, mode, moved: false };
  });

  stage.addEventListener("pointermove", (e) => {
    const p = local(e);
    if (e.pointerType === "touch" && touches.has(e.pointerId)) {
      touches.set(e.pointerId, p);
      if (pinch && touches.size === 2) {
        const s = spread();
        const plot = view.plot();
        if (pinch.d > 0 && s.d > 0) view.camera.zoomAt(Math.max(0, Math.min(plot.w, s.mid - plot.x)), s.d / pinch.d);
        pinch.d = s.d;
        view.afterMove();
        return;
      }
    }
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
    if (e.pointerType === "touch") {
      if (waiting) {
        // the tap: the plot takes the fingers from now on
        waiting = false;
        view.root.focus({ preventScroll: true });
        view.flashNotice("Drag to pan · pinch to zoom · tap outside the plot to scroll the page");
        return;
      }
      touches.delete(e.pointerId);
      if (pinch) {
        if (touches.size < 2) pinch = null;
        return;
      }
    }
    const d = view.drag;
    const box = view.box;
    view.drag = null;
    view.box = null;
    stage.classList.remove("atl-panning");
    if (!d) return;
    const p = local(e);
    const wide = box && Math.abs(box.x1 - box.x0) >= MIN_BOX;
    if (d.mode === "note") {
      note(view, p, d.moved && box && wide ? box : null);
      view.requestRender();
      return;
    }
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
  stage.addEventListener("pointercancel", (e) => {
    if (e.pointerType === "touch") {
      touches.delete(e.pointerId);
      if (touches.size < 2) pinch = null;
      if (waiting) {
        // the page scrolled under the finger
        waiting = false;
        view.flashNotice("Tap the plot first, then drag to pan");
      }
    }
    cancelDrag(view);
  });
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

/** The key `a`, then a drag over a range or a click at a time: a note there (in the lane
 * dragged in, when the drag stays in one; at a click: the lane clicked), with its text. */
function note(view: TimelineView, p: { x: number; y: number }, box: Box | null): void {
  view.annotating = false;
  view.setMode(null);
  const plot = view.plot();
  const inside = (y: number) => Math.max(plot.y, Math.min(plot.y + plot.h - 1, y));
  const laneTop = plot.y - view.scrollY;
  const rowOf = (y: number) => Math.floor((inside(y) - laneTop) / view.laneH);
  const r0 = rowOf(box ? Math.min(box.y0, box.y1) : p.y);
  const r1 = rowOf(box ? Math.max(box.y0, box.y1) : p.y);
  const lane = r0 === r1 && p.y >= plot.y ? (view.laneAt[r0] ?? null) : null;
  const at = (x: number) => view.camera.fromPx(Math.max(0, Math.min(plot.w, x - plot.x)));
  const xa = box ? Math.min(box.x0, box.x1) : p.x;
  const xb = box ? Math.max(box.x0, box.x1) : p.x;
  // on the order scale the note's times are the instants' at its ends
  const time = (v: number) => (view.xscale === "order" ? (view.seq?.count ? view.seq.time(Math.max(0, Math.min(view.seq.count - 1, Math.round(v)))) : v) : v);
  const x0 = time(at(xa));
  const x1 = box ? time(at(xb)) : null;
  askText(view, xa, (lane === null ? plot.y : laneTop + Math.max(0, r0) * view.laneH) + 2, (text) => {
    if (text !== null) view.callbacks.onAnnotate?.({ x0, x1, lane, text });
  });
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
  const target = e.target as HTMLElement | null;
  if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT")) return;
  if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "f" && !view.helpEl) {
    // the plot's search, not the page's, while the plot has the keyboard
    e.preventDefault();
    e.stopPropagation();
    view.finder.open();
    return;
  }
  const k = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && !e.altKey && (k === "z" || (k === "y" && e.ctrlKey)) && view.callbacks.onUndo && view.selectionMode !== "none") {
    // the selection's history, kept in Python (the notebook's own undo stays out)
    e.preventDefault();
    e.stopPropagation();
    view.callbacks.onUndo(k === "y" || e.shiftKey);
    return;
  }
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
    case "/":
      view.finder.open();
      break;
    case "a":
      if (!view.callbacks.onAnnotate) {
        view.flashNotice("Annotations are made in Python here");
        break;
      }
      view.connectFrom = null;
      view.annotating = !view.annotating;
      view.setMode(view.annotating ? "Annotate: drag over a time range, or click a time · Esc cancels" : null);
      break;
    case "c": {
      if (!view.callbacks.onConnect) {
        view.flashNotice("Connections are made in Python here");
        break;
      }
      const mark = markOf(view, view.hovered) ?? (view.focus ? { layer: view.focus.layer, index: view.focus.index } : null);
      if (!mark) {
        view.flashNotice("Point at a mark, then press c");
        break;
      }
      if (!view.connectFrom) {
        view.connectFrom = mark;
        view.annotating = false;
        view.setMode("Connect: point at another mark and press c · Esc cancels");
      } else {
        const from = view.connectFrom;
        view.connectFrom = null;
        view.setMode(null);
        if (from.layer !== mark.layer || from.index !== mark.index) view.callbacks.onConnect(from, mark);
      }
      break;
    }
    case ".":
    case ",":
      void view.step(e.key === ".");
      break;
    case "F":
      if (!view.focus) return;
      view.setFocus(view.focus, true, true);
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
      else if (view.annotating || view.connectFrom) {
        view.annotating = false;
        view.connectFrom = null;
        view.setMode(null);
      }
      else if (view.finder.isOpen) view.finder.close();
      else if (view.focus) view.setFocus(null);
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
