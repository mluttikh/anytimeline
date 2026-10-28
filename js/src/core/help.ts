// The "Mouse and keys" panel (?): what each gesture and key does, for the tools on offer.

import type { Tool } from "./toolbar";

type Row = [string, string];

export function helpSections(tools: Tool[], fullscreen: boolean, tree = false): [string, Row[]][] {
  const sections: [string, Row[]][] = [
    [
      "Every tool",
      [
        ["Wheel", "zoom time (after a click into the plot, or with Ctrl/⌘)"],
        ["Shift + wheel", "scroll lanes"],
        ["Hold Space + drag", "pan"],
        ["Drag on the time axis", "zoom to that range (Select: select it)"],
        ["Hover", "the event's details"],
      ],
    ],
    [
      "Pan",
      [
        ["Drag", "move through time and lanes"],
        ["Shift + drag", "zoom to a time range"],
        ["Shift/Ctrl/⌘ + click", "add or remove an event"],
        ["Alt + click", "remove an event"],
        ["Double-click", "the whole timeline"],
      ],
    ],
    [
      "Zoom",
      [
        ["Drag", "zoom to a time range"],
        ["Click", "zoom in 2×"],
        ["Alt + click", "zoom out 2×"],
      ],
    ],
  ];
  if (tools.includes("select")) {
    sections.push([
      "Select",
      [
        ["Drag", "select the events in a box"],
        ["Click", "select an event"],
        ["Shift/Ctrl/⌘", "add to the selection"],
        ["Alt", "remove from it"],
        ["Ctrl/⌘ Z · Shift+Ctrl/⌘ Z", "undo · redo a change of the selection"],
      ],
    ]);
  }
  sections.push([
    "Measure",
    [
      ["Drag", "from a mark's start or end to another's: the time between"],
      ["Shift + drag", "to or from a free time"],
      ["Double-click a bar", "its length"],
      ["Click a measure's time", "select it: drag its ends, Delete removes it"],
      ["Hover a measure's time", "both times, and the time between exactly"],
    ],
  ]);
  if (tree) {
    sections.push([
      "Lanes in a tree",
      [
        ["Click a name with ▸ / ▾", "fold or unfold the lanes under it"],
        ["Alt + click", "with every level under it"],
        ["Double-click a name", "zoom to it and everything under it"],
        ["[ · ]", "fold all · unfold all"],
      ],
    ]);
  }
  sections.push([
    "Keys",
    [
      ["p · z · s", "Pan · Zoom · Select"],
      ["t", "Time / Order"],
      ["0", "the whole timeline"],
      ["Backspace", "previous view"],
      ["+ · −", "zoom in · out"],
      ["← → ↑ ↓", "pan time · scroll lanes"],
      ["Esc", fullscreen ? "leave full screen (the browser's)" : "cancel a box, then clear the selection"],
      ["d", "spread overlapping events, or not"],
      ["/ · Ctrl/⌘ F", "find text or lanes (Enter · Shift+Enter: next · previous)"],
      [". · ,", "the next · previous mark in the lane"],
      ["F", "fit the view to that mark"],
      ["a", "annotate: drag over a time range, or click a time"],
      ["c", "on a mark, then on another: an arrow between them"],
      ["m", "on one end, then on the other: measure the time between"],
      ["M", "on a bar: measure its length"],
      ["> · <", "move a measure's second end to the next · previous edge"],
      ["l · f · ?", "legend · full screen · this help"],
    ],
  ]);
  return sections;
}

export function buildHelp(tools: Tool[], fullscreen: boolean, onClose: () => void, tree = false): HTMLElement {
  const panel = document.createElement("div");
  panel.className = "atl-help";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Mouse and keys");
  panel.tabIndex = -1;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "atl-button atl-help-close";
  close.textContent = "Close";
  close.addEventListener("click", (e) => {
    e.stopPropagation();
    onClose();
  });
  const title = document.createElement("div");
  title.className = "atl-help-title";
  title.textContent = "Mouse and keys";
  panel.append(close, title);
  const columns = document.createElement("div");
  columns.className = "atl-help-columns";
  for (const [heading, rows] of helpSections(tools, fullscreen, tree)) {
    const section = document.createElement("section");
    const h = document.createElement("h4");
    h.textContent = heading;
    section.append(h);
    for (const [k, v] of rows) {
      const row = document.createElement("div");
      row.className = "atl-help-row";
      const kk = document.createElement("kbd");
      kk.textContent = k;
      const vv = document.createElement("span");
      vv.textContent = v;
      row.append(kk, vv);
      section.append(row);
    }
    columns.append(section);
  }
  panel.append(columns);
  panel.addEventListener("pointerdown", (e) => e.stopPropagation());
  panel.addEventListener("wheel", (e) => e.stopPropagation());
  return panel;
}
