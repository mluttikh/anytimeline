// Standalone plots: the data embedded in the page, so they work without a kernel and without
// network access (e.g. the documentation). Any number per page: <div class="anytimeline-embed">
// holding a <script type="application/json"> with the data (Python: Timeline._embed_html).
// Each plot starts when it comes near the screen, and follows the page's light or dark theme.

import type { DataSource, RendererPreference, SceneSpec, XScale } from "./core/types";
import { type Tool, TimelineView } from "./core/view";

/** The data of one plot, as Timeline writes it (Python: _standalone_data). */
interface Payload {
  spec: SceneSpec;
  /** Buffer id → base64 bytes. */
  buffers: Record<string, string>;
  height: number;
  renderer: RendererPreference;
  title: string;
  xscale: XScale;
  tool: Tool;
  legend: boolean;
  hover: boolean;
  font_size: number;
  mark_scale?: number;
  dodge?: boolean;
  /** The last zoom_to (ticks), or null. */
  zoom: [number, number] | null;
  /** The selection made in Python: layer → base64 int32 event indices. */
  marks: Record<string, string>;
  /** The group of linked plots it is in (Timeline.link), or null. */
  link?: { group: string; align: "time" | "start" } | null;
  /** Per layer, its tooltip columns as text, by event index (absent for large layers). */
  tooltips?: Record<string, { columns: string[]; values: string[][] }>;
}

function decodeBase64(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

/** Draw one plot into `host`; resolves with its view once its data is in. */
async function show(host: HTMLElement, payload: Payload): Promise<TimelineView> {
  const buffers = new Map(Object.entries(payload.buffers).map(([id, b64]) => [id, decodeBase64(b64)]));
  const source: DataSource = {
    has: (id) => buffers.has(id),
    get: (id) => buffers.get(id)!,
    ensure: (ids) => (ids.every((id) => buffers.has(id)) ? Promise.resolve() : new Promise<void>(() => {})),
  };
  // selecting needs Python, which turns gestures into table rows: none in a page (no Select
  // tool), but a selection made in Python shows
  const tips = payload.tooltips ?? {};
  const view = new TimelineView(host, {
    renderer: payload.renderer,
    onTooltip: (layer, index) => {
      const t = tips[layer];
      return Promise.resolve(t ? t.columns.map((c, k) => [c, t.values[k][index] ?? ""]) : []);
    },
  });
  view.setTitle(payload.title ?? "");
  if (host.dataset.fill === "window") {
    // a page of its own (Timeline.save_html): the plot fills the window
    const fit = () => view.setHeight(Math.max(240, window.innerHeight - host.getBoundingClientRect().top * 2));
    fit();
    window.addEventListener("resize", fit);
  } else view.setHeight(payload.height ?? 0);
  view.setFontSize(payload.font_size ?? 12);
  view.setMarkScale(payload.mark_scale ?? 1);
  view.setDodge(payload.dodge !== false);
  view.setHover(payload.hover !== false);
  view.setLegend(payload.legend !== false);
  view.setSelectionMode("none");
  view.setTool(payload.tool ?? "pan");
  view.setMarks(Object.fromEntries(Object.entries(payload.marks ?? {}).map(([k, v]) => [k, new Int32Array(decodeBase64(v))])));
  if (payload.link?.group) view.setLink(payload.link);
  await view.setSpec(payload.spec, source);
  view.setXScale(payload.xscale ?? "time");
  if (payload.zoom) view.zoomTo(payload.zoom);
  return view;
}

/** Start the plots of the page, each when it comes near the screen; returns `add`, which
 * starts one more (a notebook's output, Python: display="html") or, without a host, any that
 * have not started. */
function embedded(): (host?: HTMLElement | null) => void {
  const views = new Map<HTMLElement, TimelineView>();
  // a notebook's output that is cleared or replaced (a cell run again) takes its plot off the
  // page: its view stops (and leaves its group of linked plots)
  const prune = () => {
    for (const [host, view] of views) {
      if (host.isConnected) continue;
      views.delete(host);
      view.destroy();
    }
  };
  const start = (host: HTMLElement) => {
    const data = host.querySelector<HTMLScriptElement>("script[type='application/json']");
    if (!data || host.dataset.state) return;
    prune();
    host.dataset.state = "loading";
    host.querySelector(".anytimeline-note")?.remove(); // says what the plot needs if scripts do not run
    show(host, JSON.parse(data.textContent!) as Payload)
      .then((view) => {
        views.set(host, view);
        host.dataset.state = "ready";
      })
      .catch((err) => {
        host.dataset.state = "error";
        console.error("[anytimeline]", err);
        host.append(`anytimeline could not draw this plot: ${String(err)}`);
      });
  };
  const near =
    "IntersectionObserver" in window
      ? new IntersectionObserver(
          (entries) => {
            for (const e of entries) {
              if (!e.isIntersecting) continue;
              near!.unobserve(e.target);
              start(e.target as HTMLElement);
            }
          },
          { rootMargin: "300px 0px" },
        )
      : null;
  const add = (host: HTMLElement) => (near ? near.observe(host) : start(host));
  document.querySelectorAll<HTMLElement>(".anytimeline-embed").forEach(add);
  // (each view follows the page's light or dark theme itself)
  return (host) => {
    if (host) {
      // a notebook's output: JupyterLab and its exports style the HTML in outputs (striped
      // table rows, padding), and not a widget's; this output only holds the plot, which then
      // looks as it does as a widget
      host.parentElement?.classList.remove("jp-RenderedHTMLCommon");
      add(host);
    } else document.querySelectorAll<HTMLElement>(".anytimeline-embed:not([data-state])").forEach(add);
  };
}

declare global {
  interface Window {
    /** Plots in a notebook's outputs (Python: display="html"): each output runs this script
     * only when the page has not run this version of it (kept under a hash of it in
     * `window.anytimelineEmbeds`), then adds its plot. */
    anytimelineEmbed?: { add: (host?: HTMLElement | null) => void };
  }
}

if (document.readyState === "loading") {
  // a page of its own: its plots are in the page when it is read
  let add: ((host?: HTMLElement | null) => void) | null = null;
  const pending: (HTMLElement | null | undefined)[] = [];
  window.anytimelineEmbed = { add: (host) => (add ? add(host) : pending.push(host)) };
  document.addEventListener("DOMContentLoaded", () => {
    add = embedded();
    pending.forEach((h) => add!(h));
  });
} else window.anytimelineEmbed = { add: embedded() };
