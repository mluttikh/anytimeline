// The legend: colours, symbols and sizes of each layer, as HTML from the spec alone.

import { fmtNumber } from "./time";
import { SYMBOLS } from "./scene";
import type { LayerSpec } from "./types";
import { tracePath } from "./renderers/symbols";

/** The most items a block of the legend lists. */
export const MAX_ITEMS = 16;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/** A small SVG of symbol `name` in `color` (CSS). */
function symbolIcon(name: string, color: string, size = 10): SVGSVGElement {
  const s = Math.max(0, SYMBOLS.indexOf(name));
  const box = size + 6;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", String(box));
  svg.setAttribute("height", String(box));
  svg.setAttribute("viewBox", `0 0 ${box} ${box}`);
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  const recorder = new PathRecorder();
  tracePath(recorder as unknown as Path2D, s, box / 2, box / 2, size / 2);
  path.setAttribute("d", recorder.d);
  const open = s >= 5;
  path.setAttribute("fill", open ? "none" : color);
  path.setAttribute("stroke", color);
  path.setAttribute("stroke-width", open ? "1.5" : "0");
  svg.append(path);
  return svg;
}

/** A small SVG of a bar in `color` (intervals layers). */
function barIcon(color: string): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("viewBox", "0 0 16 16");
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  for (const [k, v] of Object.entries({ x: "1", y: "4.5", width: "14", height: "7", rx: "1.5", fill: color })) rect.setAttribute(k, v);
  svg.append(rect);
  return svg;
}

/** A small SVG of a line in `color` (values layers). */
function lineIcon(color: string): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("viewBox", "0 0 16 16");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  for (const [k, v] of Object.entries({ d: "M1 11 5 6.5 9 9.5 15 4", fill: "none", stroke: color, "stroke-width": "2", "stroke-linejoin": "round", "stroke-linecap": "round" })) path.setAttribute(k, v);
  svg.append(path);
  return svg;
}

/** Records Path2D calls as SVG path data. */
class PathRecorder {
  d = "";
  moveTo(x: number, y: number): void {
    this.d += `M${x.toFixed(2)} ${y.toFixed(2)}`;
  }
  lineTo(x: number, y: number): void {
    this.d += `L${x.toFixed(2)} ${y.toFixed(2)}`;
  }
  closePath(): void {
    this.d += "Z";
  }
  arc(x: number, y: number, r: number): void {
    this.d = `M${(x - r).toFixed(2)} ${y.toFixed(2)}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
  }
}

export function buildLegend(layers: LayerSpec[], themeColor: string): HTMLElement | null {
  const root = el("div", "atl-legend");
  let any = false;
  for (const layer of layers) {
    const blocks: HTMLElement[] = [];
    const color = layer.color.legend;
    if (color?.kind === "categories") {
      const block = el("div", "atl-legend-block");
      if (color.title) block.append(el("div", "atl-legend-title", color.title));
      const symbol = layer.type === "events" ? (layer.symbol.values ? "circle" : (layer.symbol.value ?? "circle")) : null;
      for (const item of color.items.slice(0, MAX_ITEMS)) {
        const row = el("div", "atl-legend-row");
        const icon = symbol ? symbolIcon(symbol, item.color) : layer.type === "values" ? lineIcon(item.color) : barIcon(item.color);
        row.append(icon, el("span", "", item.label));
        block.append(row);
      }
      if (color.items.length > MAX_ITEMS) block.append(el("div", "atl-legend-more", `+${color.items.length - MAX_ITEMS} more`));
      blocks.push(block);
    } else if (color?.kind === "continuous") {
      const block = el("div", "atl-legend-block");
      if (color.title) block.append(el("div", "atl-legend-title", color.title));
      const bar = el("div", "atl-legend-bar");
      bar.style.background = `linear-gradient(to right, ${color.colors.join(", ")})`;
      const ends = el("div", "atl-legend-ends");
      ends.append(el("span", "", fmtNumber(color.clim[0], 3)), el("span", "", fmtNumber(color.clim[1], 3)));
      block.append(bar, ends);
      blocks.push(block);
    }
    if (layer.type !== "events") {
      if (!blocks.length) continue;
      any = true;
      if (layers.length > 1) root.append(el("div", "atl-legend-layer", layer.name));
      root.append(...blocks);
      continue;
    }
    const sym = layer.symbol.legend;
    if (sym) {
      const block = el("div", "atl-legend-block");
      if (sym.title) block.append(el("div", "atl-legend-title", sym.title));
      const ink = layer.color.rgba ? "var(--atl-muted)" : layer.color.solid && layer.color.solid !== "theme" ? layer.color.solid : themeColor;
      for (const item of sym.items.slice(0, MAX_ITEMS)) {
        const row = el("div", "atl-legend-row");
        row.append(symbolIcon(item.symbol, ink), el("span", "", item.label));
        block.append(row);
      }
      if (sym.items.length > MAX_ITEMS) block.append(el("div", "atl-legend-more", `+${sym.items.length - MAX_ITEMS} more`));
      blocks.push(block);
    }
    const size = layer.size.legend;
    if (size) {
      const block = el("div", "atl-legend-block");
      if (size.title) block.append(el("div", "atl-legend-title", size.title));
      for (const item of size.items) {
        const row = el("div", "atl-legend-row");
        row.append(symbolIcon("circle", "var(--atl-muted)", item.size), el("span", "", item.label));
        block.append(row);
      }
      blocks.push(block);
    }
    if (!blocks.length) continue;
    any = true;
    if (layers.length > 1) root.append(el("div", "atl-legend-layer", layer.name));
    root.append(...blocks);
  }
  return any ? root : null;
}
