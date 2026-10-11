// TimelineView: one timeline in a DOM element. It lays out the lanes and the time axis,
// keeps the camera, culls and dodges the events in view, and hands the backend what to draw.
// Three canvases are stacked: the back (lane bands, grid lines), the renderer's (events,
// routes) and the front (axis, lane names, labels, hover ring, selection box).
//
// Framework-agnostic: widget.ts connects it to anywidget; another host supplies a
// DataSource and the callbacks.

import { BarLayer, type BarView, decodeBars } from "./bars";
import { TimeCamera } from "./camera";
import { dodge, rowsFor, spacing } from "./dodge";
import { buildHelp } from "./help";
import { buildLegend } from "./legend";
import { FLAG_SELECTED, type FrameDraw, type MarkLayerDraw, type Renderer, type SegmentDraw } from "./renderers/renderer";
import { createRenderer } from "./renderers/select";
import { type Align, compatible, convert, frameOf, join, leave, type LinkFrame, type LinkPeer, type LinkSpec, others } from "./link";
import { download, fileName, legendPainter } from "./snapshot";
import { levelOffset, levelsFor, placeStems, type StemItem, type StemPlaced } from "./stems";
import { decodeValues, ValueLayer, type ValueView } from "./values";
import { decodeEvents, type EventsData, fillSolid, lowerBound, parseHex, specBufferIds, upperBound } from "./scene";
import { TimeAxis, UNIT_NS, fmtNumber } from "./time";
import { FONT_SIZES, TOOLS, type Tool, Toolbar } from "./toolbar";
import type { DataSource, EventsLayerSpec, IntervalsLayerSpec, RendererKind, RendererPreference, SceneSpec, ValuesLayerSpec, XScale } from "./types";

/** What is under the pointer: an event, a bar (`bar`) or a sample of a values layer (`val`);
 * `layer` indexes the view's events layers, bars or values accordingly. */
type Hit = { layer: number; index: number; bar?: boolean; val?: boolean };

const PAD_RIGHT = 10;
const PAD_BOTTOM = 8;
const MIN_LANE = 18;
const AUTO_LANE = 30;
/** A zoom or selection box narrower than this (px) is a click. */
const MIN_BOX = 8;
const DOUBLE_CLICK_MS = 300;
/** Views remembered for Back. */
const HISTORY = 20;
const HOVER_PX = 9;
const LABEL_BUDGET = 3000;
const ROUTE_BUDGET = 60_000;
/** Break marks of long gaps (Order scale) at least this far apart (px); the longest win. */
const GAP_PX = 28;

export type Gesture =
  | { kind: "click"; layer: string; index: number; mode: SelectMode }
  | { kind: "box"; x: [number, number]; lanes: [number, number]; shown?: number[]; xscale: XScale; mode: SelectMode }
  | { kind: "clear" };
export type SelectMode = "replace" | "add" | "remove" | "toggle";
export type { Tool } from "./toolbar";

/** What a drag does: set when it starts, from the tool, the keys held and where it starts. */
type DragMode = "pan" | "zoom" | "select" | "axis";
/** A zoom range (a band over all lanes), a selection box, or a time range to select. */
type BoxKind = "range" | "select" | "range-select";
interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  kind: BoxKind;
}

export interface ViewCallbacks {
  onGesture?: (g: Gesture) => void;
  /** The visible range in time ticks (debounced). */
  onView?: (range: [number, number]) => void;
  onXScale?: (xscale: XScale) => void;
  /** Tooltip columns of one event: [name, value] rows. */
  onTooltip?: (layer: string, index: number) => Promise<string[][]>;
  onPerf?: (update: Record<string, unknown>) => void;
  /** The backend to start with (default "auto"). */
  renderer?: RendererPreference;
  /** The user switched the tool (toolbar or key). */
  onTool?: (tool: Tool) => void;
  /** The user showed or hid the legend. */
  onLegend?: (on: boolean) => void;
  /** The user changed the text size (px). */
  onFontSize?: (px: number) => void;
  /** The user changed the mark size (a factor of the layers' own). */
  onMarkScale?: (factor: number) => void;
  /** The user switched spreading overlapping events on or off. */
  onDodge?: (on: boolean) => void;
}

interface Layer {
  data: EventsData;
  draw: MarkLayerDraw;
  /** Screen x per event (CSS px, plot-relative) of the last cull. */
  xs: Float64Array;
  /** The range in x units that dodging covered, and at which scale. */
  dodged: { left: number; right: number; scale: number; laneH: number } | null;
  /** The marks' sizes as the layer gives them (data.size holds them × the mark scale). */
  baseSize: Float32Array;
}

interface Theme {
  bg: string;
  text: string;
  muted: string;
  grid: string;
  band: string;
  select: string;
  accent: string;
}

export class TimelineView {
  readonly root: HTMLDivElement;
  private readonly header: HTMLDivElement;
  private readonly titleEl: HTMLSpanElement;
  private readonly info: HTMLSpanElement;
  private readonly toolbar: Toolbar;
  private tool: Tool = "pan";
  private history: { left: number; span: number; scrollY: number; xscale: XScale }[] = [];
  private helpEl: HTMLElement | null = null;
  private spaceDown = false;
  private lastWheel = 0;
  /** Text size in CSS px: lane names; axis and labels are 1 px smaller. */
  private fs = FONT_SIZES.default;
  private readonly stage: HTMLDivElement;
  private readonly back: HTMLCanvasElement;
  private readonly front: HTMLCanvasElement;
  private readonly tooltip: HTMLDivElement;
  private readonly notice: HTMLDivElement;
  private legendEl: HTMLElement | null = null;
  private renderer: Renderer | null = null;
  private rendererPref: RendererPreference = "auto";
  private failedKinds: RendererKind[] = [];
  private spec: SceneSpec | null = null;
  private axis: TimeAxis | null = null;
  private layers: Layer[] = [];
  private seqTimes: Float64Array | null = null;
  private gaps: { at: number; span: number }[] = [];
  private readonly camera = new TimeCamera();
  private xscale: XScale = "time";
  private base = 0;
  private baseVersion = 0;
  private scrollY = 0;
  private laneH = AUTO_LANE;
  /** The lane each row of the plot shows; folded lanes hide the lanes under them. */
  private laneAt = new Int32Array(0);
  /** The row of each lane, -1 when hidden. */
  private slot = new Int32Array(0);
  /** Per lane of the tree (lanes.tree): whether its children show. */
  private open = new Uint8Array(0);
  /** Rows the plot's automatic height is for (fixed when the spec arrives, so folding does
   * not resize the plot). */
  private autoRows = 1;
  private gutter = 80;
  /** Room on the right: the legend's column when the plot is wide enough. */
  private padRight = PAD_RIGHT;
  private width = 0;
  private height = 0;
  private fixedHeight = 0;
  private dpr = 1;
  private marks: Record<string, Int32Array> = {};
  /** The event or bar under the pointer (`bar`: an index into `bars`, else into `layers`). */
  private hovered: Hit | null = null;
  private bars: BarLayer[] = [];
  private values: ValueLayer[] = [];
  private hoverEnabled = true;
  private selectionMode = "multiple";
  private showLegend = true;
  private theme: Theme;
  private frameRequested = false;
  private viewTimer: ReturnType<typeof setTimeout> | undefined;
  private drag: { x: number; y: number; left: number; scrollY: number; mode: DragMode; moved: boolean } | null = null;
  private box: Box | null = null;
  private pointer: { x: number; y: number } | null = null;
  private tooltipKey = "";
  private readonly resizeObserver: ResizeObserver;
  private loadToken = 0;
  private firstFrameAt = 0;
  private status: string | null = null;
  private lastTap = 0;
  /** The group of linked plots this view is in, and how it is in it. */
  private link: { spec: LinkSpec; peer: LinkPeer } | null = null;
  /** Following another view (its range or pointer): do not pass it on. */
  private following = false;
  /** The pointer of a linked view: a time in this view's ticks, or null. */
  private linkedCursor: number | null = null;
  /** This view's own gutter and right padding, before the group's widest. */
  private own = { gutter: 80, padRight: PAD_RIGHT };
  /** The last click on a lane's name: a second one soon after on the same lane zooms to it. */
  private lastNameTap = { at: 0, lane: -1 };

  constructor(
    private readonly host: HTMLElement,
    private readonly callbacks: ViewCallbacks = {},
  ) {
    this.root = document.createElement("div");
    this.root.className = "atl-root";
    this.root.tabIndex = 0;
    (this.root as unknown as { __view: TimelineView }).__view = this; // for tests and debugging
    this.header = div("atl-header");
    this.titleEl = document.createElement("span");
    this.titleEl.className = "atl-title";
    this.info = document.createElement("span");
    this.info.className = "atl-info";
    this.toolbar = new Toolbar({
      tool: (t) => this.setTool(t, true),
      xscale: (xs) => this.setXScale(xs, true),
      previous: () => this.previousView(),
      home: () => this.resetView(),
      clear: () => this.callbacks.onGesture?.({ kind: "clear" }),
      legend: () => this.toggleLegend(),
      fullscreen: () => this.toggleFullscreen(),
      image: () => void this.savePNG(),
      help: () => this.toggleHelp(),
      fontSize: (px) => {
        this.setFontSize(px ?? FONT_SIZES.default);
        this.callbacks.onFontSize?.(this.fs);
      },
      markScale: (factor) => {
        this.setMarkScale(factor ?? 1);
        this.callbacks.onMarkScale?.(this.markScale);
      },
      dodge: (on) => {
        this.setDodge(on);
        this.callbacks.onDodge?.(this.dodgeOn);
      },
    });
    this.header.append(this.titleEl, this.info, this.toolbar.hint, this.toolbar.element);
    this.stage = div("atl-stage");
    this.back = canvas("atl-back");
    this.front = canvas("atl-front");
    this.tooltip = div("atl-tooltip");
    this.notice = div("atl-notice");
    this.stage.append(this.back, this.front, this.tooltip, this.notice);
    this.root.append(this.header, this.stage);
    host.append(this.root);
    this.theme = this.readTheme();
    this.bindInput();
    this.stage.dataset.tool = this.tool;
    this.updateToolbar();
    this.resizeObserver = new ResizeObserver(() => this.layout());
    this.resizeObserver.observe(this.root);
    // the host's light or dark theme: the OS's, or an attribute of <html> or <body> that
    // JupyterLab, VS Code, marimo and documentation themes switch
    this.themeMedia = matchMedia?.("(prefers-color-scheme: dark)") ?? null;
    this.themeMedia?.addEventListener?.("change", this.onThemeChange);
    this.themeWatch = new MutationObserver(this.onThemeChange);
    for (const el of [document.documentElement, document.body]) {
      if (el) this.themeWatch.observe(el, { attributes: true, attributeFilter: THEME_ATTRIBUTES });
    }
    void this.setRenderer(callbacks.renderer ?? "auto");
  }

  // ------------------------------------------------------------------ settings

  async setRenderer(pref: RendererPreference): Promise<void> {
    if (pref === this.rendererPref && (this.renderer || this.rendererToken)) return;
    this.rendererPref = pref;
    this.failedKinds = [];
    await this.makeRenderer();
  }

  private rendererToken = 0;

  private async makeRenderer(): Promise<void> {
    const token = ++this.rendererToken;
    this.renderer?.destroy();
    this.renderer?.canvas.remove();
    this.renderer = null;
    try {
      const { renderer, skipped } = await createRenderer(this.rendererPref, () => {
        const c = canvas("atl-gpu");
        this.stage.insertBefore(c, this.front);
        return c;
      }, this.failedKinds);
      if (token !== this.rendererToken) {
        // a newer request (another backend) started meanwhile: it wins
        renderer.destroy();
        renderer.canvas.remove();
        return;
      }
      this.renderer = renderer;
      renderer.onFailure = (reason) => {
        console.warn("[anytimeline]", reason);
        this.failedKinds.push(renderer.kind);
        this.callbacks.onPerf?.({ failed: [...this.failedKinds], reason });
        void this.makeRenderer();
      };
      this.callbacks.onPerf?.({ renderer: renderer.kind, description: renderer.description, skipped });
      for (const l of this.layers) this.bumpAll(l);
      for (const b of this.bars) b.bumpAll();
      this.layout();
    } catch (err) {
      this.setStatus(String(err));
    }
  }

  setTitle(title: string): void {
    this.titleEl.textContent = title;
    this.titleEl.style.display = title ? "" : "none";
  }

  setHeight(height: number): void {
    this.fixedHeight = Math.max(0, height);
    this.layout();
  }

  setHover(on: boolean): void {
    this.hoverEnabled = on;
    if (!on) this.setHovered(null);
  }

  setSelectionMode(mode: string): void {
    this.selectionMode = mode;
    if (!this.offeredTools().includes(this.tool)) this.setTool("pan");
    this.updateToolbar();
  }

  setLegend(on: boolean): void {
    this.showLegend = on;
    if (this.legendEl) this.legendEl.style.display = on ? "" : "none";
    this.layout();
    this.updateToolbar();
  }

  /** The size of all text in the plot (CSS px): canvas text, header, legend, tooltip. */
  setFontSize(px: number): void {
    const fs = Math.round(Math.max(FONT_SIZES.min, Math.min(FONT_SIZES.max, Number(px) || FONT_SIZES.default)));
    if (fs === this.fs && this.root.style.getPropertyValue("--atl-font-size")) return;
    this.fs = fs;
    this.root.style.setProperty("--atl-font-size", `${fs}px`);
    for (const l of this.layers) l.dodged = null;
    this.layout();
    this.updateToolbar();
  }

