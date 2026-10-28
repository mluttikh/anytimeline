// anywidget entry (AFM): connects a Python Timeline model to TimelineView.

import type { Found, Match } from "./core/find";
import type { NoteEnd, Notes } from "./core/notes";
import type { LayerSummary } from "./core/summary";
import { BufferStore, type PutMessage } from "./core/transport";
import type { RendererPreference, SceneSpec, WindowAnswer, XScale } from "./core/types";
import { type Gesture, type Tool, TimelineView } from "./core/view";

interface AnyModel {
  get(key: string): any;
  set(key: string, value: unknown): void;
  save_changes(): void;
  on(event: string, cb: (...args: any[]) => void): void;
  off(event?: string, cb?: (...args: any[]) => void): void;
  send(content: unknown, callbacks?: unknown, buffers?: ArrayBuffer[]): void;
}

interface ModelState {
  store: BufferStore;
  views: Set<TimelineView>;
  pending: Map<number, (msg: any) => void>;
  nextRequest: number;
  tooltips: Map<string, Promise<string[][]>>;
  perf: Record<string, unknown>;
  perfTimer: ReturnType<typeof setTimeout> | undefined;
}

const states = new WeakMap<AnyModel, ModelState>();
const ASK_TIMEOUT_MS = 10_000;

const NO_DATA_HINT = "Waiting for data from Python. Is the kernel running? Run the cell again.";
const NO_ANSWER_HINT = "Python no longer answers for this plot, for example after a kernel restart. Run its cell again.";

function stateFor(model: AnyModel): ModelState {
  let s = states.get(model);
  if (s) return s;
  const state: ModelState = {
    store: new BufferStore((ids) => model.send({ type: "need", ids })),
    views: new Set(),
    pending: new Map(),
    nextRequest: 0,
    tooltips: new Map(),
    perf: {},
    perfTimer: undefined,
  };
  model.on("msg:custom", (msg: any, buffers: (DataView | ArrayBuffer)[] = []) => {
    if (msg?.type === "put" && msg.url) fetchFile(model, state.store, msg as PutMessage);
    else if (msg?.type === "put") state.store.receive(msg as PutMessage, buffers[0]);
    else if (msg?.type === "missing") state.store.missing(msg.id);
    else if (msg?.type === "answer") {
      state.pending.get(msg.request)?.(msg);
      state.pending.delete(msg.request);
    } else if (msg?.type === "benchmark") {
      // Python's plot.dev.benchmark(): frames drawn in the first view, as perf
      const view = [...state.views][0];
      view
        ?.benchmark(Number(msg.frames ?? 60))
        .then((result) => {
          Object.assign(state.perf, { benchmark: result });
          send(model, { type: "perf", update: state.perf });
        })
        .catch(() => {});
    } else if (msg?.type === "snapshot") {
      // Python's save_png: a picture of the plot as shown (the first view that has one)
      const view = [...state.views][0];
      if (!view) return;
      view
        .snapshot()
        .then((blob) => blob.arrayBuffer())
        .then((png) => model.send({ type: "image", request: msg.request }, undefined, [png]))
        .catch((err) => send(model, { type: "image", request: msg.request, error: String(err) }));
    }
  });
  state.store.onStall = (stalled) => {
    const text = stalled ? (state.store.received ? NO_ANSWER_HINT : NO_DATA_HINT) : null;
    state.views.forEach((v) => v.setStatus(text));
  };
  model.on("change:_spec", () => state.tooltips.clear());
  states.set(model, state);
  return state;
}

/** A buffer sent as a file (marimo): fetch it, and say so (Python then drops the file); when
 * that fails, ask for it again, and for every buffer as messages from now on. */
function fetchFile(model: AnyModel, store: BufferStore, msg: PutMessage): void {
  fetch(msg.url!)
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.arrayBuffer();
    })
    .then((bytes) => {
      if (bytes.byteLength !== msg.byteLength) throw new Error("short file");
      store.receive(msg, bytes);
      send(model, { type: "fetched", file: msg.file });
    })
    .catch((err) => {
      console.warn("[anytimeline] cannot fetch a buffer file, asking for messages:", err);
      send(model, { type: "fetched", file: msg.file });
      send(model, { type: "need", ids: [msg.id], files: false });
    });
}

