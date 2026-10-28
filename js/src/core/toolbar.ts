// The header: title, counts, the hint for the active tool, and the toolbar (tools, scale,
// view, selection, legend, full screen, help). One row of icon buttons; a narrow plot wraps
// to a second row rather than hiding buttons.

import { ICONS } from "./icons";
import type { XScale } from "./types";

export type Tool = "pan" | "zoom" | "select" | "measure";
export const TOOLS: Tool[] = ["pan", "zoom", "select", "measure"];

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
  /** Mark size as a factor of the layers' own, or null for 1. */
  markScale(factor: number | null): void;
  /** Spread overlapping events over sub-rows (dodging), or draw them on the lane's line. */
  dodge(on: boolean): void;
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
  markScale: number;
  dodge: boolean;
  /** Whether any layer spreads its events (the switch shows only then). */
  dodges: boolean;
}

export const FONT_SIZES = { min: 8, max: 24, default: 12 };
/** The mark sizes the Display panel steps through (factors of the layers' own sizes). */
export const MARK_SCALES = [0.5, 0.75, 1, 1.25, 1.5, 2];

const TOOL_TIPS: Record<Tool, string> = {
  pan: "Pan: drag to move through time and lanes · key p",
  zoom: "Zoom: drag over a time range to show it; click to zoom in, Alt-click to zoom out · key z",
  select: "Select: drag a box, or click an event; Shift adds, Alt removes · key s",
  measure: "Measure: drag from one mark's start or end to another's; double-click a bar for its length · key m measures from the keyboard",
};

/** What a drag does with each tool: the hint next to the counts. */
export const HINTS: Record<Tool, string> = {
  pan: "Drag: pan · Shift-drag: zoom to a range",
  zoom: "Drag: zoom to a time range · Alt-click: zoom out",
  select: "Drag: select a box · Shift: add · Alt: remove",
  measure: "Drag: measure between edges · Shift: a free time · double-click: a bar's length",
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
  private readonly markLabel: HTMLSpanElement;
  private readonly dodgeBox: HTMLInputElement;
  private readonly dodgeRow: HTMLLabelElement;
  private fontSize = FONT_SIZES.default;
  private markScale = 1;

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
      measure: button(ICONS.measure, "Measure", TOOL_TIPS.measure, () => actions.tool("measure")),
    };
    this.toolGroup.append(...TOOLS.map((t) => this.toolButtons[t]));

    const scale = document.createElement("div");
    scale.className = "atl-group";
    this.scaleButtons = {
      time: button(ICONS.time, "Time", "Time: events at their time · key t", () => actions.xscale("time")),
      order: button(ICONS.order, "Order", "Order: events in the order they happened, evenly spaced · key t", () => actions.xscale("order")),
    };
    scale.append(this.scaleButtons.time, this.scaleButtons.order);

    this.back = button(ICONS.previous, "Previous view", "Previous view · Backspace", actions.previous);
    this.home = button(ICONS.home, "Whole timeline", "The whole timeline · key 0, or double-click with Pan", actions.home);
    this.clear = button(ICONS.close, "Clear the selection", "Clear the selection · Esc", actions.clear);
    this.clear.classList.add("atl-clear");
    this.legend = button(ICONS.legend, "Legend", "Show or hide the legend · key l", actions.legend);
    this.full = button(ICONS.expand, "Full screen", "Full screen · key f, Esc to leave", actions.fullscreen);
    const help = button(ICONS.help, "Mouse and keys", "Mouse and keys · key ?", actions.help);
    const image = button(ICONS.image, "Save as PNG", "Save the plot as a PNG image", actions.image);

    // Display: a button that opens text size, mark size (− value + Reset) and spreading
    const text = document.createElement("div");
    text.className = "atl-popover-anchor";
    this.textButton = button(ICONS.display, "Display", "Display: text size, mark size, spreading", () => this.togglePopover());
    this.popover = document.createElement("div");
    this.popover.className = "atl-popover";
    this.popover.hidden = true;
    this.popover.setAttribute("role", "group");
    this.popover.setAttribute("aria-label", "Display");
    const row = (title: string, ...items: HTMLElement[]) => {
      const label = document.createElement("span");
      label.className = "atl-popover-label";
      label.textContent = title;
      const r = document.createElement("div");
      r.className = "atl-popover-row";
      r.append(label, ...items);
      return r;
    };
    const step = (delta: number) => () => actions.fontSize(Math.max(FONT_SIZES.min, Math.min(FONT_SIZES.max, this.fontSize + delta)));
    this.sizeLabel = document.createElement("span");
    this.sizeLabel.className = "atl-size";
    const markStep = (delta: number) => () => {
      const i = MARK_SCALES.reduce((best, s, k) => (Math.abs(s - this.markScale) < Math.abs(MARK_SCALES[best] - this.markScale) ? k : best), 0);
      actions.markScale(MARK_SCALES[Math.max(0, Math.min(MARK_SCALES.length - 1, i + delta))]);
    };
    this.markLabel = document.createElement("span");
    this.markLabel.className = "atl-size";
    this.dodgeBox = document.createElement("input");
    this.dodgeBox.type = "checkbox";
    this.dodgeBox.addEventListener("change", () => actions.dodge(this.dodgeBox.checked));
    this.dodgeRow = document.createElement("label");
    this.dodgeRow.className = "atl-popover-row atl-popover-check";
    this.dodgeRow.title = "Spread events that would overlap over the lane's height · key d";
    this.dodgeRow.append(this.dodgeBox, document.createTextNode("Spread overlapping events"));
    this.popover.append(
      row("Text size", textButton("−", "Smaller text", step(-1)), this.sizeLabel, textButton("+", "Larger text", step(1)), textButton("Reset", "Default text size", () => actions.fontSize(null))),
      row("Mark size", textButton("−", "Smaller marks", markStep(-1)), this.markLabel, textButton("+", "Larger marks", markStep(1)), textButton("Reset", "Default mark size", () => actions.markScale(null))),
      this.dodgeRow,
    );
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
    for (const xs of ["time", "order"] as XScale[]) {
      this.scaleButtons[xs].setAttribute("aria-pressed", String(s.xscale === xs));
    }
    this.scaleButtons.time.disabled = !s.timeAvailable;
    this.scaleButtons.order.disabled = !s.orderAvailable;
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
    this.markScale = s.markScale;
    this.markLabel.textContent = `×${Number(s.markScale.toFixed(2))}`;
    this.dodgeBox.checked = s.dodge;
    this.dodgeRow.hidden = !s.dodges;
    this.textButton.title = `Display: text ${s.fontSize} px, marks ×${Number(s.markScale.toFixed(2))}${s.dodges ? `, spreading ${s.dodge ? "on" : "off"}` : ""}`;
  }
}
