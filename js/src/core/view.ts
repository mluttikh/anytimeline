// TimelineView: one timeline in a DOM element. It lays out the lanes and the time axis,
// keeps the camera, culls and dodges the events in view, and hands the backend what to draw.
// Three canvases are stacked: the back (lane bands, grid lines), the renderer's (events,
// routes) and the front (axis, lane names, labels, hover ring, selection box).
//
// Framework-agnostic: widget.ts connects it to anywidget; another host supplies a
// DataSource and the callbacks.
//
// The view's parts are modules of functions that take it: folding (rows and folding),
// rendering (a frame), drawing (the front canvas), picking (and tooltips) and input. Its
// members without `private` are theirs to use; other code uses its methods.

import { BarLayer, decodeBars } from "./bars";
import { TimeCamera } from "./camera";
import { buildHelp } from "./help";
import { buildLegend } from "./legend";
import { FLAG_SELECTED, type MarkLayerDraw, type Renderer } from "./renderers/renderer";
import { createRenderer } from "./renderers/select";
import { type Align, compatible, convert, frameOf, join, leave, type LinkFrame, type LinkPeer, type LinkSpec, others } from "./link";
import { download, fileName, legendPainter } from "./snapshot";
import type { StemPlaced } from "./stems";
import { decodeValues, ValueLayer, type ValueView } from "./values";
import { BarDetail, Detail, type DetailView, ValueDetail, type WindowAsk } from "./levels";
import { decodeEvents, type EventsData, fillSolid, lowerBound, specBufferIds } from "./scene";
import { Sequence } from "./sequence";
import { fmtNumber, TimeAxis, UNIT_NS } from "./time";
import { FONT_SIZES, type Tool, Toolbar, TOOLS } from "./toolbar";
import type { DataSource, EventsLayerSpec, IntervalsLayerSpec, RendererKind, RendererPreference, SceneSpec, ValuesLayerSpec, XScale } from "./types";
import { AUTO_LANE, type Box, canvas, div, type DragMode, findGaps, fontFamily, gapsOf, type Gesture, HISTORY, type Hit, isStems, type Layer, MIN_LANE, PAD_BOTTOM, PAD_RIGHT, rowsOf, type Theme, THEME_ATTRIBUTES } from "./common";
import * as folding from "./folding";
import * as rendering from "./rendering";
import * as drawing from "./drawing";
import * as picking from "./picking";
import * as input from "./input";

export type { Gesture, SelectMode } from "./common";
export { findGaps } from "./common";
export type { Tool } from "./toolbar";