function ask(model: AnyModel, s: ModelState, content: Record<string, unknown>): Promise<any> {
  const request = ++s.nextRequest;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      s.pending.delete(request);
      reject(new Error("no answer"));
    }, ASK_TIMEOUT_MS);
    s.pending.set(request, (msg) => {
      clearTimeout(timer);
      if (msg.error) reject(new Error(msg.error));
      else resolve(msg);
    });
    try {
      model.send({ ...content, request });
    } catch (err) {
      clearTimeout(timer);
      s.pending.delete(request);
      reject(err);
    }
  });
}

function send(model: AnyModel, content: Record<string, unknown>): void {
  try {
    model.send(content);
  } catch {
    // no Python: the store notices missing answers and says so
  }
}

function marksOf(model: AnyModel): Record<string, Int32Array> {
  const raw = (model.get("_marks") ?? {}) as Record<string, DataView | ArrayBuffer | Uint8Array>;
  const out: Record<string, Int32Array> = {};
  for (const [name, v] of Object.entries(raw)) {
    const bytes = v instanceof ArrayBuffer ? new Uint8Array(v) : new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
    out[name] = new Int32Array(bytes.slice().buffer);
  }
  return out;
}

function markedOf(model: AnyModel): Record<string, Float64Array> {
  const raw = (model.get("_marked") ?? {}) as Record<string, DataView | ArrayBuffer | Uint8Array>;
  const out: Record<string, Float64Array> = {};
  for (const [name, v] of Object.entries(raw)) {
    const bytes = v instanceof ArrayBuffer ? new Uint8Array(v) : new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
    out[name] = new Float64Array(bytes.slice().buffer);
  }
  return out;
}

