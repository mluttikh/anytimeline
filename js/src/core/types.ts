// The scene specification Python sends (Timeline._spec), and the shapes the view works with.

export type RendererKind = "webgpu" | "webgl2" | "canvas2d";
export type RendererPreference = "auto" | RendererKind;
export type XScale = "time" | "order";

export type DType = "float64" | "float32" | "int32" | "uint32" | "uint16" | "uint8" | "utf8";

/** A buffer Python holds, by content id; fetched with a "need" message. */
export interface BufferRef {
  id: string;
  dtype: DType;
  count: number;
  components: number;
  byteLength: number;
}

/**
 * The time axis. Ticks are float64 values relative to the origin: for datetimes and
 * durations ticks of `unit` (absolute ns = origin_ns + tick × ns per unit), for plain
 * numbers the value minus `origin`, for "order" ranks.
 */
export interface TimeSpec {
  kind: "datetime" | "duration" | "number" | "order";
  unit: "" | "s" | "ms" | "us" | "ns";
  /** int64 as a decimal string. */
  origin_ns: string;
  origin: number;
  timezone: string;
  extent: [number, number];
}

export interface CategoryLegend {
  kind: "categories";
  title: string;
  items: { label: string; color: string }[];
}

export interface ContinuousLegend {
  kind: "continuous";
  title: string;
  colors: string[];
  clim: [number, number];
}

export interface EventsLayerSpec {
  type: "events";
  name: string;
  count: number;
  /** Sorted by lane, then time, then order: ticks (or the order where there is no time). */
  time: BufferRef;
  lane: BufferRef;
  /** count of lanes + 1 offsets: lane l's events are lane_starts[l] .. lane_starts[l + 1]. */
  lane_starts: BufferRef;
  rank: BufferRef;
  has_time: boolean;
  overlap: "dodge" | "overlay";
  /** Where the text goes: beside each mark, or in boxes on stems above and below the line. */
  labels?: "beside" | "stems";
  /** Stem labels: straight stems (the box over its event), or curved (a box may move aside). */
  stem_shape?: "straight" | "curved";
  /** Stem labels: the widest a box gets (px); null: 16 × the text size; 0: no limit. */
  label_width?: number | null;
  hover: boolean;
  select: boolean;
  dropped: number;
  color: { rgba: BufferRef | null; solid: string | null; alpha: number; legend: CategoryLegend | ContinuousLegend | null };
  symbol: { values: BufferRef | null; value: string | null; names: string[]; legend: { title: string; items: { label: string; symbol: string }[] } | null };
  size: { values: BufferRef | null; value: number | null; legend: { title: string; items: { label: string; size: number }[] } | null };
  text: BufferRef | null;
  importance: BufferRef | null;
  tooltip: string[];
  route: { segments: BufferRef; count: number; color: string | null; width: number } | null;
  /** A page's events: the table row of each (to copy a measure as Python). */
  table_rows?: BufferRef;
  /** A layer of many events (Python: levels.LEVELS_FROM) is sent as levels: its events
   * counted per lane and bin; the events themselves (none here) come in windows. */
  levels?: LevelsSpec | null;
  /** A window's events: each one's index among the layer's events (Python's order). */
  index?: BufferRef;
}

/** Levels of detail of a layer sent as levels (Python: anytimeline.levels). */
export interface LevelsSpec {
  /** The layer's events. */
  total: number;
  /** The most events in view that are drawn one by one (with fewer, they are asked for). */
  raw: number;
  /** Python serves windows (else, in a page, the levels are all there is). */
  windows: boolean;
  /** The colour categories' names (what a bin's tooltip counts), or null. */
  categories: string[] | null;
  time: LevelScale;
  order: LevelScale;
}

/** The levels of one scale: level k has bins of width top / 4^k from x0. */
export interface LevelScale {
  x0: number;
  top: number;
  levels: LevelSpec[];
}

/** One level: per lane (lane_starts), its bins that hold events, in order. */
export interface LevelSpec {
  k: number;
  width: number;
  count: number;
  /** The most events in one bin. */
  most: number;
  lane_starts: BufferRef;
  /** The first and last event's position in each bin, and how many it holds. */
  lo: BufferRef;
  hi: BufferRef;
  n: BufferRef;
  /** Each bin's representative event (the most important, else the first): its index. */
  top: BufferRef;
  /** Each bin's colour (its most frequent category's, else its representative's), symbol
   * and size; null: the layer's one value. */
  rgba: BufferRef | null;
  symbol: BufferRef | null;
  size: BufferRef | null;
  /** The range a window's bins cover; null: everything. */
  range: [number, number] | null;
}

