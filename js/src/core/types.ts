// The scene specification Python sends (Timeline._spec), and the shapes the view works with.

export type RendererKind = "webgpu" | "webgl2" | "canvas2d";
export type RendererPreference = "auto" | RendererKind;
export type XScale = "time" | "sequence";

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
  /** Pairs of bar indices: an arrow from the end of the first to the start of the second. */
  links: { pairs: BufferRef; count: number } | null;
  unit_ns: number;
  /** Write each bar's duration right of it. */
  durations?: boolean;
  /** False: an open bar (no end) does not fade out (states: the lane is still in it). */
  fade_open?: boolean;
  /** The critical path (layers with a tree): rows (bar, from, to); from and to are instants,
   * 2 × bar for a bar's start and 2 × bar + 1 for its end. */
  critical?: { segments: BufferRef; count: number } | null;
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
}

export type LayerSpec = EventsLayerSpec | IntervalsLayerSpec | ValuesLayerSpec;

export interface MarkerSpec {
  /** Time in ticks. */
  x: number;
  label: string;
  color: string | null;
}

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
  sequence: { times: BufferRef; count: number } | null;
  markers?: MarkerSpec[];
}

/** Where buffers come from: Python (BufferStore), or a page with the data in it. */
export interface DataSource {
  has(id: string): boolean;
  get(id: string): ArrayBuffer;
  ensure(ids: string[]): Promise<void>;
}
