// anywidget entry (AFM): connects a Python Timeline model to TimelineView.

import { BufferStore, type PutMessage } from "./core/transport";
import type { RendererPreference, SceneSpec, XScale } from "./core/types";
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
    if (msg?.type === "put") state.store.receive(msg as PutMessage, buffers[0]);
    else if (msg?.type === "missing") state.store.missing(msg.id);
    else if (msg?.type === "answer") {
      state.pending.get(msg.request)?.(msg);
      state.pending.delete(msg.request);
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
    onView: (range) => send(model, { type: "view", range }),
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
  const onHover = () => view.setHover(Boolean(model.get("hover")));
  const onLegend = () => view.setLegend(Boolean(model.get("legend")));
  const onMode = () => view.setSelectionMode(String(model.get("selection_mode")));
  const onTool = () => view.setTool((model.get("tool") ?? "pan") as Tool);
  const onFontSize = () => view.setFontSize(Number(model.get("font_size") ?? 12));
  const onLink = () => {
    const l = model.get("_link") as { group?: string; align?: string } | null;
    view.setLink(l?.group ? { group: l.group, align: l.align === "start" ? "start" : "time" } : null);
  };
  let zoomN = Number(model.get("_zoom")?.n ?? 0);
  const onZoom = () => {
    const z = model.get("_zoom");
    if (z?.n && z.n !== zoomN && Array.isArray(z.range)) {
      zoomN = z.n;
      view.zoomTo(z.range as [number, number]);
    }
  };
  const handlers: [string, () => void][] = [
    ["change:_spec", load],
    ["change:renderer", onRenderer],
    ["change:height", onHeight],
    ["change:title", onTitle],
    ["change:xscale", onXScale],
    ["change:_marks", onMarks],
    ["change:hover", onHover],
    ["change:legend", onLegend],
    ["change:selection_mode", onMode],
    ["change:tool", onTool],
    ["change:font_size", onFontSize],
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
  onMarks();
  onXScale();
  onLink();
  load();
  // a zoom_to made before the plot was shown applies once the data is there
  const z = model.get("_zoom");
  if (z?.range) setTimeout(() => {
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