export interface ViewCallbacks {
  onGesture?: (g: Gesture) => void;
  /** The time range in sight and the names of the lanes in sight, top to bottom. */
  onView?: (range: [number, number], lanes: string[]) => void;
  onXScale?: (xscale: XScale) => void;
  /** Tooltip columns of one event: [name, value] rows. */
  onTooltip?: (layer: string, index: number) => Promise<string[][]>;
  /** What a bin of a layer sent as levels holds (rows of category and count). */
  onBinTooltip?: (layer: string, scale: XScale, lane: number, range: [number, number]) => Promise<string[][]>;
  /** A window of a layer sent as levels (Python serves them; without, the levels are all). */
  onWindow?: WindowAsk;
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

export class TimelineView implements DetailView {
  readonly root: HTMLDivElement;
  private readonly header: HTMLDivElement;
  private readonly titleEl: HTMLSpanElement;
  readonly info: HTMLSpanElement;
  private readonly toolbar: Toolbar;
  tool: Tool = "pan";
  private history: { left: number; span: number; scrollY: number; xscale: XScale }[] = [];
  helpEl: HTMLElement | null = null;
  spaceDown = false;
  lastWheel = 0;
  /** Text size in CSS px: lane names; axis and labels are 1 px smaller. */
  fs = FONT_SIZES.default;
  readonly stage: HTMLDivElement;
  readonly back: HTMLCanvasElement;
  readonly front: HTMLCanvasElement;
  readonly tooltip: HTMLDivElement;
  private readonly notice: HTMLDivElement;
  legendEl: HTMLElement | null = null;
  renderer: Renderer | null = null;
  private rendererPref: RendererPreference = "auto";
  private failedKinds: RendererKind[] = [];
  spec: SceneSpec | null = null;
  axis: TimeAxis | null = null;
  layers: Layer[] = [];
  /** The order of every instant (the Order scale), or null. */
  seq: Sequence | null = null;
  gaps: { at: number; span: number }[] = [];
  readonly camera = new TimeCamera();
  xscale: XScale = "time";
  base = 0;
  private baseVersion = 0;
  scrollY = 0;
  laneH = AUTO_LANE;
  /** The lane each row of the plot shows; folded lanes hide the lanes under them. */
  laneAt = new Int32Array(0);
  /** The row of each lane, -1 when hidden. */
  slot = new Int32Array(0);
  /** Per lane of the tree (lanes.tree): whether its children show. */
  open = new Uint8Array(0);
  /** Rows the plot's automatic height is for (fixed when the spec arrives, so folding does
   * not resize the plot). */
  autoRows = 1;
  private gutter = 80;
  /** Room on the right: the legend's column when the plot is wide enough. */
  private padRight = PAD_RIGHT;
  width = 0;
  height = 0;
  private fixedHeight = 0;
  dpr = 1;
  marks: Record<string, Int32Array> = {};
  /** Per events layer sent as levels: where its selected events are (time, order, lane). */
  marked: Record<string, Float64Array> = {};
  /** The event or bar under the pointer (`bar`: an index into `bars`, else into `layers`). */
  hovered: Hit | null = null;
  bars: BarLayer[] = [];
  values: ValueLayer[] = [];
  hoverEnabled = true;
  selectionMode = "multiple";
  private showLegend = true;
  theme: Theme;
  private frameRequested = false;
  private viewTimer: ReturnType<typeof setTimeout> | undefined;
  drag: { x: number; y: number; left: number; scrollY: number; mode: DragMode; moved: boolean } | null = null;
  box: Box | null = null;
  pointer: { x: number; y: number } | null = null;
  tooltipKey = "";
  /** The tooltip columns Python sent for the hovered mark (tooltipKey's). */
  tooltipExtra: string[][] = [];
  private readonly resizeObserver: ResizeObserver;
  private loadToken = 0;
  private firstFrameAt = 0;
  private status: string | null = null;
  lastTap = 0;
  /** The group of linked plots this view is in, and how it is in it. */
  private link: { spec: LinkSpec; peer: LinkPeer } | null = null;
  /** Following another view (its range or pointer): do not pass it on. */
  private following = false;
  /** The pointer of a linked view: a time in this view's ticks, or null. */
  linkedCursor: number | null = null;
  /** This view's own gutter and right padding, before the group's widest. */
  private own = { gutter: 80, padRight: PAD_RIGHT };
  /** The last click on a lane's name: a second one soon after on the same lane zooms to it. */
  lastNameTap = { at: 0, lane: -1 };

