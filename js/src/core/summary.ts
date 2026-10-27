// The selection in numbers: a panel over the plot while something is selected, showing
// what Python counted (Timeline.summary): per layer, the totals, then by colour category
// and by lane. All text comes from Python; this only lays it out.

/** A row of the panel: the numbers as text, and what they are of. */
export interface SummaryRow {
  count: string;
  total?: string;
  mean?: string;
  open?: string;
  span?: string;
  min?: string;
  max?: string;
  label?: string;
  color?: string | null;
}

export interface SummaryBlock {
  title: string;
  rows: SummaryRow[];
  /** Rows left out (those with the fewest marks). */
  more: number;
}

export interface LayerSummary {
  layer: string;
  /** The numbers shown, in order: "count", then "total", "mean" (bars), "span" (events),
   * or "mean", "min", "max" (values). */
  columns: (keyof SummaryRow)[];
  total: SummaryRow;
  blocks: SummaryBlock[];
}

const HEADS: Record<string, string> = { count: "count", total: "total", mean: "mean", span: "span", min: "min", max: "max" };

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/** The panel, or null when nothing is selected. `onClose`: its × was clicked. */
export function buildSummary(layers: LayerSummary[], onClose: () => void): HTMLElement | null {
  if (!layers.length) return null;
  const root = el("div", "atl-summary");
  root.setAttribute("role", "region");
  root.setAttribute("aria-label", "Selection summary");
  // its own clicks and scrolling, not the plot's
  for (const type of ["pointerdown", "wheel", "dblclick"]) root.addEventListener(type, (e) => e.stopPropagation());
  const close = el("button", "atl-summary-close", "×");
  close.type = "button";
  close.title = "Hide the summary (until the selection changes)";
  close.setAttribute("aria-label", "Hide the summary");
  close.addEventListener("click", onClose);
  root.append(close);
  for (const s of layers) {
    const table = el("table", "atl-summary-table");
    const span = s.columns.length + 1;
    const n = `${s.total.count} selected`;
    table.append(line("atl-summary-caption", layers.length > 1 ? `${s.layer}: ${n}` : n, span));
    if (s.columns.length > 1) {
      const head = el("tr", "atl-summary-head");
      head.append(el("th", ""));
      for (const c of s.columns) head.append(el("th", "", HEADS[c] ?? String(c)));
      table.append(head, row(s, { ...s.total, label: "all" }, "atl-summary-all"));
    }
    if (s.total.open) table.append(line("atl-summary-note", `${s.total.open}: no duration`, span));
    for (const b of s.blocks) {
      table.append(line("atl-summary-title", `by ${b.title}`, span));
      for (const r of b.rows) table.append(row(s, r, ""));
      if (b.more) table.append(line("atl-summary-more", `+${b.more} more`, span));
    }
    root.append(table);
  }
  return root;
}

/** A row of one cell over all columns. */
function line(cls: string, text: string, span: number): HTMLTableRowElement {
  const tr = el("tr", cls);
  const td = el("td", "", text);
  td.colSpan = span;
  tr.append(td);
  return tr;
}

function row(s: LayerSummary, r: SummaryRow, cls: string): HTMLTableRowElement {
  const tr = el("tr", cls);
  const label = el("td", "atl-summary-label");
  if (r.color) {
    const swatch = el("span", "atl-summary-swatch");
    swatch.style.background = r.color;
    label.append(swatch);
  }
  label.append(document.createTextNode(r.label ?? ""));
  label.title = r.label ?? "";
  tr.append(label);
  for (const c of s.columns) tr.append(el("td", "atl-summary-num", String(r[c] ?? "")));
  return tr;
}
