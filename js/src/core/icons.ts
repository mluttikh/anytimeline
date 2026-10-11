// Toolbar icons as inline SVG: the same on every platform and font. 16 × 16, lines in the
// button's text colour.

const svg = (body: string) =>
  `<svg class="atl-icon" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

export const ICONS = {
  /** Pan: arrows in four directions. */
  pan: svg('<path d="M8 1.75v12.5M1.75 8h12.5"/><path d="M6.25 3.5 8 1.75 9.75 3.5M6.25 12.5 8 14.25l1.75-1.75M3.5 6.25 1.75 8 3.5 9.75M12.5 6.25 14.25 8l-1.75 1.75"/>'),
  /** Zoom: a magnifier with a plus. */
  zoom: svg('<circle cx="6.75" cy="6.75" r="4.5"/><path d="m10 10 3.75 3.75M4.75 6.75h4M6.75 4.75v4"/>'),
  /** Select: a dashed box around two events. */
  select: svg('<rect x="2.25" y="3.25" width="11.5" height="9.5" rx="0.5" stroke-dasharray="2.2 1.8"/><g fill="currentColor" stroke="none"><circle cx="6" cy="8" r="1.4"/><circle cx="10.25" cy="8" r="1.4"/></g>'),
  /** Time: events on a time axis, at their time (gaps that grow). */
  time: svg('<path d="M1.75 13.25h12.5"/><path d="M2.75 3v7.5M4.75 3v7.5M8 3v7.5M13.25 3v7.5"/>'),
  /** Order: events on an axis, evenly spaced. */
  order: svg('<path d="M1.75 13.25h12.5"/><path d="M2.75 3v7.5M6.25 3v7.5M9.75 3v7.5M13.25 3v7.5"/>'),
  /** Display (text size, mark size, spreading): three sliders. */
  display: svg('<path d="M2 4h12M2 8h12M2 12h12"/><g fill="currentColor"><circle cx="5" cy="4" r="1.6"/><circle cx="10.5" cy="8" r="1.6"/><circle cx="7" cy="12" r="1.6"/></g>'),
  /** Text size: a large and a small A. */
  text: svg('<path d="M1.5 13.5 5.25 3l3.75 10.5M2.9 9.75h4.7"/><path d="m10 13.5 2.25-6 2.25 6M10.85 11.35h2.8"/>'),
  /** Home: the whole timeline. */
  home: svg('<path d="M2 7.75 8 2.5l6 5.25"/><path d="M3.75 6.5v7h3.25V10h2v3.5h3.25v-7"/>'),
  /** Back to the previous view. */
  previous: svg('<path d="M4.5 6.5h6a3.25 3.25 0 0 1 0 6.5H7"/><path d="M7 3.5 4 6.5l3 3"/>'),
  /** Clear the selection: a cross. */
  close: svg('<path d="m4.5 4.5 7 7M11.5 4.5l-7 7"/>'),
  /** Legend: a list of swatches. */
  legend: svg('<path d="M7 4.5h6.5M7 8h6.5M7 11.5h6.5"/><g fill="currentColor" stroke="none"><circle cx="3.5" cy="4.5" r="1.4"/><circle cx="3.5" cy="8" r="1.4"/><circle cx="3.5" cy="11.5" r="1.4"/></g>'),
  /** Full screen: four corners pointing out. */
  expand: svg('<path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10"/>'),
  /** Leave full screen: four corners pointing in. */
  collapse: svg('<path d="M6 2.5V6H2.5M13.5 6H10V2.5M10 13.5V10h3.5M2.5 10H6v3.5"/>'),
  /** Save as PNG: an arrow down into a tray. */
  image: svg('<path d="M8 2v8M4.75 6.75 8 10l3.25-3.25"/><path d="M2.5 10.5v2.75h11V10.5"/>'),
  /** Mouse and keys: a question mark in a circle. */
  help: svg('<circle cx="8" cy="8" r="6"/><path d="M6.25 6.25a1.8 1.8 0 1 1 2.55 1.65c-.5.25-.8.6-.8 1.1v.4"/><path d="M8 11.6v.05" stroke-width="2"/>'),
} as const;