  /** The size of event marks, as a factor of the sizes the layers give them (0.25 to 4). */
  setMarkScale(factor: number): void {
    const s = Math.max(0.25, Math.min(4, Number(factor) || 1));
    if (s === this.markScale) return;
    this.markScale = s;
    for (const l of this.layers) this.scaleMarks(l);
    this.requestRender();
    this.updateToolbar();
  }

  private markScale = 1;

  private scaleMarks(l: Layer): void {
    const size = l.data.size;
    for (let i = 0; i < size.length; i++) size[i] = l.baseSize[i] * this.markScale;
    l.draw.size.version++;
    l.dodged = null;
  }

  /** Spread events that would overlap over sub-rows (dodging), or draw them all on the
   * lane's line (layers with overlap="overlay" never spread). */
  setDodge(on: boolean): void {
    if (on === this.dodgeOn) return;
    this.dodgeOn = on;
    for (const l of this.layers) {
      l.draw.dy.data.fill(0);
      l.draw.dy.version++;
      l.dodged = null;
    }
    this.requestRender();
    this.updateToolbar();
  }

  private dodgeOn = true;

  /** The canvas font, `delta` px from the text size. */
  private font(delta = 0): string {
    return `${Math.max(6, this.fs + delta)}px ${fontFamily}`;
  }

  /** The time axis' height: two rows of text. */
  private get axisH(): number {
    return Math.round((44 * this.fs) / FONT_SIZES.default);
  }

  /** The smallest lane: room for its name. */
  private minLane(): number {
    return Math.max(MIN_LANE, Math.round(this.fs * 1.5));
  }

  setStatus(text: string | null): void {
    this.status = text;
    this.notice.textContent = text ?? "";
    this.notice.classList.toggle("atl-show", !!text);
  }

  /** The selected events per layer, as indices into the layer's (sorted) events. */
  setMarks(marks: Record<string, Int32Array>): void {
    this.marks = marks;
    for (const l of this.layers) this.applyMarks(l);
    for (const b of this.bars) b.applyMarks(this.marks[b.data.spec.name]);
    this.requestRender();
    this.updateToolbar();
  }

  // ------------------------------------------------------------------ data

  async setSpec(spec: SceneSpec, source: DataSource): Promise<void> {
    const token = ++this.loadToken;
    const t0 = performance.now();
    const ids = specBufferIds(spec);
    if (ids.some((id) => !source.has(id))) this.setStatus("Loading…");
    await source.ensure(ids);
    if (token !== this.loadToken) return;
    if (ids.some((id) => !source.has(id))) return; // a newer spec freed them
    if (this.status === "Loading…") this.setStatus(null);
    const firstSpec = !this.spec;
    const oldExtent = this.spec?.time.extent;
    this.spec = spec;
    this.axis = new TimeAxis(spec.time);
    this.layers = spec.layers.filter((ls): ls is EventsLayerSpec => ls.type === "events").map((ls) => this.makeLayer(decodeEvents(ls, source)));
    this.bars = spec.layers
      .filter((ls): ls is IntervalsLayerSpec => ls.type === "intervals")
      .map((ls) => {
        const b = new BarLayer(decodeBars(ls, source), this.theme.accent);
        b.applyMarks(this.marks[ls.name]);
        return b;
      });
    this.values = spec.layers
      .filter((ls): ls is ValuesLayerSpec => ls.type === "values")
      .map((ls) => new ValueLayer(decodeValues(ls, source), this.theme.accent));
    this.hovered = null;
    this.initRows(spec);
    this.seqTimes = spec.sequence ? (new Float64Array(source.get(spec.sequence.times.id))) : null;
    this.gaps = findGaps(this.seqTimes);
    this.renderer?.retain(new Set([...this.layers.map((l) => l.draw.key), ...this.bars.map((b) => b.draw.key)]));
    const orderOnly = spec.time.kind === "order";
    if (orderOnly && this.xscale === "time") this.xscale = "sequence";
    this.legendEl?.remove();
    this.legendEl = buildLegend(spec.layers, this.theme.accent);
    if (this.legendEl) {
      this.legendEl.style.display = this.showLegend ? "" : "none";
      this.stage.append(this.legendEl);
    }
    const counts: string[] = [];
    const events = spec.layers.reduce((n, l) => n + (l.type === "events" ? l.count : 0), 0);
    if (events || (!this.bars.length && !this.values.length)) counts.push(`${fmtNumber(events)} event${events === 1 ? "" : "s"}`);
    for (const b of this.bars) counts.push(`${fmtNumber(b.data.count)} ${b.data.spec.name}`);
    for (const v of this.values) counts.push(`${fmtNumber(v.data.count)} samples`);
    const lanes = spec.lanes.names.length;
    const groups = spec.lanes.tree?.header?.length ?? 0;
    if (groups) counts.push(`${fmtNumber(groups)} group${groups === 1 ? "" : "s"}`);
    else if (!spec.lanes.tree) counts.push(`${fmtNumber(lanes)} lane${lanes === 1 ? "" : "s"}`);
    this.infoText = counts.join(" · ");
    this.updateToolbar();
    const sameExtent = oldExtent && oldExtent[0] === spec.time.extent[0] && oldExtent[1] === spec.time.extent[1];
    this.layout();
    this.setLimits();
    if (firstSpec || !sameExtent) {
      this.camera.fitExtent();
      this.history = [];
      this.adoptLinkedRange();
    }
    for (const p of this.link ? others(this.link.peer) : []) p.relayout();
    this.rebase(true);
    this.updateToolbar();
    this.firstFrameAt = performance.now() - t0;
    this.callbacks.onPerf?.({ load_ms: Math.round(this.firstFrameAt) });
    this.requestRender();
  }

  private infoText = "";

  private makeLayer(data: EventsData): Layer {
    const n = data.count;
    if (data.themeColor) fillSolid(data.color, this.theme.accent, data.spec.color.alpha);
    const sf = new Uint8Array(n * 4);
    for (let i = 0; i < n; i++) sf[4 * i] = data.symbol[i];
    const key = data.spec.time.id + data.spec.name;
    const draw: MarkLayerDraw = {
      key,
      count: n,
      x: { data: new Float32Array(n), version: 0 },
      lane: { data: rowsOf(data.lane, this.slot), version: 0 },
      dy: { data: new Float32Array(n), version: 0 },
      size: { data: data.size, version: 0 },
      color: { data: data.color, version: 0 },
      sf: { data: sf, version: 0 },
      offset: 0,
      scale: 1,
      laneTop: 0,
      laneHeight: this.laneH,
      fade: false,
      visible: new Uint32Array(n),
      visibleCount: 0,
    };
    const layer: Layer = { data, draw, xs: new Float64Array(n), dodged: null, baseSize: Float32Array.from(data.size) };
    if (this.markScale !== 1) this.scaleMarks(layer);
    this.applyMarks(layer);
    return layer;
  }

  /** Every array changed (a new renderer): upload them all again. */
  private bumpAll(l: Layer): void {
    for (const a of [l.draw.x, l.draw.lane, l.draw.dy, l.draw.size, l.draw.color, l.draw.sf]) a.version++;
  }

  private applyMarks(l: Layer): void {
    const sf = l.draw.sf.data;
    for (let i = 0; i < l.data.count; i++) sf[4 * i + 1] &= ~FLAG_SELECTED;
    const m = this.marks[l.data.spec.name];
    if (m) for (const i of m) if (i >= 0 && i < l.data.count) sf[4 * i + 1] |= FLAG_SELECTED;
    l.draw.sf.version++;
  }

  // ------------------------------------------------------------------ scales and camera

  /** x positions of a layer's events on the current scale. */
  private xsrc(l: Layer): Float64Array {
    return this.xscale === "sequence" ? l.data.rank : l.data.time;
  }

  private setLimits(): void {
    if (!this.spec) return;
    if (this.xscale === "sequence") {
      const n = this.spec.sequence?.count ?? 1;
      this.camera.setLimits([-0.5, Math.max(0.5, n - 0.5)], 1 / 200);
    } else {
      const t = this.spec.time;
      const per = UNIT_NS[t.unit] ?? 1;
      // one pixel shows at least 0.05 ns, or a billionth of the extent for plain numbers
      const min = t.kind === "number" ? Math.max(1e-300, (t.extent[1] - t.extent[0]) * 1e-9) : 0.05 / per;
      // linked: the time of the whole group, so this view can follow the others anywhere
      const extent: [number, number] = [t.extent[0], t.extent[1]];
      if (this.link) {
        const to = frameOf(t);
        for (const p of others(this.link.peer)) {
          const e = p.extent();
          const f = p.frame();
          if (!e || !f || !compatible(f, to, this.link.spec.align)) continue;
          extent[0] = Math.min(extent[0], convert(e[0], f, to, this.link.spec.align));
          extent[1] = Math.max(extent[1], convert(e[1], f, to, this.link.spec.align));
        }
      }
      this.camera.setLimits(extent, min);
    }
  }

  setXScale(xscale: XScale, fromUser = false): void {
    if (xscale === "sequence" && this.spec && !this.spec.sequence?.count) return; // samples only
    if (!this.spec || (xscale === "time" && this.spec.time.kind === "order")) {
      this.xscale = this.spec?.time.kind === "order" ? "sequence" : xscale;
      this.updateToolbar();
      return;
    }
    if (xscale === this.xscale) return;
    const [a, b] = [this.camera.left, this.camera.right];
    const seq = this.seqTimes;
    this.xscale = xscale;
    this.setLimits();
    if (seq && seq.length) {
      if (xscale === "sequence") {
        const r0 = lowerBound(seq, a);
        const r1 = upperBound(seq, b) - 1;
        if (r1 >= r0) this.camera.fit(r0 - 0.5, r1 + 0.5, 0);
        else this.camera.fitExtent();
      } else {
        const i0 = Math.max(0, Math.min(seq.length - 1, Math.floor(a + 0.5)));
        const i1 = Math.max(0, Math.min(seq.length - 1, Math.ceil(b - 0.5)));
        this.camera.fit(seq[i0], seq[i1], 0.02);
      }
    }
    for (const l of this.layers) l.dodged = null;
    this.rebase(true);
    this.updateToolbar();
    if (fromUser) this.callbacks.onXScale?.(xscale);
    this.requestRender();
    this.reportView();
  }

  /** Show a time range (ticks), from Python's zoom_to. */
  zoomTo(range: [number, number]): void {
    if (!this.spec) return;
    let [a, b] = range;
    if (this.xscale === "sequence" && this.seqTimes) {
      a = lowerBound(this.seqTimes, a) - 0.5;
      b = upperBound(this.seqTimes, b) - 0.5;
    }
    this.pushHistory();
    this.camera.fit(a, b, 0);
    this.afterMove();
  }

  resetView(): void {
    if (this.isZoomed()) this.pushHistory();
    this.camera.fitExtent();
    this.scrollY = 0;
    this.afterMove();
  }

  /**
   * Positions go to the GPU as float32 relative to a base near the view. Rebase when the
   * view has moved far from it (relative to its span), so float32 keeps sub-pixel precision.
   */
  private rebase(force = false): void {
    const center = this.camera.left + this.camera.span / 2;
    if (!force && Math.abs(center - this.base) < this.camera.span * 400) return;
    this.base = center;
    this.baseVersion++;
    for (const l of this.layers) {
      const src = this.xsrc(l);
      const x = l.draw.x.data;
      for (let i = 0; i < src.length; i++) x[i] = src[i] - this.base;
      l.draw.x.version = this.baseVersion * 1000 + 1;
    }
    for (const b of this.bars) b.rebase(this.base, this.xscale === "sequence", this.baseVersion * 1000 + 1);
  }

  private reportView(): void {
    clearTimeout(this.viewTimer);
    this.viewTimer = setTimeout(() => {
      let [a, b] = [this.camera.left, this.camera.right];
      if (this.xscale === "sequence" && this.seqTimes?.length) {
        const n = this.seqTimes.length;
        a = this.seqTimes[Math.max(0, Math.min(n - 1, Math.ceil(a)))];
        b = this.seqTimes[Math.max(0, Math.min(n - 1, Math.floor(b)))];
      }
      this.callbacks.onView?.([a, b]);
    }, 250);
  }

  // ------------------------------------------------------------------ layout