  constructor(
    private readonly host: HTMLElement,
    readonly callbacks: ViewCallbacks = {},
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
    input.bindInput(this);
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
    if (!on) picking.setHovered(this, null);
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

  markScale = 1;

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

  dodgeOn = true;

  /** The canvas font, `delta` px from the text size. */
  font(delta = 0): string {
    return `${Math.max(6, this.fs + delta)}px ${fontFamily}`;
  }

  /** The time axis' height: two rows of text. */
  get axisH(): number {
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

  /** Where the selected events of layers sent as levels are (shown over their bins). */
  setMarked(marked: Record<string, Float64Array>): void {
    this.marked = marked;
    this.requestRender();
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
    // layers sent as levels: the coarsest level of the scale shown, for a first frame
    const levelled = spec.layers.filter((ls): ls is EventsLayerSpec => ls.type === "events" && !!ls.levels);
    const scale: XScale = spec.time.kind === "order" ? "order" : this.xscale;
    const details = levelled.map((ls) => new Detail(ls, source, this.callbacks.onWindow ?? null));
    for (const d of details) ids.push(...d.firstIds(scale));
    const valueDetails = spec.layers
      .filter((ls): ls is ValuesLayerSpec => ls.type === "values" && !!ls.levels)
      .map((ls) => new ValueDetail(ls, source, this.callbacks.onWindow ?? null));
    for (const d of valueDetails) ids.push(...d.firstIds());
    const barDetails = spec.layers
      .filter((ls): ls is IntervalsLayerSpec => ls.type === "intervals" && !!ls.levels)
      .map((ls) => new BarDetail(ls, source, this.callbacks.onWindow ?? null, () => this.theme.accent));
    for (const d of barDetails) ids.push(...d.firstIds(scale));
    if (ids.some((id) => !source.has(id))) this.setStatus("Loading…");
    await source.ensure(ids);
    if (token !== this.loadToken) return;
    if (ids.some((id) => !source.has(id))) return; // a newer spec freed them
    if (this.status === "Loading…") this.setStatus(null);
    const firstSpec = !this.spec;
    const oldExtent = this.spec?.time.extent;
    this.spec = spec;
    this.axis = new TimeAxis(spec.time);
    for (const l of this.layers) l.detail?.destroy();
    for (const v of this.values) v.detail?.destroy();
    for (const b of this.bars) b.detail?.destroy();
    this.layers = spec.layers
      .filter((ls): ls is EventsLayerSpec => ls.type === "events")
      .map((ls) => {
        const layer = this.makeLayer(decodeEvents(ls, source));
        const detail = details.find((d) => d.spec === ls);
        if (detail) {
          detail.preload(scale);
          layer.detail = detail;
          layer.index = new Uint32Array(0);
        }
        return layer;
      });
    this.bars = spec.layers
      .filter((ls): ls is IntervalsLayerSpec => ls.type === "intervals")
      .map((ls) => {
        const b = new BarLayer(decodeBars(ls, source), this.theme.accent);
        const detail = barDetails.find((d) => d.spec === ls);
        if (detail) {
          detail.preload(scale);
          b.detail = detail;
        }
        b.applyMarks(this.marks[ls.name]);
        return b;
      });
    this.values = spec.layers
      .filter((ls): ls is ValuesLayerSpec => ls.type === "values")
      .map((ls) => {
        const v = new ValueLayer(decodeValues(ls, source), this.theme.accent);
        const detail = valueDetails.find((d) => d.spec === ls);
        if (detail) {
          detail.preload();
          v.detail = detail;
          v.index = new Uint32Array(0);
        }
        return v;
      });
    this.hovered = null;
    folding.initRows(this, spec);
    const sq = spec.sequence;
    this.seq = sq ? new Sequence(new Float64Array(source.get(sq.times.id)), sq.step ?? 1, sq.count) : null;
    this.gaps = sq?.gaps ? gapsOf(new Float64Array(source.get(sq.gaps.id))) : findGaps(this.seq?.exact ? this.seq.kept : null);
    this.retainDraws();
    const orderOnly = spec.time.kind === "order";
    if (orderOnly && this.xscale === "time") this.xscale = "order";
    this.legendEl?.remove();
    this.legendEl = buildLegend(spec.layers, this.theme.accent);
    if (this.legendEl) {
      this.legendEl.style.display = this.showLegend ? "" : "none";
      this.stage.append(this.legendEl);
    }
    const counts: string[] = [];
    const events = spec.layers.reduce((n, l) => n + (l.type === "events" ? (l.levels?.total ?? l.count) : 0), 0);
    if (events || (!this.bars.length && !this.values.length)) counts.push(`${fmtNumber(events)} event${events === 1 ? "" : "s"}`);
    for (const b of this.bars) counts.push(`${fmtNumber(b.detail?.levels.total ?? b.data.count)} ${b.data.spec.name}`);
    for (const v of this.values) counts.push(`${fmtNumber(v.detail?.levels.total ?? v.data.count)} samples`);
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

  infoText = "";

  private makeLayer(data: EventsData, index: Uint32Array | null = null): Layer {
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
    const layer: Layer = { data, draw, xs: new Float64Array(n), dodged: null, baseSize: Float32Array.from(data.size), index };
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
    const index = l.index;
    if (m && index) {
      // a window's events: the selected ones among them (both in the layer's order)
      for (const g of m) {
        const i = lowerBound(index, g);
        if (i < index.length && index[i] === g) sf[4 * i + 1] |= FLAG_SELECTED;
      }
    } else if (m) for (const i of m) if (i >= 0 && i < l.data.count) sf[4 * i + 1] |= FLAG_SELECTED;
    l.draw.sf.version++;
  }

  /** A window's events came for a layer sent as levels: they are its events now. */
  setWindow(detail: Detail, data: EventsData, index: Uint32Array): void {
    const at = this.layers.findIndex((l) => l.detail === detail);
    if (at < 0) return;
    const layer = this.makeLayer(data, index);
    layer.detail = detail;
    this.layers[at] = layer;
    if (this.hovered && !this.hovered.bar && !this.hovered.val && this.hovered.layer === at) picking.setHovered(this, null);
    this.rebase(true);
    this.retainDraws();
    this.requestRender();
  }

  /** An intervals layer sent as levels draws other bars (a level's or a window's). */
  showBars(at: number, bars: BarLayer): void {
    this.bars[at] = bars;
    bars.rebase(this.base, this.xscale === "order", this.baseVersion * 1000 + 1);
    bars.setSlots(this.slot);
    bars.recolor(this.theme.accent);
    bars.applyMarks(this.marks[bars.data.spec.name]);
    if (this.hovered?.bar && this.hovered.layer === at) picking.setHovered(this, null);
    this.retainDraws();
  }

  /** The exact times of the order from rank `offset` (a window's). */
  setSequence(offset: number, times: Float64Array): void {
    this.seq?.setSlice(offset, times);
  }

  /** Let the renderer forget what no layer draws any more. */
  retainDraws(): void {
    const keys = new Set([...this.layers.map((l) => l.draw.key), ...this.bars.map((b) => b.draw.key)]);
    for (const l of this.layers) l.detail?.keys(keys);
    for (const b of this.bars) b.detail?.keys(keys);
    this.renderer?.retain(keys);
  }

  // ------------------------------------------------------------------ scales and camera

  /** x positions of a layer's events on the current scale. */
  xsrc(l: Layer): Float64Array {
    return this.xscale === "order" ? l.data.rank : l.data.time;
  }

  private setLimits(): void {
    if (!this.spec) return;
    if (this.xscale === "order") {
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
    if (xscale === "order" && this.spec && !this.spec.sequence?.count) return; // samples only
    if (!this.spec || (xscale === "time" && this.spec.time.kind === "order")) {
      this.xscale = this.spec?.time.kind === "order" ? "order" : xscale;
      this.updateToolbar();
      return;
    }
    if (xscale === this.xscale) return;
    const [a, b] = [this.camera.left, this.camera.right];
    const seq = this.seq;
    this.xscale = xscale;
    this.setLimits();
    if (seq && seq.count) {
      if (xscale === "order") {
        const r0 = seq.lower(a);
        const r1 = seq.upper(b) - 1;
        if (r1 >= r0) this.camera.fit(r0 - 0.5, r1 + 0.5, 0);
        else this.camera.fitExtent();
      } else {
        const i0 = Math.max(0, Math.min(seq.count - 1, Math.floor(a + 0.5)));
        const i1 = Math.max(0, Math.min(seq.count - 1, Math.ceil(b - 0.5)));
        this.camera.fit(seq.time(i0), seq.time(i1), 0.02);
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
    if (this.xscale === "order" && this.seq) {
      a = this.seq.lower(a) - 0.5;
      b = this.seq.upper(b) - 0.5;
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
  rebase(force = false): void {
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
    for (const b of this.bars) b.rebase(this.base, this.xscale === "order", this.baseVersion * 1000 + 1);
  }

  reportView(): void {
    clearTimeout(this.viewTimer);
    this.viewTimer = setTimeout(() => {
      let [a, b] = [this.camera.left, this.camera.right];
      if (this.xscale === "order" && this.seq?.count) {
        const n = this.seq.count;
        a = this.seq.time(Math.max(0, Math.min(n - 1, Math.ceil(a))));
        b = this.seq.time(Math.max(0, Math.min(n - 1, Math.floor(b))));
      }
      this.callbacks.onView?.([a, b], folding.lanesInSight(this));
    }, 250);
  }

  /** Show a view set in Python (plot.view): a time range (null: the whole timeline), and
   * with `lane` (undefined: as it is) the lane of that name at the top, unfolding what it
   * is in (null: from the top). */
  setView(range: [number, number] | null, lane?: string | null): void {
    if (!this.spec) return;
    if (range) this.zoomTo(range);
    else this.resetView();
    if (lane !== undefined) this.scrollToLane(lane);
  }

  scrollToLane(name: string | null): void {
    return folding.scrollToLane(this, name);
  }

  // ------------------------------------------------------------------ layout

  /** Size the canvases to the plot; `dpr`: draw at this many pixels per CSS px (a snapshot). */
  layout(dpr = window.devicePixelRatio || 1): void {
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
    folding.clampScroll(this);
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
    if (this.xscale !== "order" || !this.seq?.count) return [this.camera.left, this.camera.right];
    return [this.timeAt(this.camera.left), this.timeAt(this.camera.right)];
  }

  /** The time at position x (ticks; on the Order scale interpolated between the events). */
  private timeAt(x: number): number {
    if (this.xscale !== "order" || !this.seq?.count) return x;
    const seq = this.seq;
    const i = Math.max(0, Math.min(seq.count - 1, Math.floor(x)));
    const j = Math.min(seq.count - 1, i + 1);
    const f = Math.max(0, Math.min(1, x - i));
    return seq.time(i) + (seq.time(j) - seq.time(i)) * f;
  }

  /** The position of time t (ticks) on the current scale. */
  xAt(t: number): number {
    if (this.xscale !== "order" || !this.seq?.count) return t;
    const seq = this.seq;
    const j = seq.lower(t);
    if (j <= 0) return -0.5;
    if (j >= seq.count) return seq.count - 0.5;
    const span = seq.time(j) - seq.time(j - 1);
    return j - 1 + (span > 0 ? (t - seq.time(j - 1)) / span : 1);
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
  shareCursor(px: number | null): void {
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
      const indent = tree && i < tree.depth.length ? folding.treeIndent(this, tree.depth[i]) : 0;
      w = Math.max(w, indent + ctx.measureText(names[i]).width);
    }
    return Math.round(Math.min(this.width * (tree ? 0.35 : 0.3), Math.max(48, w + 20)));
  }

  headers: { list: number[]; set: Set<number> } | null = null;

  // ------------------------------------------------------------------ rows and folding

  rowKey = "";

  plot(): { x: number; y: number; w: number; h: number } {
    return { x: this.gutter, y: this.axisH, w: Math.max(10, this.width - this.gutter - this.padRight), h: Math.max(10, this.height - this.axisH - PAD_BOTTOM) };
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

  renderFrame(): void {
    return rendering.renderFrame(this);
  }

  // ------------------------------------------------------------------ front canvas

  /** Boxes of stem labels as drawn in the last frame (for picking). */
  stemHits: { layer: number; index: number; x0: number; y0: number; x1: number; y1: number }[] = [];
  /** Badges ("+N") of events without a box, as drawn in the last frame: a click zooms in. */
  badgeHits: { x0: number; y0: number; x1: number; y1: number; a: number; b: number; n: number }[] = [];
  /** Per stems layer: whether its lanes have room for a level of boxes (else its text goes
   * beside the marks). */
  stemsFit = new WeakMap<Layer, boolean>();
  /** Per stems layer: the boxes laid out for a view (kept while only panning). */
  stemCache = new WeakMap<
    Layer,
    {
      key: string;
      left: number;
      a: number;
      b: number;
      boxH: number;
      start: number;
      placed: Map<number, StemPlaced[]>;
      /** Each event's box lines (wrapped), and whether a line is the box's head (the time). */
      rows: Map<number, { text: string; head: boolean }[]>;
      /** Per badge (its negative index): the events it stands for, their span (x units), and
       * where they are (row; px at layout). */
      clusters: Map<number, { n: number; a: number; b: number; row: number; px0: number; px1: number }>;
      /** Badges with no place above or below: drawn on the line, around their events. */
      onLine: number[];
    }
  >();

  valueView(plot = this.plot()): ValueView {
    return drawing.valueView(this, plot);
  }

  // ------------------------------------------------------------------ picking

  pick(px: number, py: number): Hit | null {
    return picking.pick(this, px, py);
  }

  // ------------------------------------------------------------------ tools and input

  /** Switch the tool (Pan, Zoom, Select); Select only while something can be selected. */
  setTool(tool: Tool, fromUser = false): void {
    if (!TOOLS.includes(tool)) return;
    const next = this.offeredTools().includes(tool) ? tool : "pan";
    if (next === this.tool) return;
    this.tool = next;
    this.stage.dataset.tool = next;
    input.cancelDrag(this);
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
    const [a, b] = this.xscale === "order" ? [-0.5, Math.max(0.5, (this.spec.sequence?.count ?? 1) - 0.5)] : this.spec.time.extent;
    const span = (b - a) * 1.06 || 1;
    const tol = span * 1e-3;
    return Math.abs(this.camera.span - span) > tol || Math.abs(this.camera.left - (a - (b - a) * 0.03)) > tol || this.scrollY > 0.5;
  }

  /** Remember the view before a navigation, for Back (Backspace). */
  pushHistory(): void {
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
      folding.clampScroll(this);
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

  onFullscreenChange = (): void => {
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

  toggleLegend(): void {
    this.setLegend(!this.showLegend);
    this.callbacks.onLegend?.(this.showLegend);
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
    const seq = this.xscale === "order";
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
      // a layer sent as levels: its events there, from its bins
      const e = l.detail?.extent(this.xscale, lane, last);
      if (e) {
        a = Math.min(a, e[0]);
        b = Math.max(b, e[1]);
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
    folding.clampScroll(this);
    this.afterMove();
  }

  afterMove(): void {
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

  flashNotice(text: string): void {
    if (this.status) return;
    this.notice.textContent = text;
    this.notice.classList.add("atl-show");
    clearTimeout(this.noticeTimer);
    this.noticeTimer = setTimeout(() => {
      if (!this.status) this.notice.classList.remove("atl-show");
    }, 1600);
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
    const box = b.box(index, drawing.barView(this));
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