/** Bars from a start to an end (Python: Timeline.intervals). Sorted by lane, start, end. */
export interface IntervalsLayerSpec {
  type: "intervals";
  name: string;
  count: number;
  start: BufferRef;
  end: BufferRef;
  lane: BufferRef;
  lane_starts: BufferRef;
  /** Sub-row of each bar in its lane, and the number of sub-rows of its lane. */
  row: BufferRef;
  rows: BufferRef;
  /** 1: a milestone (start = end), 2: open (no end; runs to the plot's last time). */
  kind: BufferRef;
  /** Two components: the order of each bar's start and end. */
  rank: BufferRef;
  height: number;
  overlap: "pack" | "overlay";
  hover: boolean;
  select: boolean;
  dropped: number;
  color: { rgba: BufferRef | null; solid: string | null; alpha: number; legend: CategoryLegend | ContinuousLegend | null };
  progress: BufferRef | null;
  text: BufferRef | null;
  tooltip: string[];
  /** A page's bars: the table row of each (to copy a measure as Python). */
  table_rows?: BufferRef;
  /** Pairs of bar indices: an arrow from the end of the first to the start of the second. */
  links: { pairs: BufferRef; count: number } | null;
  unit_ns: number;
  /** Write each bar's duration right of it. */
  durations?: boolean;
  /** False: an open bar (no end) does not fade out (states: the lane is still in it). */
  fade_open?: boolean;
  /** States layers (Python: Timeline.states): each bar's state, and the state column's name.
   * The tooltip then shows every lane's state at the pointer's time. */
  states?: { values: BufferRef; title: string } | null;
  /** The critical path (layers with a tree): rows (bar, from, to); from and to are instants,
   * 2 × bar for a bar's start and 2 × bar + 1 for its end. */
  critical?: { segments: BufferRef; count: number } | null;
  /** Sent as levels (many bars): none above (count 0), these instead. */
  levels?: BarLevelsSpec;
  /** A level's or a window's bars: the index of each among the layer's (0xFFFFFFFF: short
   * bars merged, kind 3), how many bars each holds, and how opaque each is (0–255). */
  index?: BufferRef;
  n?: BufferRef;
  alpha?: BufferRef;
  /** A window's bars: those of level k (absent: every bar there). */
  k?: number;
}

/** Levels of an intervals layer of many bars, per scale: level k has the bars at least
 * top / 4^k long, and the others merged per lane, sub-row and bin of that width. */
export interface BarLevelsSpec {
  total: number;
  /** A window of at most this many bars has every one of them. */
  raw: number;
  windows: boolean;
  time: BarLevelScale;
  order: BarLevelScale;
}

export interface BarLevelScale {
  x0: number;
  top: number;
  levels: BarLevelSpec[];
}

export interface BarLevelSpec extends IntervalsLayerSpec {
  k: number;
  /** Its bins' width (top / 4^k). */
  bin_width: number;
}

/** A number over time per lane (Python: Timeline.values). Sorted by lane, series, time. */
export interface ValuesLayerSpec {
  type: "values";
  name: string;
  count: number;
  time: BufferRef;
  /** float32; NaN: a gap in the line. */
  value: BufferRef;
  /** Runs: one line each (a lane's series): their first samples (count + 1), lanes, colours. */
  runs: { starts: BufferRef; lane: BufferRef; color: BufferRef; count: number };
  /** The series of each run, or null. */
  series: string[] | null;
  series_title: string;
  /** Per lane of the plot: low and high of its band (two float64 components). */
  ylim: BufferRef;
  kind: "line" | "area" | "step";
  width: number;
  hover: boolean;
  select: false;
  dropped: number;
  color: { solid: string | null; alpha: number; legend: CategoryLegend | ContinuousLegend | null };
  tooltip: string[];
  /** Sent as levels (many samples): none above (count 0, the runs kept), these instead. */
  levels?: ValueLevelsSpec;
  /** A level's or a window's samples: the index of each among the layer's. */
  index?: BufferRef;
  /** A window's samples: those that draw them at level k (absent: every sample). */
  k?: number;
}

/** Levels of a values layer of many samples: level k holds the samples that draw it with bins
 * of width top / 4^k from x0 (each run's first, lowest, highest and last sample per bin). */
export interface ValueLevelsSpec {
  total: number;
  /** A window of at most this many samples has every one of them. */
  raw: number;
  windows: boolean;
  x0: number;
  top: number;
  levels: ValueLevelSpec[];
}

export interface ValueLevelSpec extends ValuesLayerSpec {
  k: number;
  /** Its bins' width (top / 4^k). */
  bin_width: number;
}

export type LayerSpec = EventsLayerSpec | IntervalsLayerSpec | ValuesLayerSpec;

/**
 * Lanes that form a tree (the first depth.length lanes; Timeline.intervals with parent=), in
 * depth-first order: lane l's descendants are the lanes l + 1 .. l + size[l] - 1.
 */
export interface LaneTree {
  depth: number[];
  size: number[];
  /** Whether a lane's children show at first. */
  open: boolean[];
  /** The header lanes of groups (layers' group=). */
  header?: number[];
  /** Compact lanes (spans): folding moves the lanes below instead of resizing all. */
  compact?: boolean;
}

export interface SceneSpec {
  version: number;
  time: TimeSpec;
  /** show_names false: no column of lane names (a story of one lane). */
  lanes: { names: string[]; title: string; tree?: LaneTree | null; show_names?: boolean };
  layers: LayerSpec[];
  /** Every instant's time, in the order (the Order scale). With layers sent as levels, every
   * `step`-th (and the last), and the long gaps between them (rows of rank, span). */
  sequence: { times: BufferRef; count: number; step?: number; gaps?: BufferRef } | null;
  /** When Python made it (seconds since the epoch): a new spec is always a change, so it syncs. */
  t?: number;
}

/** Where buffers come from: Python (BufferStore), or a page with the data in it. */
export interface DataSource {
  has(id: string): boolean;
  get(id: string): ArrayBuffer;
  ensure(ids: string[]): Promise<void>;
}

/** Python's answer to a window of a layer sent as levels: its events in a range (an events
 * layer's spec with `index`), or its bins of level `k` there; and the exact times of the
 * order there, from rank `offset`. */
export interface WindowAnswer {
  spec: EventsLayerSpec | LevelSpec | ValuesLayerSpec | IntervalsLayerSpec;
  range: [number, number];
  scale: XScale;
  k: number | null;
  sequence?: { times: BufferRef; offset: number };
}