  /** Size the canvases to the plot; `dpr`: draw at this many pixels per CSS px (a snapshot). */
  private layout(dpr = window.devicePixelRatio || 1): void {
    const width = Math.max(120, Math.round(this.root.clientWidth || this.host.clientWidth || 600));
    const lanes = this.laneAt.length || 1;
    const headerH = this.header.offsetHeight || 30;
    const auto = this.axisH + PAD_BOTTOM + Math.min(560, Math.max(80, this.autoRows * AUTO_LANE));
    const full = this.isFullscreen();
    const stageH = full
      ? Math.max(120, (this.root.clientHeight || window.innerHeight) - headerH)
      : this.fixedHeight
        ? Math.max(120, this.fixedHeight - headerH)
        : auto;
    this.stage.style.height = `${stageH}px`;
    this.width = width;
    this.height = stageH;
    this.dpr = dpr;
    for (const c of [this.back, this.front]) {
      c.width = Math.round(width * dpr);
      c.height = Math.round(stageH * dpr);
      c.style.width = `${width}px`;
      c.style.height = `${stageH}px`;
    }
    if (this.renderer) {
      this.renderer.canvas.style.width = `${width}px`;
      this.renderer.canvas.style.height = `${stageH}px`;
      this.renderer.resize(width, stageH, dpr);
    }
    this.gutter = this.measureGutter();
    this.placeLegend();
    this.shareSizes();
    const plot = this.plot();
    // lanes fill the height (dodging then has room to spread ties); when they do not fit at
    // MIN_LANE they keep that height and scroll, with the top lane kept in view
    const topLane = this.scrollY / this.laneH;
    this.laneH = Math.max(this.minLane(), plot.h / Math.max(1, lanes));
    // a tree's lanes stay compact: folding and unfolding then only moves the lanes below
    if (this.spec?.lanes.tree?.compact) this.laneH = Math.max(this.minLane(), Math.min(this.laneH, Math.round(this.fs * 2.4)));
    this.scrollY = topLane * this.laneH;
    this.clampScroll();
    this.camera.setWidth(plot.w);
    this.setLimits();
    this.requestRender();
  }

  /** Linked plots take the widest lane names and legend of their group, so their time axes
   * line up; the others lay out again when this view's own sizes change. */
  private shareSizes(): void {
    const own = { gutter: this.gutter, padRight: this.padRight };
    const changed = own.gutter !== this.own.gutter || own.padRight !== this.own.padRight;
    this.own = own;
    if (!this.link) return;
    const peers = others(this.link.peer);
    for (const p of peers) {
      const s = p.sizes();
      this.gutter = Math.max(this.gutter, s.gutter);
      this.padRight = Math.max(this.padRight, s.padRight);
    }
    if (changed) for (const p of peers) p.relayout();
  }

  // ------------------------------------------------------------------ linking

  /** Join a group of linked plots (null: leave it). */
  setLink(spec: LinkSpec | null): void {
    if (spec && this.link && spec.group === this.link.spec.group && spec.align === this.link.spec.align) return;
    if (this.link) {
      const old = others(this.link.peer);
      leave(this.link.peer);
      this.link = null;
      for (const p of old) p.relayout();
    }
    this.linkedCursor = null;
    if (spec) {
      const peer = this.makePeer(spec.group);
      this.link = { spec, peer };
      join(peer);
      this.adoptLinkedRange();
    }
    this.setLimits();
    this.layout();
    for (const p of this.link ? others(this.link.peer) : []) p.relayout();
  }

  private makePeer(group: string): LinkPeer {
    return {
      group,
      frame: () => (this.spec ? frameOf(this.spec.time) : null),
      extent: () => (this.spec ? [this.spec.time.extent[0], this.spec.time.extent[1]] : null),
      range: () => (this.spec ? this.timeRange() : null),
      follow: (range, from, align) => this.followRange(range, from, align),
      cursor: (at, from, align) => this.followCursor(at, from, align),
      sizes: () => this.own,
      relayout: () => {
        this.setLimits();
        this.layout();
      },
    };
  }

  /** The time range shown, in ticks (on the Order scale: the times of the events at the edges). */
  private timeRange(): [number, number] {
    if (this.xscale !== "sequence" || !this.seqTimes?.length) return [this.camera.left, this.camera.right];
    return [this.timeAt(this.camera.left), this.timeAt(this.camera.right)];
  }

  /** The time at position x (ticks; on the Order scale interpolated between the events). */
  private timeAt(x: number): number {
    if (this.xscale !== "sequence" || !this.seqTimes?.length) return x;
    const seq = this.seqTimes;
    const i = Math.max(0, Math.min(seq.length - 1, Math.floor(x)));
    const j = Math.min(seq.length - 1, i + 1);
    const f = Math.max(0, Math.min(1, x - i));
    return seq[i] + (seq[j] - seq[i]) * f;
  }

  /** The position of time t (ticks) on the current scale. */
  private xAt(t: number): number {
    if (this.xscale !== "sequence" || !this.seqTimes?.length) return t;
    const seq = this.seqTimes;
    const j = lowerBound(seq, t);
    if (j <= 0) return -0.5;
    if (j >= seq.length) return seq.length - 0.5;
    const span = seq[j] - seq[j - 1];
    return j - 1 + (span > 0 ? (t - seq[j - 1]) / span : 1);
  }

  /** Tell the group which time range this view shows. */
  private shareRange(): void {
    if (!this.link || this.following || !this.spec) return;
    const from = frameOf(this.spec.time);
    const range = this.timeRange();
    for (const p of others(this.link.peer)) p.follow(range, from, this.link.spec.align);
  }

  private followRange(range: [number, number], from: LinkFrame, align: Align): void {
    if (!this.spec) return;
    const to = frameOf(this.spec.time);
    if (!compatible(from, to, align)) return;
    const a = this.xAt(convert(range[0], from, to, align));
    const b = this.xAt(convert(range[1], from, to, align));
    if (!(b > a)) return;
    this.following = true;
    this.camera.fit(a, b, 0);
    this.rebase();
    this.requestRender();
    this.reportView();
    this.updateToolbarSoon();
    this.following = false;
  }

  private followCursor(at: number | null, from: LinkFrame | null, align: Align): void {
    if (!this.spec || at === null || !from) {
      if (this.linkedCursor !== null) {
        this.linkedCursor = null;
        this.requestRender();
      }
      return;
    }
    const to = frameOf(this.spec.time);
    this.linkedCursor = compatible(from, to, align) ? convert(at, from, to, align) : null;
    this.requestRender();
  }

  /** Show the pointer's time in the other views of the group (null: it left the plot). */
  private shareCursor(px: number | null): void {
    if (!this.link || !this.spec) return;
    const at = px === null ? null : this.timeAt(this.camera.fromPx(px - this.plot().x));
    const from = frameOf(this.spec.time);
    for (const p of others(this.link.peer)) p.cursor(at, from, this.link.spec.align);
  }

  /** On joining a group, or new data: show what the group shows. */
  private adoptLinkedRange(): void {
    if (!this.link || !this.spec) return;
    for (const p of others(this.link.peer)) {
      const r = p.range();
      const f = p.frame();
      if (r && f) {
        this.followRange(r, f, this.link.spec.align);
        return;
      }
    }
  }

