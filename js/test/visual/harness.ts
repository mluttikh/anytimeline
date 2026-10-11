// Visual test harness: renders a scene written by scripts/make_scenes.py with the real widget
// code, playing the notebook's part (the model, and Python's answers to "need").
//
// harness.html?scene=service_time&renderer=webgl2

import widget from "../../src/widget";

type Handler = (...args: any[]) => void;

function bytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function main(): Promise<void> {
  const params = new URLSearchParams(location.search);
  const scene = params.get("scene") ?? "service_time";
  const data = await (await fetch(`scenes/${scene}.json`)).json();
  const state: Record<string, any> = { ...data.state, renderer: params.get("renderer") ?? "auto" };
  if (params.get("height")) state.height = Number(params.get("height"));
  if (params.get("font_size")) state.font_size = Number(params.get("font_size"));
  if (params.get("width")) document.getElementById("plot")!.style.width = params.get("width") + "px";
  state._marks = Object.fromEntries(Object.entries(state._marks ?? {}).map(([k, v]) => [k, bytes(v as string).buffer]));
  const buffers: Record<string, string> = data.buffers;
  const handlers = new Map<string, Set<Handler>>();
  const log: unknown[] = [];
  const model = {
    get: (k: string) => state[k],
    set: (k: string, v: unknown) => {
      state[k] = v;
      log.push({ set: k, value: v });
    },
    save_changes: () => {},
    on: (e: string, cb: Handler) => {
      if (!handlers.has(e)) handlers.set(e, new Set());
      handlers.get(e)!.add(cb);
    },
    off: (e?: string, cb?: Handler) => {
      if (e && cb) handlers.get(e)?.delete(cb);
    },
    send: (content: any) => {
      log.push(content);
      if (content.type === "need") {
        setTimeout(() => {
          for (const id of content.ids as string[]) {
            const b = bytes(buffers[id]);
            const msg = { type: "put", id, chunk: 0, chunks: 1, offset: 0, byteLength: b.byteLength, t_send: Date.now() / 1000 };
            handlers.get("msg:custom")?.forEach((h) => h(msg, [b.buffer]));
          }
        }, 1);
      } else if (content.type === "tooltip") {
        setTimeout(() => handlers.get("msg:custom")?.forEach((h) => h({ type: "answer", request: content.request, rows: [["row", String(content.index)]] }), []), 1);
      } else if (content.type === "perf") {
        (window as any).__perf = content.update;
      }
    },
  };
  const el = document.getElementById("plot")!;
  (window as any).__log = log;
  (window as any).__model = { state, emit: (e: string) => handlers.get(e)?.forEach((h) => h()) };
  widget.render({ model, el });
}

void main();