function render({ model, el }: { model: AnyModel; el: HTMLElement }): () => void {
  const s = stateFor(model);
  let pickCount = Number(model.get("_pick")?.n ?? 0);
  const reportPerf = (update: Record<string, unknown>) => {
    Object.assign(s.perf, update);
    clearTimeout(s.perfTimer);
    s.perfTimer = setTimeout(() => send(model, { type: "perf", update: s.perf }), 500);
  };
  const view = new TimelineView(el, {
    onGesture: (g: Gesture) => {
      model.set("_pick", { ...g, n: ++pickCount });
      model.save_changes();
    },
    onView: (range, lanes) => send(model, { type: "view", range, lanes }),
    onXScale: (xscale: XScale) => {
      model.set("xscale", xscale);
      model.save_changes();
    },
    onTooltip: (layer, index) => {
      const key = `${layer}:${index}`;
      let p = s.tooltips.get(key);
      if (!p) {
        p = ask(model, s, { type: "tooltip", layer, index }).then((msg) => msg.rows as string[][]);
        p.catch(() => s.tooltips.delete(key));
        s.tooltips.set(key, p);
      }
      return p;
    },
    onBinTooltip: (layer, scale, lane, range) => ask(model, s, { type: "tooltip", layer, bin: { scale, lane, range } }).then((msg) => msg.rows as string[][]),
    onUndo: (redo) => send(model, { type: redo ? "redo" : "undo" }),
    onAnnotate: (note) => send(model, { type: "annotate", ...note }),
    onConnect: (a, b) => send(model, { type: "connect", a, b }),
    onMeasure: (a, b, lane) => send(model, { type: "measure", a, b, lane }),
    onNoteEnd: (id, end, to) => send(model, { type: "note_end", id, end, to }),
    onNoteRemove: (id) => send(model, { type: "note_remove", id }),
    onSnap: (q) => ask(model, s, { type: "snap", ...q }).then((msg) => (msg.edge ?? null) as NoteEnd | null),
    onFind: (q, scale) => ask(model, s, { type: "find", q, scale }) as Promise<Found>,
    onStep: (lane, after, forward, scale) => ask(model, s, { type: "step", lane, after, forward, scale }).then((msg) => (msg.match ?? null) as Match | null),
    onWindow: (layer, scale, range, k) => ask(model, s, { type: "window", layer, scale, range, k }) as Promise<WindowAnswer>,
    onPerf: reportPerf,
    onTool: (tool: Tool) => {
      model.set("tool", tool);
      model.save_changes();
    },
    onLegend: (on: boolean) => {
      model.set("legend", on);
      model.save_changes();
    },
    onFontSize: (px: number) => {
      model.set("font_size", px);
      model.save_changes();
    },
    onMarkScale: (factor: number) => {
      model.set("mark_scale", factor);
      model.save_changes();
    },
    onDodge: (on: boolean) => {
      model.set("dodge", on);
      model.save_changes();
    },
    renderer: (model.get("renderer") ?? "auto") as RendererPreference,
  });
  s.views.add(view);

  const load = () => {
    const spec = model.get("_spec") as SceneSpec;
    if (spec && spec.version) void view.setSpec(spec, s.store);
  };
  const onRenderer = () => void view.setRenderer((model.get("renderer") ?? "auto") as RendererPreference);
  const onHeight = () => view.setHeight(Number(model.get("height") ?? 0));
  const onTitle = () => view.setTitle(String(model.get("title") ?? ""));
  const onXScale = () => view.setXScale((model.get("xscale") ?? "time") as XScale);
  const onMarks = () => view.setMarks(marksOf(model));
  const onMarked = () => view.setMarked(markedOf(model));
  const onNotes = () => view.setNotes((model.get("_notes") ?? {}) as Notes);
  const onSummary = () => view.setSummary((model.get("_summary") ?? []) as LayerSummary[]);
  const onHover = () => view.setHover(Boolean(model.get("hover")));
  const onLegend = () => view.setLegend(Boolean(model.get("legend")));
  const onMode = () => view.setSelectionMode(String(model.get("selection_mode") ?? "none"));
  const onTool = () => view.setTool((model.get("tool") ?? "pan") as Tool);
  const onFontSize = () => view.setFontSize(Number(model.get("font_size") ?? 12));
  const onMarkScale = () => view.setMarkScale(Number(model.get("mark_scale") ?? 1));
  const onDodge = () => view.setDodge(model.get("dodge") !== false);
  const onLink = () => {
    const l = model.get("_link") as { group?: string; align?: string } | null;
    view.setLink(l?.group ? { group: l.group, align: l.align === "start" ? "start" : "time" } : null);
  };
  let zoomN = Number(model.get("_zoom")?.n ?? 0);
  // plot.view and zoom_to: a range (null: the whole timeline) and, set with plot.view, the
  // lane at the top (null: from the top)
  const onZoom = () => {
    const z = model.get("_zoom");
    if (z?.n && z.n !== zoomN) {
      zoomN = z.n;
      view.setView(Array.isArray(z.range) ? (z.range as [number, number]) : null, "lanes" in z ? (z.lanes as string | null) : undefined);
    }
  };
  const handlers: [string, () => void][] = [
    ["change:_spec", load],
    ["change:renderer", onRenderer],
    ["change:height", onHeight],
    ["change:title", onTitle],
    ["change:xscale", onXScale],
    ["change:_marks", onMarks],
    ["change:_marked", onMarked],
    ["change:_summary", onSummary],
    ["change:_notes", onNotes],
    ["change:hover", onHover],
    ["change:legend", onLegend],
    ["change:selection_mode", onMode],
    ["change:tool", onTool],
    ["change:font_size", onFontSize],
    ["change:mark_scale", onMarkScale],
    ["change:dodge", onDodge],
    ["change:_zoom", onZoom],
    ["change:_link", onLink],
  ];
  for (const [event, fn] of handlers) model.on(event, fn);
  onTitle();
  onHeight();
  onHover();
  onLegend();
  onMode();
  onTool();
  onFontSize();
  onMarkScale();
  onDodge();
  onMarks();
  onMarked();
  onSummary();
  onNotes();
  onXScale();
  onLink();
  load();
  // a zoom_to made before the plot was shown applies once the data is there
  const z = model.get("_zoom");
  if (z?.n) setTimeout(() => {
    zoomN = 0;
    onZoom();
  }, 50);

  return () => {
    for (const [event, fn] of handlers) model.off(event, fn);
    s.views.delete(view);
    view.destroy();
  };
}

export default { render };