  /** The other views' pointer: a dashed line across the lanes. */
  private drawLinkedCursor(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }): void {
    if (this.linkedCursor === null) return;
    const x = Math.round(plot.x + this.camera.toPx(this.xAt(this.linkedCursor))) + 0.5;
    if (x < plot.x || x > plot.x + plot.w) return;
    ctx.save();
    ctx.strokeStyle = this.theme.muted;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x, plot.y);
    ctx.lineTo(x, plot.y + plot.h);
    ctx.stroke();
    ctx.restore();
  }

  /** The legend in a column right of the plot when there is room, else over the plot. */
  private placeLegend(): void {
    const legend = this.legendEl;
    this.padRight = PAD_RIGHT;
    if (!legend || !this.showLegend) return;
    const w = legend.offsetWidth;
    const column = this.width - this.gutter - w - 24 >= 360;
    legend.classList.toggle("atl-legend-column", column);
    legend.style.top = `${this.axisH}px`;
    if (column) this.padRight = w + 20;
  }

  private measureGutter(): number {
    if (this.spec?.lanes.show_names === false) return 12;
    const names = this.spec?.lanes.names ?? [];
    const tree = this.spec?.lanes.tree;
    const ctx = this.front.getContext("2d")!;
    ctx.font = this.font(0);
    let w = 0;
    for (let i = 0; i < Math.min(names.length, 2000); i++) {
      const indent = tree && i < tree.depth.length ? this.treeIndent(tree.depth[i]) : 0;
      w = Math.max(w, indent + ctx.measureText(names[i]).width);
    }
    return Math.round(Math.min(this.width * (tree ? 0.35 : 0.3), Math.max(48, w + 20)));
  }

  /** The header lanes of groups, or null. */
  private headerSet(): Set<number> | null {
    const h = this.spec?.lanes.tree?.header;
    if (!h?.length) return null;
    if (this.headers?.list !== h) this.headers = { list: h, set: new Set(h) };
    return this.headers.set;
  }

  private headers: { list: number[]; set: Set<number> } | null = null;

  /** Where a tree lane's name starts (after its fold triangle), in px from the left. */
  private treeIndent(depth: number): number {
    return 6 + depth * Math.round(this.fs * 0.9) + Math.round(this.fs * 1.1);
  }

  // ------------------------------------------------------------------ rows and folding

  /** The rows when a spec arrives: tree lanes open as the spec says, unless the same lanes
   * were shown before (a layer added, a marker set): then they stay as the user left them. */
  private initRows(spec: SceneSpec): void {
    const tree = spec.lanes.tree;
    const names = spec.lanes.names;
    const key = treeKey(spec);
    const same = key !== "" && key === this.rowKey;
    if (!same) this.open = tree ? Uint8Array.from(tree.open, (o) => (o ? 1 : 0)) : new Uint8Array(0);
    this.rowKey = key;
    this.computeRows(names.length);
    if (!same) {
      if (tree) this.scrollY = 0;
      this.autoRows = this.laneAt.length;
    }
  }

  private rowKey = "";

  private computeRows(n = this.spec?.lanes.names.length ?? 0): void {
    const tree = this.spec?.lanes.tree;
    const slot = new Int32Array(n).fill(-1);
    const at: number[] = [];
    for (let l = 0; l < n; ) {
      slot[l] = at.length;
      at.push(l);
      l += tree && l < tree.size.length && !this.open[l] ? tree.size[l] : 1;
    }
    this.laneAt = Int32Array.from(at);
    this.slot = slot;
    for (const l of this.layers) {
      l.draw.lane.data = rowsOf(l.data.lane, slot);
      l.draw.lane.version++;
      l.dodged = null;
    }
    for (const b of this.bars) b.setSlots(slot);
  }

  /** Fold or unfold a lane of the tree (`deep`: everything under it too). */
  toggleLane(lane: number, deep = false): void {
    const tree = this.spec?.lanes.tree;
    if (!tree || lane < 0 || lane >= tree.size.length || tree.size[lane] < 2) return;
    const open = this.open[lane] ? 0 : 1;
    this.open[lane] = open;
    if (deep) for (let k = lane + 1; k < lane + tree.size[lane]; k++) this.open[k] = open;
    this.computeRows();
    this.hovered = null;
    this.clampScroll();
    this.layout();
  }

  /** Unfold every lane of the tree, or fold them all to their roots. */
  expandAll(open: boolean): void {
    if (!this.spec?.lanes.tree) return;
    this.open.fill(open ? 1 : 0);
    this.computeRows();
    this.hovered = null;
    this.scrollY = 0;
    this.layout();
  }

  /** Whether a point is on the name of a lane that folds. */
  private foldableAt(p: { x: number; y: number }): boolean {
    const tree = this.spec?.lanes.tree;
    const plot = this.plot();
    if (!tree || p.x >= plot.x || p.y < plot.y || p.y > plot.y + plot.h) return false;
    const l = this.laneAtY(p.y);
    return l >= 0 && l < tree.size.length && tree.size[l] > 1;
  }

  /** The lane on the row at y (CSS px in the stage), or -1. */
  private laneAtY(y: number): number {
    const r = Math.floor((y - this.plot().y + this.scrollY) / this.laneH);
    return r >= 0 && r < this.laneAt.length ? this.laneAt[r] : -1;
  }

  private plot(): { x: number; y: number; w: number; h: number } {
    return { x: this.gutter, y: this.axisH, w: Math.max(10, this.width - this.gutter - this.padRight), h: Math.max(10, this.height - this.axisH - PAD_BOTTOM) };
  }

  private clampScroll(): void {
    const max = Math.max(0, this.laneAt.length * this.laneH - this.plot().h);
    this.scrollY = Math.max(0, Math.min(max, this.scrollY));
  }

  // ------------------------------------------------------------------ theme

  private readTheme(): Theme {
    const s = getComputedStyle(this.root);
    const v = (name: string, fallback: string) => s.getPropertyValue(name).trim() || fallback;
    return {
      bg: v("--atl-bg", "#ffffff"),
      text: v("--atl-text", "#1b2430"),
      muted: v("--atl-muted", "#5e6875"),
      grid: v("--atl-grid", "#e6e9ed"),
      band: v("--atl-band", "#f6f7f9"),
      select: v("--atl-select", "#e8590c"),
      accent: v("--atl-accent", "#1f77b4"),
    };
  }

  refreshTheme(): void {
    const old = this.theme.accent;
    this.theme = this.readTheme();
    if (this.theme.accent !== old) {
      for (const l of this.layers) {
        if (l.data.themeColor) {
          fillSolid(l.data.color, this.theme.accent, l.data.spec.color.alpha);
          l.draw.color.version++;
        }
      }
      for (const b of this.bars) b.recolor(this.theme.accent);
      for (const v of this.values) v.recolor(this.theme.accent);
    }
    this.requestRender();
  }

  // ------------------------------------------------------------------ frame

  requestRender(): void {
    if (this.frameRequested) return;
    this.frameRequested = true;
    const run = () => {
      this.frameRequested = false;
      this.renderFrame();
    };
    if (document.hidden) setTimeout(run, 16);
    else requestAnimationFrame(run);
  }

  private renderFrame(): void {
    const t0 = performance.now();
    this.info.textContent = [this.infoText, this.renderer?.kind ?? ""].filter(Boolean).join(" · ");
    const plot = this.plot();
    const backCtx = this.back.getContext("2d")!;
    const frontCtx = this.front.getContext("2d")!;
    backCtx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    frontCtx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    backCtx.fillStyle = this.theme.bg;
    backCtx.fillRect(0, 0, this.width, this.height);
    frontCtx.clearRect(0, 0, this.width, this.height);
    if (!this.spec || !this.axis) {
      this.renderer?.render({ plot, bars: [], segments: [], layers: [], background: [1, 1, 1], selection: [1, 0, 0], hover: [0, 0, 0] });
      return;
    }
    this.rebase();
    const laneTop = plot.y - this.scrollY;
    // rows in view (with folded lanes, a row is not the lane of the same number)
    const l0 = Math.max(0, Math.floor((plot.y - laneTop) / this.laneH));
    const l1 = Math.min(this.laneAt.length - 1, Math.floor((plot.y + plot.h - laneTop) / this.laneH));

    // lane bands and grid lines
    backCtx.save();
    backCtx.beginPath();
    backCtx.rect(0, plot.y, this.width, plot.h);
    backCtx.clip();
    const headers = this.headerSet();
    for (let l = l0; l <= l1; l++) {
      if (headers?.has(this.laneAt[l])) {
        // a group's header: a tinted band with a line above it
        backCtx.fillStyle = this.theme.grid;
        backCtx.globalAlpha = 0.55;
        backCtx.fillRect(0, laneTop + l * this.laneH, this.width, this.laneH);
        backCtx.globalAlpha = 1;
        backCtx.fillStyle = this.theme.muted;
        backCtx.fillRect(0, Math.round(laneTop + l * this.laneH), this.width, 1);
      } else if (l % 2 === 1) {
        backCtx.fillStyle = this.theme.band;
        backCtx.fillRect(0, laneTop + l * this.laneH, this.width, this.laneH);
      }
    }
    const ticks = this.ticks(plot.w);
    const gaps = this.xscale === "sequence" ? this.visibleGaps(frontCtx, plot, ticks.pinned) : [];
    if (gaps.length) {
      backCtx.strokeStyle = this.theme.grid;
      backCtx.setLineDash([2, 3]);
      backCtx.beginPath();
      for (const g of gaps) {
        backCtx.moveTo(Math.round(g.x) + 0.5, plot.y);
        backCtx.lineTo(Math.round(g.x) + 0.5, plot.y + plot.h);
      }
      backCtx.stroke();
      backCtx.setLineDash([]);
    }
    backCtx.strokeStyle = this.theme.grid;
    backCtx.lineWidth = 1;
    backCtx.beginPath();
    for (const t of ticks.minor) {
      const x = Math.round(plot.x + this.camera.toPx(t.x)) + 0.5;
      backCtx.moveTo(x, plot.y);
      backCtx.lineTo(x, plot.y + plot.h);
    }
    backCtx.stroke();
    if (this.layers.some(isStems)) {
      // a story's line through the middle of each lane
      backCtx.fillStyle = this.theme.muted;
      backCtx.globalAlpha = 0.5;
      for (let r = l0; r <= l1; r++) backCtx.fillRect(plot.x, Math.round(laneTop + (r + 0.5) * this.laneH) - 1, plot.w, 2);
      backCtx.globalAlpha = 1;
    }
    if (this.values.length) {
      const vv = this.valueView(plot);
      for (const v of this.values) v.draw(backCtx, vv, l0, l1);
    }
    backCtx.restore();

    // cull, dodge, routes
    const frame: FrameDraw = {
      plot,
      bars: [],
      segments: [],
      layers: [],
      background: rgb01(this.theme.bg),
      selection: rgb01(this.theme.select),
      hover: rgb01(this.theme.text),
    };
    const fade = Object.values(this.marks).some((m) => m.length > 0);
    let inView = 0;
    const bv = this.barView(plot);
    const seqScale = this.xscale === "sequence";
    for (const b of this.bars) {
      b.cull(this.laneAt, l0, l1, this.camera.left - 2 / this.camera.scale, this.camera.right + 2 / this.camera.scale, seqScale);
      inView += b.draw.visibleCount;
      const d = b.draw;
      d.offset = this.camera.left - this.base;
      d.scale = this.camera.scale;
      d.laneTop = laneTop;
      d.laneHeight = this.laneH;
      d.maxBar = b.maxBar(bv.maxBar);
      d.fade = fade;
      frame.bars.push(d);
    }
    for (const l of this.layers) {
      this.cull(l, l0, l1, plot.w);
      inView += l.draw.visibleCount;
      if (l.data.spec.overlap === "dodge" && this.dodgeOn && !isStems(l)) this.dodgeLayer(l, l0, l1);
      const d = l.draw;
      d.offset = this.camera.left - this.base;
      d.scale = this.camera.scale;
      d.laneTop = laneTop;
      d.laneHeight = this.laneH;
      d.fade = fade;
      frame.layers.push(d);
      const seg = this.segments(l, plot, laneTop, l0, l1);
      if (seg) frame.segments.push(seg);
    }
    this.renderer?.render(frame);

    // front: axis, lane names, labels, gaps, hover, box
    this.drawAxis(frontCtx, plot, ticks);
    this.drawLanes(frontCtx, plot, laneTop, l0, l1);
    this.drawBarText(frontCtx, bv, l0, l1, inView <= LABEL_BUDGET);
    this.drawStems(frontCtx, plot, laneTop, l0, l1);
    if (inView <= LABEL_BUDGET) this.drawLabels(frontCtx, plot, laneTop);
    this.drawMarkers(frontCtx, plot);
    this.drawValueScales(frontCtx, plot, l0, l1);
    this.drawLinkedCursor(frontCtx, plot);
    if (gaps.length) this.drawGaps(frontCtx, plot, gaps);
    this.drawHover(frontCtx, plot, laneTop);
    if (this.box) this.drawBox(frontCtx, plot, this.box);
    this.callbacks.onPerf?.({ frame_ms: Math.round((performance.now() - t0) * 100) / 100, in_view: inView });
  }

  private ticks(width: number) {
    if (this.xscale === "sequence" || !this.axis) {
      const order = new TimeAxis({ kind: "order", unit: "", origin_ns: "0", origin: 0, timezone: "UTC", extent: [0, 1] });
      const t = order.ticks(this.camera.left, this.camera.right, (width * 11) / (this.fs - 1));
      // the time of the first event in view gives the context
      if (this.seqTimes?.length && this.axis && this.spec?.time.kind !== "order") {
        const i = Math.max(0, Math.min(this.seqTimes.length - 1, Math.ceil(this.camera.left)));
        t.pinned = `from ${this.axis.formatFull(this.seqTimes[i])}`;
      }
      return t;
    }
    return this.axis.ticks(this.camera.left, this.camera.right, (width * 11) / (this.fs - 1));
  }

  /** Collect the events in view (lanes l0..l1, x within the view plus a margin). */
  private cull(l: Layer, l0: number, l1: number, width: number): void {
    const src = this.xsrc(l);
    const starts = l.data.laneStarts;
    const margin = 12 / this.camera.scale;
    const a = this.camera.left - margin;
    const b = this.camera.left + width / this.camera.scale + margin;
    const vis = l.draw.visible;
    let n = 0;
    for (let r = l0; r <= l1 && r < this.laneAt.length; r++) {
      const lane = this.laneAt[r];
      if (lane + 1 >= starts.length) continue;
      const i0 = lowerBound(src, a, starts[lane], starts[lane + 1]);
      const i1 = upperBound(src, b, i0, starts[lane + 1]);
      for (let i = i0; i < i1; i++) {
        vis[n++] = i;
        l.xs[i] = (src[i] - this.camera.left) * this.camera.scale;
      }
    }
    l.draw.visibleCount = n;
  }

  /** Spread overlapping events of each lane over sub-rows; only when the scale or range changed. */
  private dodgeLayer(l: Layer, l0: number, l1: number): void {
    const cam = this.camera;
    const d = l.dodged;
    if (d && d.scale === cam.scale && d.laneH === this.laneH && cam.left >= d.left && cam.right <= d.right) return;
    const src = this.xsrc(l);
    const starts = l.data.laneStarts;
    const span = cam.span;
    const a = cam.left - span;
    const b = cam.right + span;
    const sizes = l.data.size;
    let maxSize = 1;
    const dy = l.draw.dy.data;
    dy.fill(0);
    const order: number[] = [];
    // dodge every lane in a wider range than the view, so panning needs no new pass
    for (let r = Math.max(0, l0 - 2); r <= l1 + 2 && r < this.laneAt.length; r++) {
      const lane = this.laneAt[r];
      if (lane + 1 >= starts.length) continue;
      const i0 = lowerBound(src, a, starts[lane], starts[lane + 1]);
      const i1 = upperBound(src, b, i0, starts[lane + 1]);
      for (let i = i0; i < i1; i++) {
        l.xs[i] = (src[i] - cam.left) * cam.scale;
        maxSize = Math.max(maxSize, sizes[i]);
      }
      order.push(i0, i1);
    }
    // the most sub-rows the lanes hold (at the closest spacing); dodge in sub-rows, then space
    // the rows the events needed as far apart as the lanes allow (one spacing for all lanes,
    // so a column's height still compares between lanes)
    const rows = rowsFor(this.laneH, maxSize, spacing(this.laneH, maxSize, Infinity));
    for (let k = 0; k < order.length; k += 2) dodge(l.xs, order[k], order[k + 1], maxSize * 0.85, rows, 1, dy);
    let pairs = 0;
    for (let k = 0; k < order.length; k += 2) for (let i = order[k]; i < order[k + 1]; i++) pairs = Math.max(pairs, Math.abs(dy[i]));
    const step = spacing(this.laneH, maxSize, pairs);
    for (let k = 0; k < order.length; k += 2) for (let i = order[k]; i < order[k + 1]; i++) dy[i] *= step;
    l.draw.dy.version++;
    l.dodged = { left: a, right: b, scale: cam.scale, laneH: this.laneH };
  }

  private segments(l: Layer, plot: { x: number; y: number; w: number; h: number }, laneTop: number, l0: number, l1: number): SegmentDraw | null {
    const route = l.data.spec.route;
    const seg = l.data.segments;
    if (!route || !seg || !route.count) return null;
    const src = this.xsrc(l);
    const lane = l.data.lane;
    const dy = l.draw.dy.data;
    const color = l.data.color;
    const solid = route.color ? (route.color === "theme" ? parseHex(this.theme.text) : parseHex(route.color)) : null;
    const coords = new Float32Array(Math.min(route.count, ROUTE_BUDGET) * 4);
    const colors = new Uint8Array(coords.length);
    const cam = this.camera;
    let n = 0;
    const right = cam.left + plot.w / cam.scale;
    for (let k = 0; k < route.count && n < ROUTE_BUDGET; k++) {
      const i = seg[2 * k];
      const j = seg[2 * k + 1];
      const xa = src[i];
      const xb = src[j];
      if ((xa < cam.left && xb < cam.left) || (xa > right && xb > right)) continue;
      const la = this.slot[lane[i]];
      const lb = this.slot[lane[j]];
      if (la < 0 || lb < 0) continue; // a folded lane
      if ((la < l0 && lb < l0) || (la > l1 && lb > l1)) continue;
      coords[4 * n] = plot.x + (xa - cam.left) * cam.scale;
      coords[4 * n + 1] = laneTop + (la + 0.5) * this.laneH + dy[i];
      coords[4 * n + 2] = plot.x + (xb - cam.left) * cam.scale;
      coords[4 * n + 3] = laneTop + (lb + 0.5) * this.laneH + dy[j];
      if (solid) {
        colors[4 * n] = solid[0];
        colors[4 * n + 1] = solid[1];
        colors[4 * n + 2] = solid[2];
      } else {
        colors[4 * n] = color[4 * i];
        colors[4 * n + 1] = color[4 * i + 1];
        colors[4 * n + 2] = color[4 * i + 2];
      }
      colors[4 * n + 3] = 140;
      n++;
    }
    return { count: n, coords, colors, width: route.width };
  }

  // ------------------------------------------------------------------ front canvas

  private drawAxis(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, ticks: ReturnType<TimeAxis["ticks"]>): void {
    ctx.save();
    ctx.fillStyle = this.theme.bg;
    ctx.fillRect(0, 0, this.width, this.axisH);
    ctx.strokeStyle = this.theme.muted;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(plot.x, this.axisH - 0.5);
    ctx.lineTo(plot.x + plot.w, this.axisH - 0.5);
    ctx.stroke();
    ctx.beginPath();
    ctx.rect(plot.x, 0, plot.w, this.axisH);
    ctx.clip();
    ctx.font = this.font(-1);
    ctx.fillStyle = this.theme.text;
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "center";
    ctx.beginPath();
    let lastEnd = -Infinity;
    for (const t of ticks.minor) {
      const x = plot.x + this.camera.toPx(t.x);
      ctx.moveTo(Math.round(x) + 0.5, this.axisH - 5);
      ctx.lineTo(Math.round(x) + 0.5, this.axisH);
      const w = ctx.measureText(t.label).width;
      // a label is shown whole: at the edges it moves inward, as long as it still covers its
      // tick; a tick off the plot gets no label
      if (x < plot.x || x > plot.x + plot.w) continue;
      const cx = Math.min(plot.x + plot.w - w / 2, Math.max(plot.x + w / 2, x));
      if (cx - w / 2 > lastEnd + 6) {
        ctx.fillText(t.label, cx, this.axisH - Math.round(this.fs * 0.75));
        lastEnd = cx + w / 2;
      }
    }
    ctx.strokeStyle = this.theme.muted;
    ctx.stroke();
    // context row: boundaries, and the unit of the left edge pinned there
    ctx.font = this.font(-1);
    ctx.fillStyle = this.theme.muted;
    ctx.textAlign = "left";
    const y = Math.round(this.fs * 1.25);
    let pinnedEnd = plot.x + 4 + ctx.measureText(ticks.pinned).width;
    const firstBoundary = ticks.context.length ? plot.x + this.camera.toPx(ticks.context[0].x) : Infinity;
    if (ticks.pinned && firstBoundary > pinnedEnd + 8) ctx.fillText(ticks.pinned, plot.x + 4, y);
    else pinnedEnd = -Infinity;
    for (const c of ticks.context) {
      const x = plot.x + this.camera.toPx(c.x);
      ctx.fillRect(Math.round(x), 4, 1, Math.round(this.fs * 1.17));
      ctx.fillText(c.label, x + 4, y);
    }
    ctx.restore();
  }

  private drawLanes(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number, l0: number, l1: number): void {
    if (this.spec!.lanes.show_names === false) return;
    const names = this.spec!.lanes.names;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, plot.y, plot.x, plot.h);
    ctx.clip();
    ctx.font = this.font(0);
    ctx.fillStyle = this.theme.text;
    ctx.textBaseline = "middle";
    ctx.textAlign = "right";
    const tree = this.spec!.lanes.tree;
    const tri = Math.max(3, Math.round(this.fs * 0.32));
    for (let r = l0; r <= l1; r++) {
      const l = this.laneAt[r];
      const y = laneTop + (r + 0.5) * this.laneH;
      if (!tree || l >= tree.depth.length) {
        ctx.font = this.font(0);
        ctx.textAlign = "right";
        ctx.fillText(ellipsize(ctx, names[l], plot.x - 12), plot.x - 8, y);
        continue;
      }
      // a tree: names indented by depth, a triangle to fold the lanes under them
      const x = this.treeIndent(tree.depth[l]);
      if (tree.size[l] > 1) {
        const cx = x - Math.round(this.fs * 0.6);
        ctx.beginPath();
        if (this.open[l]) {
          ctx.moveTo(cx - tri, y - tri * 0.6);
          ctx.lineTo(cx + tri, y - tri * 0.6);
          ctx.lineTo(cx, y + tri * 0.8);
        } else {
          ctx.moveTo(cx - tri * 0.6, y - tri);
          ctx.lineTo(cx + tri * 0.8, y);
          ctx.lineTo(cx - tri * 0.6, y + tri);
        }
        ctx.closePath();
        ctx.fillStyle = this.theme.muted;
        ctx.fill();
        ctx.fillStyle = this.theme.text;
      }
      ctx.textAlign = "left";
      const header = this.headerSet()?.has(l) ?? false;
      ctx.font = header ? `600 ${this.fs}px ${fontFamily}` : this.font(0);
      const room = plot.x - 8 - x;
      let name = ellipsize(ctx, names[l], room);
      if (!this.open[l] && tree.size[l] > 1) {
        // folded: how many lanes it hides, when there is room
        const more = ` +${fmtNumber(tree.size[l] - 1)}`;
        if (ctx.measureText(name + more).width <= room && name === names[l]) {
          ctx.fillText(name, x, y);
          ctx.fillStyle = this.theme.muted;
          ctx.fillText(more, x + ctx.measureText(name).width, y);
          ctx.fillStyle = this.theme.text;
          continue;
        }
        name = ellipsize(ctx, names[l], room);
      }
      ctx.fillText(name, x, y);
    }
    ctx.restore();
    if (this.spec!.lanes.title) {
      ctx.save();
      ctx.font = this.font(-1);
      ctx.fillStyle = this.theme.muted;
      ctx.textAlign = "right";
      ctx.fillText(ellipsize(ctx, this.spec!.lanes.title, plot.x - 12), plot.x - 8, this.axisH - Math.round(this.fs * 0.75));
      ctx.restore();
    }
    // a scroll hint when lanes do not fit
    const total = this.laneAt.length * this.laneH;
    if (total > plot.h + 1) {
      const frac = plot.h / total;
      const top = plot.y + (this.scrollY / total) * plot.h;
      ctx.fillStyle = this.theme.grid;
      ctx.fillRect(this.width - 5, plot.y, 3, plot.h);
      ctx.fillStyle = this.theme.muted;
      ctx.fillRect(this.width - 5, top, 3, Math.max(12, frac * plot.h));
    }
  }

  private drawLabels(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number): void {
    ctx.save();
    ctx.beginPath();
    ctx.rect(plot.x, plot.y, plot.w, plot.h);
    ctx.clip();
    ctx.font = this.font(-1);
    ctx.textBaseline = "middle";
    ctx.fillStyle = this.theme.text;
    ctx.strokeStyle = this.theme.bg;
    ctx.lineWidth = 3;
    ctx.lineJoin = "round";
    for (const l of this.layers) {
      if (isStems(l) && this.stemsFit.get(l) !== false) continue; // in boxes on stems
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
        const y = laneTop + (this.slot[l.data.lane[i]] + 0.5) * this.laneH + l.draw.dy.data[i];
        const w = ctx.measureText(label).width;
        const half = this.fs / 2;
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
  private visibleGaps(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, pinned: string): { x: number; label: string | null }[] {
    if (!this.gaps.length || !this.axis) return [];
    const i0 = lowerBoundBy(this.gaps, this.camera.left);
    const candidates: { x: number; span: number }[] = [];
    for (let k = i0; k < this.gaps.length && this.gaps[k].at <= this.camera.right; k++) {
      const x = plot.x + this.camera.toPx(this.gaps[k].at);
      if (x > plot.x + 4 && x < plot.x + plot.w - 4) candidates.push({ x, span: this.gaps[k].span });
    }
    candidates.sort((a, b) => b.span - a.span);
    ctx.save();
    ctx.font = this.font(-1);
    const labelsFrom = pinned ? plot.x + 4 + ctx.measureText(pinned).width + 12 : plot.x;
    const shown: { x: number; label: string | null }[] = [];
    const labelled: [number, number][] = [];
    for (const c of candidates) {
      if (shown.some((g) => Math.abs(g.x - c.x) < GAP_PX)) continue;
      const text = this.axis.formatSpan(c.span);
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
  private drawGaps(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, gaps: { x: number; label: string | null }[]): void {
    ctx.save();
    ctx.beginPath();
    ctx.rect(plot.x, 0, plot.w, this.axisH + 4);
    ctx.clip();
    ctx.strokeStyle = this.theme.muted;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    const y = this.axisH - 1;
    for (const { x } of gaps) {
      ctx.moveTo(x - 4, y + 3);
      ctx.lineTo(x - 1, y - 3);
      ctx.moveTo(x + 1, y + 3);
      ctx.lineTo(x + 4, y - 3);
    }
    ctx.stroke();
    ctx.font = this.font(-1);
    ctx.textAlign = "center";
    ctx.fillStyle = this.theme.muted;
    const top = Math.round(this.fs * 1.25);
    for (const g of gaps) if (g.label) ctx.fillText(g.label, g.x, top);
    ctx.restore();
  }

  /** A zoom range (a band in the text colour) or a selection (dashed, in the selection colour). */
  private drawBox(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, b: Box): void {
    const x0 = Math.max(plot.x, Math.min(b.x0, b.x1));
    const x1 = Math.min(plot.x + plot.w, Math.max(b.x0, b.x1));
    ctx.save();
    if (b.kind === "select") {
      const y0 = Math.max(plot.y, Math.min(b.y0, b.y1));
      const y1 = Math.min(plot.y + plot.h, Math.max(b.y0, b.y1));
      ctx.strokeStyle = this.theme.select;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(Math.round(x0) + 0.5, Math.round(y0) + 0.5, x1 - x0, y1 - y0);
    } else {
      const color = b.kind === "range-select" ? this.theme.select : this.theme.text;
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
      if (this.axis && x1 - x0 >= MIN_BOX) {
        // how long the range is
        const span = this.camera.fromPx(x1 - plot.x) - this.camera.fromPx(x0 - plot.x);
        const label = this.xscale === "sequence" ? `${fmtNumber(Math.round(span))} events` : this.axis.formatSpan(span);
        ctx.font = this.font(-1);
        ctx.textAlign = "center";
        ctx.fillStyle = this.theme.bg;
        const w = ctx.measureText(label).width + 8;
        const cx = (x0 + x1) / 2;
        ctx.fillRect(cx - w / 2, plot.y + 4, w, this.fs + 5);
        ctx.fillStyle = color;
        ctx.fillText(label, cx, plot.y + 4 + this.fs);
      }
    }
    ctx.restore();
  }

  /** Boxes of stem labels as drawn in the last frame (for picking). */
  private stemHits: { layer: number; index: number; x0: number; y0: number; x1: number; y1: number }[] = [];
  /** Per stems layer: whether its lanes have room for a level of boxes (else its text goes
   * beside the marks). */
  private stemsFit = new WeakMap<Layer, boolean>();
  /** Per stems layer: the boxes laid out for a view (kept while only panning). */
  private stemCache = new WeakMap<Layer, { key: string; left: number; a: number; b: number; boxH: number; placed: Map<number, StemPlaced[]> }>();

  /** The text of stems layers in boxes above and below their lanes' lines, joined to the
   * events by stems; laid out again when the zoom, lane height or text changes, over three
   * view widths so panning keeps the boxes where they are. */
  private drawStems(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number, l0: number, l1: number): void {
    this.stemHits = [];
    const cam = this.camera;
    this.layers.forEach((l, li) => {
      if (!isStems(l) || !l.data.text) return;
      const text = l.data.text;
      const lineH = Math.round(this.fs * 1.25);
      const lines = (i: number) => (text[i] ?? "").split("\n");
      // a box's height: its lines; one height for all, so levels are rows
      let most = 1;
      for (let i = 0; i < l.data.count; i++) most = Math.max(most, lines(i).length);
      const boxH = most * lineH + 6;
      const gap = 6;
      let markR = 2;
      for (let i = 0; i < Math.min(l.data.count, 1000); i++) markR = Math.max(markR, l.data.size[i] / 2);
      const start = markR + 10;
      const levels = levelsFor(this.laneH, boxH, gap, start);
      this.stemsFit.set(l, levels > 0);
      if (levels === 0) return; // too little room: the text goes beside the marks
      const src = this.xsrc(l);
      const key = [cam.scale, this.laneH, this.fs, this.xscale, levels, this.laneAt.length, l0, l1].join(":");
      let cache = this.stemCache.get(l);
      if (!cache || cache.key !== key || cam.left < cache.a || cam.right > cache.b) {
        const span = cam.span;
        const a = cam.left - span;
        const b = cam.right + span;
        ctx.font = this.font(-1);
        const placed = new Map<number, StemPlaced[]>();
        const starts = l.data.laneStarts;
        for (let r = Math.max(0, l0 - 1); r <= l1 + 1 && r < this.laneAt.length; r++) {
          const lane = this.laneAt[r];
          if (lane + 1 >= starts.length) continue;
          const i0 = lowerBound(src, a, starts[lane], starts[lane + 1]);
          const i1 = upperBound(src, b, i0, starts[lane + 1]);
          const items: StemItem[] = [];
          for (let i = i0; i < i1; i++) {
            if (!text[i]) continue;
            const w = Math.max(...lines(i).map((s) => ctx.measureText(s).width)) + 14;
            items.push({ index: i, x: (src[i] - cam.left) * cam.scale, w, importance: l.data.importance?.[i] ?? 0 });
          }
          // boxes may reach past the view (they are laid out wider than it), not past the data
          const ext = this.xscale === "sequence" ? [-0.5, (this.seqTimes?.length ?? 1) - 0.5] : this.spec!.time.extent;
          const left = (Math.max(a, ext[0]) - cam.left) * cam.scale;
          const right = Math.max(left, (Math.min(b, ext[1]) - cam.left) * cam.scale);
          placed.set(r, placeStems(items, { levels, gap, inset: 8, left, right }));
        }
        cache = { key, left: cam.left, a, b, boxH, placed };
        this.stemCache.set(l, cache);
      }
      const shift = (cache.left - cam.left) * cam.scale;
      ctx.save();
      ctx.beginPath();
      ctx.rect(plot.x, plot.y, plot.w, plot.h);
      ctx.clip();
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      const sf = l.draw.sf.data;
      const color = l.data.color;
      const shown: { p: StemPlaced; cy: number; x0: number; top: number }[] = [];
      for (const [r, boxes] of cache.placed) {
        if (r < l0 || r > l1) continue;
        const cy = laneTop + (r + 0.5) * this.laneH;
        for (const p of boxes) {
          const x0 = plot.x + p.x0 + shift;
          if (x0 > plot.x + plot.w || x0 + p.w < plot.x) continue;
          shown.push({ p, cy, x0, top: cy + levelOffset(p.level, boxH, gap, start) - boxH / 2 });
        }
      }
      // the stems first, from each event to its box: boxes go over the stems they cross
      ctx.strokeStyle = this.theme.muted;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (const { p, cy, top } of shown) {
        const x = Math.round(plot.x + p.x + shift) + 0.5;
        ctx.moveTo(x, cy + (p.level > 0 ? -markR - 1 : markR + 1));
        ctx.lineTo(x, p.level > 0 ? top + boxH : top);
      }
      ctx.stroke();
      for (const { p, x0, top } of shown) {
        {
          const i = p.index;
          // the box, with the event's colour along its left side
          const selected = (sf[4 * i + 1] & FLAG_SELECTED) !== 0;
          const hovered = this.hovered && !this.hovered.bar && !this.hovered.val && this.hovered.layer === li && this.hovered.index === i;
          ctx.fillStyle = this.theme.bg;
          ctx.strokeStyle = selected ? this.theme.select : hovered ? this.theme.text : this.theme.grid;
          ctx.lineWidth = selected || hovered ? 1.5 : 1;
          ctx.beginPath();
          if (ctx.roundRect) ctx.roundRect(x0 + 0.5, top + 0.5, p.w, boxH, 3);
          else ctx.rect(x0 + 0.5, top + 0.5, p.w, boxH);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = `rgba(${color[4 * i]},${color[4 * i + 1]},${color[4 * i + 2]},${(color[4 * i + 3] || 255) / 255})`;
          ctx.fillRect(x0 + 1, top + 1, 3, boxH - 1);
          const ls = lines(i);
          ls.forEach((line, k) => {
            const first = k === 0 && ls.length > 1;
            ctx.font = first ? this.font(-2) : this.font(-1);
            ctx.fillStyle = first ? this.theme.muted : this.theme.text;
            ctx.fillText(line, x0 + 8, top + 3 + lineH * (k + 0.5));
          });
          this.stemHits.push({ layer: li, index: i, x0, y0: top, x1: x0 + p.w, y1: top + boxH });
        }
      }
      ctx.restore();
    });
  }

  /** What the values layers need of the frame. */
  private valueView(plot = this.plot()): ValueView {
    return {
      left: this.camera.left,
      scale: this.camera.scale,
      plot,
      laneTop: plot.y - this.scrollY,
      laneH: this.laneH,
      slot: this.slot,
      sequence: this.xscale === "sequence",
      seqTimes: this.seqTimes,
    };
  }

  /** Each values lane's high and low, small at the left of its band. */
  private drawValueScales(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, l0: number, l1: number): void {
    if (!this.values.length) return;
    ctx.save();
    ctx.beginPath();
    ctx.rect(plot.x, plot.y, plot.w, plot.h);
    ctx.clip();
    ctx.font = this.font(-3);
    ctx.fillStyle = this.theme.muted;
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    const vv = this.valueView(plot);
    for (const v of this.values) v.drawScales(ctx, vv, l0, l1, (x) => fmtNumber(x, 3), this.fs * 3);
    ctx.restore();
  }

  /** What the bars need of the frame. */
  private barView(plot = this.plot()): BarView {
    return {
      left: this.camera.left,
      scale: this.camera.scale,
      plot,
      laneTop: plot.y - this.scrollY,
      laneH: this.laneH,
      maxBar: Math.max(16, Math.round(this.fs * 2.2)),
      sequence: this.xscale === "sequence",
      slot: this.slot,
    };
  }

  /** The arrows of dependencies, and text in the bars (when not too many are in view). */
  private drawBarText(ctx: CanvasRenderingContext2D, v: BarView, l0: number, l1: number, labels: boolean): void {
    if (!this.bars.length) return;
    const { plot } = v;
    ctx.save();
    ctx.beginPath();
    ctx.rect(plot.x, plot.y, plot.w, plot.h);
    ctx.clip();
    for (const b of this.bars) b.drawLinks(ctx, v, l0, l1, this.theme.muted);
    for (const b of this.bars) b.drawCritical(ctx, v, l0, l1, this.theme.text);
    ctx.font = this.font(-1);
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    const span = (t: number) => (this.axis ? this.axis.formatSpan(t) : fmtNumber(t));
    if (labels) for (const b of this.bars) b.drawLabels(ctx, v, this.theme.text, this.theme.bg, this.theme.muted, span);
    ctx.restore();
  }

  /** Vertical lines at times set in Python (Timeline.marker), labelled at the top. */
  private drawMarkers(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }): void {
    const markers = this.spec?.markers ?? [];
    if (!markers.length) return;
    ctx.save();
    ctx.beginPath();
    ctx.rect(plot.x, 0, plot.w, plot.y + plot.h);
    ctx.clip();
    ctx.font = this.font(-1);
    ctx.textBaseline = "alphabetic";
    for (const m of markers) {
      let at = m.x;
      if (this.xscale === "sequence") {
        if (!this.seqTimes?.length) continue;
        at = lowerBound(this.seqTimes, m.x) - 0.5;
      }
      const x = Math.round(plot.x + this.camera.toPx(at)) + 0.5;
      if (x < plot.x - 1 || x > plot.x + plot.w + 1) continue;
      const color = m.color ?? this.theme.select;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 3]);
      ctx.beginPath();
      ctx.moveTo(x, plot.y);
      ctx.lineTo(x, plot.y + plot.h);
      ctx.stroke();
      ctx.setLineDash([]);
      if (m.label) {
        const w = ctx.measureText(m.label).width + 8;
        const lx = Math.min(x + 3, plot.x + plot.w - w);
        const y = plot.y + 3;
        ctx.fillStyle = this.theme.bg;
        ctx.fillRect(lx, y, w, this.fs + 4);
        ctx.fillStyle = color;
        ctx.fillText(m.label, lx + 4, y + this.fs);
      }
    }
    ctx.restore();
  }

  private drawHover(ctx: CanvasRenderingContext2D, plot: { x: number; y: number; w: number; h: number }, laneTop: number): void {
    const h = this.hovered;
    if (!h) return;
    if (h.val) {
      const v = this.values[h.layer];
      if (!v) return;
      const p = v.position(h.index, this.valueView(plot));
      ctx.save();
      ctx.beginPath();
      ctx.rect(plot.x, plot.y, plot.w, plot.h);
      ctx.clip();
      ctx.strokeStyle = this.theme.muted;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(Math.round(p.x) + 0.5, p.y - this.laneH / 2);
      ctx.lineTo(Math.round(p.x) + 0.5, p.y + this.laneH / 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = p.color;
      ctx.strokeStyle = this.theme.bg;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.restore();
      return;
    }
    if (h.bar) {
      const b = this.bars[h.layer];
      if (!b) return;
      const box = b.box(h.index, this.barView(plot));
      ctx.save();
      ctx.beginPath();
      ctx.rect(plot.x, plot.y, plot.w, plot.h);
      ctx.clip();
      ctx.strokeStyle = this.theme.text;
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
    const l = this.layers[h.layer];
    if (!l) return;
    const x = plot.x + (this.xsrc(l)[h.index] - this.camera.left) * this.camera.scale;
    const y = laneTop + (this.slot[l.data.lane[h.index]] + 0.5) * this.laneH + l.draw.dy.data[h.index];
    ctx.save();
    ctx.beginPath();
    ctx.rect(plot.x, plot.y, plot.w, plot.h);
    ctx.clip();
    ctx.strokeStyle = this.theme.text;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(x, y, l.data.size[h.index] / 2 + 3, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  // ------------------------------------------------------------------ picking

  /** The event nearest to a point (CSS px in the stage), within HOVER_PX. */
  private pick(px: number, py: number): Hit | null {
    if (!this.spec) return null;
    const plot = this.plot();
    if (px < plot.x || px > plot.x + plot.w || py < plot.y || py > plot.y + plot.h) return null;
    // a story's box stands for its event
    for (let k = this.stemHits.length - 1; k >= 0; k--) {
      const b = this.stemHits[k];
      if (px >= b.x0 && px <= b.x1 && py >= b.y0 && py <= b.y1) return { layer: b.layer, index: b.index };
    }
    const laneTop = plot.y - this.scrollY;
    const at = Math.floor((py - laneTop) / this.laneH);
    let best: { layer: number; index: number } | null = null;
    let bestD = HOVER_PX * HOVER_PX;
    this.layers.forEach((l, li) => {
      if (!l.data.spec.hover && !l.data.spec.select) return;
      const src = this.xsrc(l);
      const starts = l.data.laneStarts;
      const reach = (HOVER_PX + 12) / this.camera.scale;
      const x = this.camera.fromPx(px - plot.x);
      for (let r = Math.max(0, at - 1); r <= at + 1 && r < this.laneAt.length; r++) {
        const lane = this.laneAt[r];
        if (lane + 1 >= starts.length) continue;
        const i0 = lowerBound(src, x - reach, starts[lane], starts[lane + 1]);
        const i1 = upperBound(src, x + reach, i0, starts[lane + 1]);
        for (let i = i0; i < i1; i++) {
          const ex = plot.x + (src[i] - this.camera.left) * this.camera.scale;
          const ey = laneTop + (r + 0.5) * this.laneH + l.draw.dy.data[i];
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
    const vv = this.valueView(plot);
    for (let k = this.values.length - 1; k >= 0; k--) {
      const layer = this.values[k];
      if (!layer.data.spec.hover) continue;
      const i = layer.pick(px, py, at, this.laneAt, vv, HOVER_PX);
      if (i >= 0) return { layer: k, index: i, val: true };
    }
    // bars, top layer first
    const v = this.barView(plot);
    for (let k = this.bars.length - 1; k >= 0; k--) {
      const b = this.bars[k];
      if (!b.data.spec.hover && !b.data.spec.select) continue;
      const i = b.pick(px, py, at, this.laneAt, v);
      if (i >= 0) return { layer: k, index: i, bar: true };
    }
    return null;
  }

  /** The spec of the layer a hit is in. */
  private specOf(h: Hit): EventsLayerSpec | IntervalsLayerSpec | ValuesLayerSpec | undefined {
    if (h.val) return this.values[h.layer]?.data.spec;
    return h.bar ? this.bars[h.layer]?.data.spec : this.layers[h.layer]?.data.spec;
  }

  private setHovered(h: Hit | null): void {
    const same = h && this.hovered && h.layer === this.hovered.layer && h.index === this.hovered.index && !!h.bar === !!this.hovered.bar && !!h.val === !!this.hovered.val;
    if (same || (!h && !this.hovered)) return;
    this.hovered = h;
    this.requestRender();
    this.showTooltip();
  }

  private showTooltip(): void {
    const h = this.hovered;
    const spec = h ? this.specOf(h) : undefined;
    if (!h || !spec || !this.pointer || !this.axis || !this.spec || !spec.hover) {
      this.tooltip.classList.remove("atl-show");
      this.tooltipKey = "";
      return;
    }
    const key = `${h.val ? "v" : h.bar ? "b" : "e"}${h.layer}:${h.index}`;
    this.tooltipKey = key;
    const rows: [string, string][] = [];
    if (this.layers.length + this.bars.length + this.values.length > 1) rows.push(["layer", spec.name]);
    if (h.val) {
      const v = this.values[h.layer];
      const d = v.data;
      rows.push([this.spec.lanes.title || "lane", this.spec.lanes.names[v.laneOf(h.index)] ?? ""]);
      const series = v.seriesOf(h.index);
      if (series) rows.push([d.spec.series_title || "series", series]);
      rows.push(["time", this.axis.formatFull(d.time[h.index])]);
      rows.push(["value", fmtNumber(d.value[h.index], 6)]);
    } else if (h.bar) {
      const d = this.bars[h.layer].data;
      const i = h.index;
      rows.push([this.spec.lanes.title || "lane", this.spec.lanes.names[d.lane[i]] ?? ""]);
      if (d.kind[i] === 1) rows.push(["at", this.axis.formatFull(d.start[i])], ["", "milestone"]);
      else {
        rows.push(["start", this.axis.formatFull(d.start[i])]);
        rows.push(["end", d.kind[i] === 2 ? "open (not ended)" : this.axis.formatFull(d.end[i])]);
        if (d.kind[i] !== 2) rows.push(["duration", this.axis.formatSpan(d.end[i] - d.start[i])]);
      }
      if (d.progress && d.progress[i] >= 0) rows.push(["progress", `${Math.round(d.progress[i] * 100)}%`]);
      if (d.text?.[i]) rows.push(["text", d.text[i]]);
    } else {
      const l = this.layers[h.layer];
      if (this.spec.lanes.show_names !== false) rows.push([this.spec.lanes.title || "lane", this.spec.lanes.names[l.data.lane[h.index]] ?? ""]);
      if (l.data.spec.has_time) rows.push(["time", this.axis.formatFull(l.data.time[h.index])]);
      rows.push(["order", `#${fmtNumber(l.data.rank[h.index] + 1)}`]);
      if (l.data.text?.[h.index]) rows.push(["text", l.data.text[h.index]]);
    }
    const render = (extra: string[][]) => {
      if (this.tooltipKey !== key) return;
      this.tooltip.replaceChildren(
        ...[...rows, ...extra].map(([k, v]) => {
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
      this.placeTooltip();
    };
    render([]);
    this.tooltip.classList.add("atl-show");
    if (spec.tooltip.length && this.callbacks.onTooltip) {
      this.callbacks.onTooltip(spec.name, h.index).then(render, () => {});
    }
  }

  private placeTooltip(): void {
    if (!this.pointer) return;
    const tw = this.tooltip.offsetWidth;
    const th = this.tooltip.offsetHeight;
    let x = this.pointer.x + 14;
    let y = this.pointer.y + 14;
    if (x + tw > this.width - 4) x = this.pointer.x - tw - 14;
    if (y + th > this.height - 4) y = this.pointer.y - th - 14;
    this.tooltip.style.transform = `translate(${Math.max(4, x)}px, ${Math.max(4, y)}px)`;
  }

  // ------------------------------------------------------------------ tools and input

  /** Switch the tool (Pan, Zoom, Select); Select only while something can be selected. */
  setTool(tool: Tool, fromUser = false): void {
    if (!TOOLS.includes(tool)) return;
    const next = this.offeredTools().includes(tool) ? tool : "pan";
    if (next === this.tool) return;
    this.tool = next;
    this.stage.dataset.tool = next;
    this.cancelDrag();
    this.updateToolbar();
    if (fromUser) this.callbacks.onTool?.(next);
  }

  private offeredTools(): Tool[] {
    return this.selectionMode === "none" ? ["pan", "zoom"] : TOOLS;
  }

  private updateToolbar(): void {
    this.toolbar.update({
      tool: this.tool,
      tools: this.offeredTools(),
      xscale: this.xscale,
      timeAvailable: this.spec?.time.kind !== "order",
      orderAvailable: !this.spec || !!this.spec.sequence?.count,
      canGoBack: this.history.some((h) => h.xscale === this.xscale),
      zoomed: this.isZoomed(),
      selected: Object.values(this.marks).reduce((n, m) => n + m.length, 0),
      legend: this.showLegend,
      hasLegend: !!this.legendEl,
      fullscreen: this.isFullscreen(),
      fullscreenAvailable: !!document.fullscreenEnabled,
      fontSize: this.fs,
      markScale: this.markScale,
      dodge: this.dodgeOn,
      dodges: this.layers.some((l) => l.data.spec.overlap === "dodge" && !isStems(l)),
    });
  }

  /** Whether the view differs from the whole timeline (Home has something to do). */
  private isZoomed(): boolean {
    if (!this.spec) return false;
    const [a, b] = this.xscale === "sequence" ? [-0.5, Math.max(0.5, (this.spec.sequence?.count ?? 1) - 0.5)] : this.spec.time.extent;
    const span = (b - a) * 1.06 || 1;
    const tol = span * 1e-3;
    return Math.abs(this.camera.span - span) > tol || Math.abs(this.camera.left - (a - (b - a) * 0.03)) > tol || this.scrollY > 0.5;
  }

  /** Remember the view before a navigation, for Back (Backspace). */
  private pushHistory(): void {
    const s = { left: this.camera.left, span: this.camera.span, scrollY: this.scrollY, xscale: this.xscale };
    const last = this.history[this.history.length - 1];
    const eps = s.span * 1e-6;
    if (last && last.xscale === s.xscale && Math.abs(last.left - s.left) < eps && Math.abs(last.span - s.span) < eps && last.scrollY === s.scrollY) return;
    this.history.push(s);
    if (this.history.length > HISTORY) this.history.shift();
    this.updateToolbar();
  }

  previousView(): void {
    let s = this.history.pop();
    while (s && s.xscale !== this.xscale) s = this.history.pop();
    if (s) {
      this.camera.fit(s.left, s.left + s.span, 0);
      this.scrollY = s.scrollY;
      this.clampScroll();
      this.afterMove();
    }
    this.updateToolbar();
  }

  isFullscreen(): boolean {
    // :fullscreen, not document.fullscreenElement: inside a shadow root (marimo puts widgets
    // there) the latter is the shadow's host
    return this.root.matches(":fullscreen");
  }

  toggleFullscreen(): void {
    if (!document.fullscreenEnabled) {
      this.flashNotice("Full screen is not available here");
      return;
    }
    const done = this.isFullscreen() ? document.exitFullscreen() : this.root.requestFullscreen();
    done?.catch((err: unknown) => this.flashNotice(`Full screen is not available here (${err instanceof Error ? err.message : String(err)})`));
  }

  private onFullscreenChange = (): void => {
    const full = this.isFullscreen();
    this.root.classList.toggle("atl-fullscreen", full);
    this.layout();
    this.updateToolbar();
    if (this.helpEl) this.toggleHelp(); // its Esc line changed
  };

  toggleHelp(): void {
    if (this.helpEl) {
      this.helpEl.remove();
      this.helpEl = null;
      this.root.focus({ preventScroll: true });
      return;
    }
    this.helpEl = buildHelp(this.offeredTools(), this.isFullscreen(), () => this.toggleHelp(), !!this.spec?.lanes.tree);
    this.root.append(this.helpEl);
    this.helpEl.focus({ preventScroll: true });
  }

  private toggleLegend(): void {
    this.setLegend(!this.showLegend);
    this.callbacks.onLegend?.(this.showLegend);
  }

  private cancelDrag(): void {
    this.drag = null;
    this.box = null;
    this.stage.classList.remove("atl-panning");
    this.requestRender();
  }

  private bindInput(): void {
    const stage = this.stage;
    const local = (e: MouseEvent) => {
      const r = stage.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    stage.addEventListener("wheel", (e) => {
      const active = this.root.contains(document.activeElement) || this.isFullscreen() || this.root.matches(":focus-within");
      if (!active && !e.ctrlKey && !e.metaKey) {
        this.flashNotice("Click the plot, then scroll to zoom");
        return;
      }
      e.preventDefault();
      const now = performance.now();
      if (now - this.lastWheel > 500) this.pushHistory();
      this.lastWheel = now;
      const p = local(e);
      const plot = this.plot();
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
      if (e.shiftKey) {
        this.scrollY += (e.deltaY || e.deltaX) * unit;
        this.clampScroll();
      } else {
        if (e.deltaY) this.camera.zoomAt(Math.max(0, Math.min(plot.w, p.x - plot.x)), Math.exp(-e.deltaY * unit * 0.0022));
        if (e.deltaX) this.camera.pan(-e.deltaX * unit);
      }
      this.afterMove();
    }, { passive: false });

    stage.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      this.root.focus({ preventScroll: true });
      const p = local(e);
      const plot = this.plot();
      stage.setPointerCapture(e.pointerId);
      let mode: DragMode;
      if (this.spaceDown) mode = "pan";
      else if (p.y < plot.y && p.x >= plot.x) mode = "axis";
      else if (this.tool === "zoom") mode = "zoom";
      else if (this.tool === "select") mode = "select";
      else mode = e.shiftKey ? "zoom" : "pan";
      this.drag = { x: p.x, y: p.y, left: this.camera.left, scrollY: this.scrollY, mode, moved: false };
    });

    stage.addEventListener("pointermove", (e) => {
      const p = local(e);
      this.pointer = p;
      const d = this.drag;
      if (d) {
        const dx = p.x - d.x;
        const dy = p.y - d.y;
        if (!d.moved && Math.abs(dx) + Math.abs(dy) > 4) {
          d.moved = true;
          if (d.mode === "pan") {
            this.pushHistory();
            stage.classList.add("atl-panning");
          }
          this.setHovered(null);
        }
        if (!d.moved) return;
        if (d.mode === "pan") {
          this.camera.left = d.left;
          this.camera.pan(dx);
          this.scrollY = d.scrollY - dy;
          this.clampScroll();
          this.afterMove();
        } else {
          this.box = { x0: d.x, y0: d.y, x1: p.x, y1: p.y, kind: this.boxKind(d.mode) };
          this.requestRender();
        }
        return;
      }
      if (this.hoverEnabled) this.setHovered(this.pick(p.x, p.y));
      const plotNow = this.plot();
      this.shareCursor(p.x >= plotNow.x && p.x <= plotNow.x + plotNow.w ? p.x : null);
      this.stage.classList.toggle("atl-foldable", this.foldableAt(p));
      if (this.hovered) this.placeTooltip();
    });

    const end = (e: PointerEvent) => {
      const d = this.drag;
      const box = this.box;
      this.drag = null;
      this.box = null;
      stage.classList.remove("atl-panning");
      if (!d) return;
      const p = local(e);
      const wide = box && Math.abs(box.x1 - box.x0) >= MIN_BOX;
      if (d.moved && box && d.mode !== "pan") {
        if (box.kind === "select" || box.kind === "range-select") {
          if (wide || box.kind === "select") this.selectBox(box, boxMode(e));
        } else if (wide) {
          this.zoomToBox(box);
        }
        this.requestRender();
        return;
      }
      if (d.moved) return;
      this.click(p, e, d.mode);
    };
    stage.addEventListener("pointerup", end);
    stage.addEventListener("pointercancel", () => this.cancelDrag());
    stage.addEventListener("pointerleave", () => {
      this.pointer = null;
      this.shareCursor(null);
      if (!this.drag) this.setHovered(null);
    });

    this.root.addEventListener("keydown", (e) => this.key(e));
    this.root.addEventListener("keyup", (e) => {
      if (e.key === " ") {
        this.spaceDown = false;
        this.root.classList.remove("atl-space");
      }
    });
    this.root.addEventListener("blur", () => {
      this.spaceDown = false;
      this.root.classList.remove("atl-space");
    });
    document.addEventListener("fullscreenchange", this.onFullscreenChange);
  }

  private boxKind(mode: DragMode): BoxKind {
    if (mode === "select") return "select";
    if (mode === "axis") return this.tool === "select" ? "range-select" : "range";
    return "range";
  }

  /** A click (a press that did not move) with the drag mode it started in. */
  private click(p: { x: number; y: number }, e: MouseEvent, mode: DragMode): void {
    const plot = this.plot();
    const inPlot = p.x >= plot.x && p.x <= plot.x + plot.w && p.y >= plot.y && p.y <= plot.y + plot.h;
    if (mode !== "axis" && p.x < plot.x && p.y >= plot.y && p.y <= plot.y + plot.h) {
      // a lane's name: a click folds or unfolds it, a double-click shows all of it
      const lane = this.laneAtY(p.y);
      const now = performance.now();
      if (now - this.lastNameTap.at < DOUBLE_CLICK_MS && lane === this.lastNameTap.lane) {
        this.lastNameTap = { at: 0, lane: -1 };
        this.toggleLane(lane, e.altKey); // undo the first click's fold
        this.zoomToLane(lane);
      } else {
        this.lastNameTap = { at: now, lane };
        this.toggleLane(lane, e.altKey);
      }
      return;
    }
    if (mode === "axis" || !inPlot) return;
    const selecting = this.selectionMode !== "none";
    const hit = selecting ? this.pick(p.x, p.y) : null;
    const select = (m: SelectMode) => {
      const spec = hit ? this.specOf(hit) : undefined;
      if (hit && spec?.select) this.callbacks.onGesture?.({ kind: "click", layer: spec.name, index: hit.index, mode: m });
    };
    if (this.tool === "zoom" && mode === "zoom") {
      this.pushHistory();
      this.camera.zoomAt(p.x - plot.x, e.altKey ? 0.5 : 2);
      this.afterMove();
      return;
    }
    if (this.tool === "select") {
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
    if (now - this.lastTap < DOUBLE_CLICK_MS) {
      this.lastTap = 0;
      this.resetView();
      return;
    }
    this.lastTap = now;
  }

  /**
   * The plot as a PNG: its title, the lanes, axis and marks as they are on screen, and the
   * legend; at least twice the screen's resolution.
   */
  async snapshot(): Promise<Blob> {
    const legend = this.showLegend && this.legendEl ? await legendPainter(this.legendEl, this.stage) : null;
    const title = this.titleEl.textContent ?? "";
    const titleH = title ? Math.round(this.fs * 2.4) : 0;
    const scale = Math.max(2, this.dpr);
    const out = document.createElement("canvas");
    out.width = Math.round(this.width * scale);
    out.height = Math.round((this.height + titleH) * scale);
    const ctx = out.getContext("2d")!;
    ctx.scale(scale, scale);
    ctx.fillStyle = this.theme.bg;
    ctx.fillRect(0, 0, this.width, this.height + titleH);
    if (title) {
      ctx.font = `600 ${this.fs + 2}px ${fontFamily}`;
      ctx.fillStyle = this.theme.text;
      ctx.textBaseline = "middle";
      ctx.fillText(title, 10, titleH / 2 + 2);
    }
    // draw a frame without the hover ring, at the picture's resolution, and copy the canvases
    // in the same task: a WebGPU canvas can only be read in the task that drew it
    const hovered = this.hovered;
    this.hovered = null;
    const sharp = this.dpr < scale;
    if (sharp) this.layout(scale);
    // WebGPU hands the frame's pixels back itself (its canvas cannot be copied everywhere)
    const pixels = this.renderer?.captureNext?.() ?? null;
    this.renderFrame();
    ctx.drawImage(this.back, 0, titleH, this.width, this.height);
    let front: HTMLCanvasElement = this.front;
    if (pixels) {
      // keep the front canvas as drawn, to go on top once the pixels are back
      front = document.createElement("canvas");
      front.width = this.front.width;
      front.height = this.front.height;
      front.getContext("2d")!.drawImage(this.front, 0, 0);
    } else if (this.renderer) {
      ctx.drawImage(this.renderer.canvas, 0, titleH, this.width, this.height);
    }
    this.hovered = hovered;
    if (sharp) this.layout();
    if (pixels) {
      const img = await pixels.catch((err) => {
        console.warn("[anytimeline] reading the frame back failed; copying the canvas", err);
        return null;
      });
      if (img) {
        const gpu = document.createElement("canvas");
        gpu.width = img.width;
        gpu.height = img.height;
        gpu.getContext("2d")!.putImageData(img, 0, 0);
        ctx.drawImage(gpu, 0, titleH, this.width, this.height);
      } else if (this.renderer) {
        // draw the frame again and copy the canvas in the same task (best effort)
        this.hovered = null;
        if (sharp) this.layout(scale);
        this.renderFrame();
        ctx.drawImage(this.renderer.canvas, 0, titleH, this.width, this.height);
        this.hovered = hovered;
        if (sharp) this.layout();
      }
    }
    ctx.drawImage(front, 0, titleH, this.width, this.height);
    legend?.(ctx, titleH);
    this.requestRender();
    return new Promise((resolve, reject) => out.toBlob((b) => (b ? resolve(b) : reject(new Error("no image"))), "image/png"));
  }

  /** Save the plot as a PNG (the toolbar's button): a download named after the title. */
  async savePNG(): Promise<void> {
    try {
      download(await this.snapshot(), fileName(this.titleEl.textContent ?? "", "png"));
    } catch (err) {
      this.flashNotice(`Could not save the image: ${String(err)}`);
    }
  }

  /** Zoom time to everything on a lane and the lanes under it (a span and its children), and
   * scroll it to the top. */
  zoomToLane(lane: number): void {
    const tree = this.spec?.lanes.tree;
    if (lane < 0 || !this.spec) return;
    const last = lane + (tree && lane < tree.size.length ? tree.size[lane] : 1);
    const seq = this.xscale === "sequence";
    let a = Infinity;
    let b = -Infinity;
    for (const bar of this.bars) {
      const [lo, hi] = bar.ends(seq);
      const starts = bar.data.laneStarts;
      const i0 = starts[Math.min(lane, starts.length - 1)];
      const i1 = starts[Math.min(last, starts.length - 1)];
      for (let i = i0; i < i1; i++) {
        a = Math.min(a, lo[i]);
        b = Math.max(b, hi[i]);
      }
    }
    for (const l of this.layers) {
      const src = this.xsrc(l);
      const starts = l.data.laneStarts;
      const i0 = starts[Math.min(lane, starts.length - 1)];
      const i1 = starts[Math.min(last, starts.length - 1)];
      for (let i = i0; i < i1; i++) {
        a = Math.min(a, src[i]);
        b = Math.max(b, src[i]);
      }
    }
    if (!(b >= a)) return;
    if (b === a) {
      a -= 0.5;
      b += 0.5;
    }
    this.pushHistory();
    this.camera.fit(a, b, 0.04);
    if (this.slot[lane] >= 0) this.scrollY = this.slot[lane] * this.laneH;
    this.clampScroll();
    this.afterMove();
  }

  private zoomToBox(b: Box): void {
    const plot = this.plot();
    const xa = this.camera.fromPx(Math.min(b.x0, b.x1) - plot.x);
    const xb = this.camera.fromPx(Math.max(b.x0, b.x1) - plot.x);
    this.pushHistory();
    this.camera.fit(xa, xb, 0);
    this.afterMove();
  }

  private key(e: KeyboardEvent): void {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (this.helpEl && e.key !== "?" && e.key !== "Escape") return;
    const plot = this.plot();
    const move = (fn: () => void) => {
      this.pushHistory();
      fn();
    };
    let handled = true;
    switch (e.key) {
      case "p":
        this.setTool("pan", true);
        break;
      case "z":
        this.setTool("zoom", true);
        break;
      case "s":
        this.setTool("select", true);
        break;
      case "t":
      case "T":
        this.setXScale(this.xscale === "time" ? "sequence" : "time", true);
        break;
      case "[":
      case "]":
        if (!this.spec?.lanes.tree) return;
        this.expandAll(e.key === "]");
        break;
      case "0":
      case "Home":
        this.resetView();
        break;
      case "Backspace":
        this.previousView();
        break;
      case "+":
      case "=":
        move(() => this.camera.zoomAt(plot.w / 2, 2));
        break;
      case "-":
      case "_":
        move(() => this.camera.zoomAt(plot.w / 2, 0.5));
        break;
      case "ArrowLeft":
        this.camera.pan(plot.w * 0.2);
        break;
      case "ArrowRight":
        this.camera.pan(-plot.w * 0.2);
        break;
      case "ArrowUp":
        this.scrollY -= this.laneH * 3;
        break;
      case "ArrowDown":
        this.scrollY += this.laneH * 3;
        break;
      case "d":
        if (!this.layers.some((l) => l.data.spec.overlap === "dodge")) return;
        this.setDodge(!this.dodgeOn);
        this.callbacks.onDodge?.(this.dodgeOn);
        break;
      case "l":
        if (this.legendEl) this.toggleLegend();
        break;
      case "f":
        this.toggleFullscreen();
        break;
      case "?":
        this.toggleHelp();
        break;
      case " ":
        this.spaceDown = true;
        this.root.classList.add("atl-space");
        break;
      case "Escape":
        if (this.helpEl) this.toggleHelp();
        else if (this.drag) this.cancelDrag();
        else if (Object.values(this.marks).some((m) => m.length)) this.callbacks.onGesture?.({ kind: "clear" });
        else handled = false;
        break;
      default:
        handled = false;
    }
    if (handled) {
      // keep the key from the notebook (JupyterLab's command-mode shortcuts) and the page
      e.preventDefault();
      e.stopPropagation();
      this.clampScroll();
      this.afterMove();
    }
  }

  private afterMove(): void {
    this.shareRange();
    this.requestRender();
    this.reportView();
    this.updateToolbarSoon();
  }

  private toolbarTimer: ReturnType<typeof setTimeout> | undefined;

  /** The Home and Back buttons follow the view, at most every 100 ms. */
  private updateToolbarSoon(): void {
    if (this.toolbarTimer !== undefined) return;
    this.toolbarTimer = setTimeout(() => {
      this.toolbarTimer = undefined;
      this.updateToolbar();
    }, 100);
  }

  private noticeTimer: ReturnType<typeof setTimeout> | undefined;

  private flashNotice(text: string): void {
    if (this.status) return;
    this.notice.textContent = text;
    this.notice.classList.add("atl-show");
    clearTimeout(this.noticeTimer);
    this.noticeTimer = setTimeout(() => {
      if (!this.status) this.notice.classList.remove("atl-show");
    }, 1600);
  }

  private selectBox(b: Box, mode: SelectMode): void {
    const plot = this.plot();
    const laneTop = plot.y - this.scrollY;
    const xa = this.camera.fromPx(Math.min(b.x0, b.x1) - plot.x);
    const xb = this.camera.fromPx(Math.max(b.x0, b.x1) - plot.x);
    const rows = this.laneAt.length;
    let ra = 0;
    let rb = rows - 1;
    if (b.kind === "select") {
      ra = Math.floor((Math.max(plot.y, Math.min(b.y0, b.y1)) - laneTop) / this.laneH);
      rb = Math.floor((Math.min(plot.y + plot.h, Math.max(b.y0, b.y1)) - laneTop) / this.laneH);
    }
    ra = Math.max(0, Math.min(rows - 1, ra));
    rb = Math.max(0, Math.min(rows - 1, rb));
    const lanes: [number, number] = [this.laneAt[ra] ?? 0, this.laneAt[rb] ?? 0];
    // with folded lanes, the rows in the box are not one range of lanes: list them
    const folded = this.laneAt.length < (this.spec?.lanes.names.length ?? 0);
    const shown = folded ? Array.from(this.laneAt.subarray(ra, rb + 1)) : undefined;
    this.callbacks.onGesture?.({ kind: "box", x: [xa, xb], lanes, shown, xscale: this.xscale, mode });
  }

  /** Where event `index` of layer `layer` is drawn (CSS px in the stage), or null. */
  eventPosition(layer: number, index: number): { x: number; y: number } | null {
    const l = this.layers[layer];
    if (!l || index < 0 || index >= l.data.count) return null;
    const plot = this.plot();
    return {
      x: plot.x + (this.xsrc(l)[index] - this.camera.left) * this.camera.scale,
      y: plot.y - this.scrollY + (this.slot[l.data.lane[index]] + 0.5) * this.laneH + l.draw.dy.data[index],
    };
  }

  /** Where bar `index` of intervals layer `layer` is drawn (its middle, CSS px in the stage). */
  barPosition(layer: number, index: number): { x: number; y: number } | null {
    const b = this.bars[layer];
    if (!b || index < 0 || index >= b.data.count) return null;
    const box = b.box(index, this.barView());
    return { x: box.milestone ? box.x0 : (box.x0 + box.x1) / 2, y: box.cy };
  }

  /** Time the drawing of `frames` frames while panning (for benchmarks). */
  async benchmark(frames = 60): Promise<Record<string, number>> {
    const times: number[] = [];
    const plot = this.plot();
    for (let i = 0; i < frames; i++) {
      const t0 = performance.now();
      this.camera.pan(i % 2 ? -plot.w / 50 : plot.w / 50);
      this.renderFrame();
      await this.renderer?.finish();
      times.push(performance.now() - t0);
    }
    times.sort((a, b) => a - b);
    return { median_ms: times[Math.floor(times.length / 2)], p95_ms: times[Math.floor(times.length * 0.95)] };
  }

  private readonly themeWatch: MutationObserver;
  private readonly themeMedia: MediaQueryList | null;
  private readonly onThemeChange = (): void => {
    // after the host's styles apply
    requestAnimationFrame(() => this.refreshTheme());
  };

  destroy(): void {
    this.setLink(null);
    this.resizeObserver.disconnect();
    this.themeWatch.disconnect();
    this.themeMedia?.removeEventListener?.("change", this.onThemeChange);
    document.removeEventListener("fullscreenchange", this.onFullscreenChange);
    this.toolbar.destroy();
    this.renderer?.destroy();
    this.root.remove();
  }
}

// ---------------------------------------------------------------------- helpers

/** Attributes by which hosts switch light and dark: JupyterLab (data-jp-theme-light), VS Code
 * (class vscode-dark, data-vscode-theme-kind), marimo and others (class dark, data-theme),
 * Material for MkDocs / Zensical (data-md-color-scheme). */
const THEME_ATTRIBUTES = ["class", "data-jp-theme-light", "data-vscode-theme-kind", "data-theme", "data-md-color-scheme"];

const fontFamily = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

function div(cls: string): HTMLDivElement {
  const d = document.createElement("div");
  d.className = cls;
  return d;
}

function canvas(cls: string): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.className = `atl-canvas ${cls}`;
  return c;
}

function rgb01(css: string): [number, number, number] {
  const m = css.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const [r, g, b] = m[1].split(/[ ,/]+/).map(Number);
    return [r / 255, g / 255, b / 255];
  }
  const [r, g, b] = parseHex(css);
  return [r / 255, g / 255, b / 255];
}

function ellipsize(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  if (ctx.measureText(text).width <= width) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ctx.measureText(text.slice(0, mid) + "…").width <= width) lo = mid;
    else hi = mid - 1;
  }
  return text.slice(0, lo) + "…";
}

/** A click: Shift/Ctrl/⌘ add or remove the event, Alt removes it, else it replaces. */
function clickMode(e: MouseEvent): SelectMode {
  if (e.altKey) return "remove";
  if (e.shiftKey || e.ctrlKey || e.metaKey) return "toggle";
  return "replace";
}

/** A box: Shift/Ctrl/⌘ add what is inside, Alt removes it, else it replaces. */
function boxMode(e: MouseEvent): SelectMode {
  if (e.altKey) return "remove";
  if (e.shiftKey || e.ctrlKey || e.metaKey) return "add";
  return "replace";
}

/**
 * Long gaps between consecutive events (sequence scale): at rank k + 0.5 when the time
 * from event k to k + 1 is over 20× the median gap; at most one gap per 50 events (the
 * longest).
 */
export function findGaps(times: Float64Array | null): { at: number; span: number }[] {
  if (!times || times.length < 3) return [];
  const diffs = new Float64Array(times.length - 1);
  for (let i = 0; i < diffs.length; i++) diffs[i] = times[i + 1] - times[i];
  const sorted = Float64Array.from(diffs).sort();
  const median = sorted[Math.floor(sorted.length / 2)];
  const mean = sorted.reduce((a, b) => a + b, 0) / sorted.length;
  let threshold = median > 0 ? median * 20 : mean * 10;
  const most = Math.max(1, Math.floor(diffs.length / 50));
  if (sorted.length > most) threshold = Math.max(threshold, sorted[sorted.length - most - 1]);
  if (!(threshold > 0)) return [];
  const out: { at: number; span: number }[] = [];
  for (let i = 0; i < diffs.length; i++) if (diffs[i] > threshold) out.push({ at: i + 0.5, span: diffs[i] });
  return out;
}

function lowerBoundBy(a: { at: number }[], x: number): number {
  let lo = 0;
  let hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (a[mid].at < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The row of each event's lane (a float per event, for the GPU); -1 for hidden lanes. */
function rowsOf(lane: Uint32Array, slot: Int32Array): Float32Array {
  const out = new Float32Array(lane.length);
  for (let i = 0; i < lane.length; i++) out[i] = slot[lane[i]] ?? -1;
  return out;
}

/** What identifies a plot's lanes: when it is the same, folding is kept. */
function treeKey(spec: SceneSpec): string {
  const t = spec.lanes.tree;
  return t ? `${spec.lanes.names.length}:${t.depth.length}:${spec.lanes.names.slice(0, 50).join("\u0001")}` : "";
}

/** Whether an events layer puts its text in boxes on stems (a story timeline). */
function isStems(l: Layer): boolean {
  return l.data.spec.labels === "stems";
}
