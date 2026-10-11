// The header: title, counts, the hint for the active tool, and the toolbar (tools, scale,
// view, selection, legend, full screen, help). One row of icon buttons; a narrow plot wraps
// to a second row rather than hiding buttons.

import { ICONS } from "./icons";
import type { XScale } from "./types";

export type Tool = "pan" | "zoom" | "select";
export const TOOLS: Tool[] = ["pan", "zoom", "select"];

export interface ToolbarActions {
  tool(tool: Tool): void;
  xscale(xscale: XScale): void;
  previous(): void;
  home(): void;
  clear(): void;
  legend(): void;
  fullscreen(): void;
  /** Save the plot as a PNG image. */
  image(): void;
  help(): void;
  /** Text size in px, or null to go back to the default. */
  fontSize(px: number | null): void;
}

export interface ToolbarState {
  tool: Tool;
  /** Tools on offer (Select only when something can be selected). */
  tools: Tool[];
  xscale: XScale;
  /** Time is off for data with an order only. */
  timeAvailable: boolean;
  /** Order is off for plots of samples only (values layers): there is no order of events. */
  orderAvailable: boolean;
  canGoBack: boolean;
  zoomed: boolean;
  selected: number;
  legend: boolean;
  hasLegend: boolean;
  fullscreen: boolean;
  fullscreenAvailable: boolean;
  fontSize: number;
}

export const FONT_SIZES = { min: 8, max: 24, default: 12 };

const TOOL_TIPS: Record<Tool, string> = {
  pan: "Pan: drag to move through time and lanes · key p",
  zoom: "Zoom: drag over a time range to show it; click to zoom in, Alt-click to zoom out · key z",
  select: "Select: drag a box, or click an event; Shift adds, Alt removes · key s",
};

/** What a drag does with each tool: the hint next to the counts. */
export const HINTS: Record<Tool, string> = {
  pan: "Drag: pan · Shift-drag: zoom to a range",
  zoom: "Drag: zoom to a time range · Alt-click: zoom out",
  select: "Drag: select a box · Shift: add · Alt: remove",
};

function button(icon: string, label: string, tip: string, onClick: () => void): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "atl-button atl-icon-button";
  b.innerHTML = icon;
  b.setAttribute("aria-label", label);
  b.title = tip;
  b.addEventListener("click", (e) => {
    e.stopPropagation();
    onClick();
  });
  return b;
}

function textButton(text: string, label: string, onClick: () => void): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "atl-button atl-small-button";
  b.textContent = text;
  b.setAttribute("aria-label", label);
  b.title = label;
  b.addEventListener("click", (e) => {
    e.stopPropagation();
    onClick();
  });
  return b;
}

export class Toolbar {
  readonly element: HTMLDivElement;
  readonly hint: HTMLSpanElement;
  private readonly toolButtons: Record<Tool, HTMLButtonElement>;
  private readonly toolGroup: HTMLDivElement;
  private readonly scaleButtons: Record<XScale, HTMLButtonElement>;
  private readonly back: HTMLButtonElement;
  private readonly home: HTMLButtonElement;
  private readonly clear: HTMLButtonElement;
  private readonly legend: HTMLButtonElement;
  private readonly full: HTMLButtonElement;
  private readonly textButton: HTMLButtonElement;
  private readonly popover: HTMLDivElement;
  private readonly sizeLabel: HTMLSpanElement;
  private fontSize = FONT_SIZES.default;

  private closePopover = (e: Event): void => {
    if (!this.popover.hidden && !this.popover.parentElement?.contains(e.target as Node)) this.togglePopover(false);
  };

  togglePopover(open = this.popover.hidden): void {
    this.popover.hidden = !open;
    this.textButton.setAttribute("aria-expanded", String(open));
  }

  destroy(): void {
    document.removeEventListener("pointerdown", this.closePopover, true);
  }

  constructor(actions: ToolbarActions) {
    this.element = document.createElement("div");
    this.element.className = "atl-toolbar";
    this.element.setAttribute("role", "toolbar");
    this.element.setAttribute("aria-label", "Plot tools");
    this.hint = document.createElement("span");
    this.hint.className = "atl-hint";

    this.toolGroup = document.createElement("div");
    this.toolGroup.className = "atl-group";
    this.toolButtons = {
      pan: button(ICONS.pan, "Pan", TOOL_TIPS.pan, () => actions.tool("pan")),
      zoom: button(ICONS.zoom, "Zoom", TOOL_TIPS.zoom, () => actions.tool("zoom")),
      select: button(ICONS.select, "Select", TOOL_TIPS.select, () => actions.tool("select")),
    };
    this.toolGroup.append(...TOOLS.map((t) => this.toolButtons[t]));

    const scale = document.createElement("div");
    scale.className = "atl-group";
    this.scaleButtons = {
      time: button(ICONS.time, "Time", "Time: events at their time · key t", () => actions.xscale("time")),
      sequence: button(ICONS.order, "Order", "Order: events in the order they happened, evenly spaced · key t", () => actions.xscale("sequence")),
    };
    scale.append(this.scaleButtons.time, this.scaleButtons.sequence);

    this.back = button(ICONS.previous, "Previous view", "Previous view · Backspace", actions.previous);
    this.home = button(ICONS.home, "Whole timeline", "The whole timeline · key 0, or double-click with Pan", actions.home);
    this.clear = button(ICONS.close, "Clear the selection", "Clear the selection · Esc", actions.clear);
    this.clear.classList.add("atl-clear");
    this.legend = button(ICONS.legend, "Legend", "Show or hide the legend · key l", actions.legend);
    this.full = button(ICONS.expand, "Full screen", "Full screen · key f, Esc to leave", actions.fullscreen);
    const help = button(ICONS.help, "Mouse and keys", "Mouse and keys · key ?", actions.help);
    const image = button(ICONS.image, "Save as PNG", "Save the plot as a PNG image", actions.image);

    // text size: a button that opens − size + and Reset
    const text = document.createElement("div");
    text.className = "atl-popover-anchor";
    this.textButton = button(ICONS.text, "Text size", "Text size", () => this.togglePopover());
    this.popover = document.createElement("div");
    this.popover.className = "atl-popover";
    this.popover.hidden = true;
    this.popover.setAttribute("role", "group");
    this.popover.setAttribute("aria-label", "Text size");
    const step = (delta: number) => () => actions.fontSize(Math.max(FONT_SIZES.min, Math.min(FONT_SIZES.max, this.fontSize + delta)));
    const smaller = textButton("−", "Smaller text", step(-1));
    const larger = textButton("+", "Larger text", step(1));
    this.sizeLabel = document.createElement("span");
    this.sizeLabel.className = "atl-size";
    const reset = textButton("Reset", "Default text size", () => actions.fontSize(null));
    const label = document.createElement("span");
    label.className = "atl-popover-label";
    label.textContent = "Text size";
    this.popover.append(label, smaller, this.sizeLabel, larger, reset);
    this.popover.addEventListener("pointerdown", (e) => e.stopPropagation());
    text.append(this.textButton, this.popover);
    document.addEventListener("pointerdown", this.closePopover, true);

    this.element.append(this.toolGroup, scale, this.back, this.home, this.clear, this.legend, text, image, this.full, help);
  }

  update(s: ToolbarState): void {
    const shown = TOOLS.filter((t) => s.tools.includes(t));
    for (const t of TOOLS) {
      const b = this.toolButtons[t];
      b.hidden = !shown.includes(t);
      b.classList.toggle("atl-last", t === shown[shown.length - 1]);
      b.setAttribute("aria-pressed", String(s.tool === t));
    }
    for (const xs of ["time", "sequence"] as XScale[]) {
      this.scaleButtons[xs].setAttribute("aria-pressed", String(s.xscale === xs));
    }
    this.scaleButtons.time.disabled = !s.timeAvailable;
    this.scaleButtons.sequence.disabled = !s.orderAvailable;
    this.back.disabled = !s.canGoBack;
    this.home.disabled = !s.zoomed;
    this.clear.hidden = s.selected === 0;
    this.clear.title = `Clear the selection (${s.selected} selected) · Esc`;
    this.legend.hidden = !s.hasLegend;
    this.legend.setAttribute("aria-pressed", String(s.legend));
    this.full.hidden = !s.fullscreenAvailable;
    this.full.innerHTML = s.fullscreen ? ICONS.collapse : ICONS.expand;
    this.full.setAttribute("aria-label", s.fullscreen ? "Leave full screen" : "Full screen");
    this.full.title = s.fullscreen ? "Leave full screen · key f or Esc" : "Full screen · key f, Esc to leave";
    this.hint.textContent = HINTS[s.tool];
    this.fontSize = s.fontSize;
    this.sizeLabel.textContent = `${s.fontSize} px`;
    this.textButton.title = `Text size: ${s.fontSize} px`;
  }
}
