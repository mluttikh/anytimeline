// The Export menu (key e): copy, download or save a picture of the plot. The PNG is the
// browser's snapshot (the screen as drawn: works in pages without Python); the SVG is drawn
// by Python (Timeline.to_svg) for the view as shown, so it needs a kernel.

/** What the plot shows, for Python to draw as SVG. */
export interface FigureRequest {
  /** Size of the picture in CSS px: the plot's width, and its stage with the title. */
  width: number;
  height: number;
  /** The time range in sight, in the spec's ticks (also with the Order scale). */
  range: [number, number];
  /** The lanes in sight, top to bottom. */
  lanes: string[];
  /** Per lane of the tree: 1 open, 0 folded (empty without a tree). */
  open: number[];
  theme: "light" | "dark";
}

export type ExportHow = "copy" | "copy-svg" | "png" | "svg" | "save-png" | "save-svg";

export interface ExportEntry {
  how: ExportHow;
  label: string;
  note: string;
}

/** What a host can do, for the menu's entries. */
export interface ExportAbilities {
  /** PNG on the clipboard: a secure page (https or localhost) with ClipboardItem. */
  copyImages: boolean;
  /** SVG on the clipboard too (Chromium, VS Code). */
  copySvg: boolean;
  /** Python draws SVGs (a kernel is connected). */
  svg: boolean;
  /** Python writes files next to the notebook. */
  save: boolean;
}

/** The menu's entries, in order, for what this page can do. */
export function exportEntries(can: ExportAbilities): ExportEntry[] {
  const out: ExportEntry[] = [];
  if (can.copyImages) out.push({ how: "copy", label: "Copy image", note: "PNG, to paste into slides" });
  if (can.copyImages && can.copySvg && can.svg) out.push({ how: "copy-svg", label: "Copy as vector", note: "SVG, sharp at any size; a PNG for other apps" });
  out.push({ how: "png", label: "Download PNG", note: "an image file" });
  if (can.svg) out.push({ how: "svg", label: "Download SVG", note: "a vector image (PowerPoint, Keynote, Word)" });
  if (can.save) {
    out.push({ how: "save-png", label: "Save PNG next to the notebook", note: "a file where the notebook runs" });
    if (can.svg) out.push({ how: "save-svg", label: "Save SVG next to the notebook", note: "a vector file where the notebook runs" });
  }
  return out;
}

/** Whether this page may put images on the clipboard (a secure context: https or localhost). */
export function canCopyImages(): boolean {
  return typeof window !== "undefined" && window.isSecureContext && typeof ClipboardItem !== "undefined" && !!navigator.clipboard?.write;
}

/** Whether this browser can put an SVG on the clipboard (Chrome, Edge and VS Code can). */
export function canCopySvg(): boolean {
  return canCopyImages() && typeof ClipboardItem.supports === "function" && ClipboardItem.supports("image/svg+xml");
}

/**
 * Put a PNG on the clipboard. The image is passed as a promise, so the clipboard is claimed
 * during the click (browsers require that, Safari strictly) while the picture is drawn.
 */
export async function copyPng(png: Promise<Blob>): Promise<void> {
  await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
}

/**
 * Put an SVG on the clipboard with a PNG of it beside: an app that takes SVG pastes the
 * vector picture, any other the PNG; both the same picture. Promises, as for copyPng.
 */
export async function copySvg(svg: Promise<string>, png: Promise<Blob>): Promise<void> {
  const vector = svg.then((text) => new Blob([text], { type: "image/svg+xml" }));
  await navigator.clipboard.write([new ClipboardItem({ "image/svg+xml": vector, "image/png": png })]);
}

/** PNG pixels per CSS pixel: sharp on slides and high-resolution screens. */
export const PNG_SCALE = 2;

/** Draw an SVG (with width and height) as a PNG, `scale` pixels per SVG unit. */
export async function svgToPng(svg: string, scale = PNG_SCALE): Promise<Blob> {
  const size = /<svg[^>]*\bwidth="([\d.]+)"[^>]*\bheight="([\d.]+)"/.exec(svg);
  const width = size ? Number(size[1]) : 960;
  const height = size ? Number(size[2]) : 540;
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("no PNG"))), "image/png"));
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** SVGs larger than this are slow to show in slides: the message says so. */
export const LARGE_SVG_BYTES = 1_000_000;

/** A size in kB or MB. */
export function byteSize(bytes: number): string {
  return bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} kB`;
}

/** What a copied SVG was: its size, and a hint when it is large. */
export function svgCopiedMessage(bytes: number): string {
  return bytes > LARGE_SVG_BYTES
    ? `Copied as SVG (${byteSize(bytes)}): large, so slow in slides. Copy image (PNG) pastes faster`
    : `Copied as SVG (${byteSize(bytes)}): paste it into your slides`;
}

/** Whether a CSS colour is dark (the plot's background: its theme). */
export function isDark(color: string): boolean {
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return false;
  ctx.fillStyle = "#ffffff";
  ctx.fillStyle = color;
  const hex = /^#([0-9a-f]{6})/i.exec(String(ctx.fillStyle));
  const rgb = hex ? [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16)) : (String(ctx.fillStyle).match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
  if (rgb.length < 3) return false;
  const [r, g, b] = rgb;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 128;
}

/** Offer a blob as a download named `name`. */
export function download(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.style.display = "none";
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** A file name from a plot's title: letters, digits and dashes. */
export function fileName(title: string, ext: string): string {
  const base = title.trim().toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "");
  return `${base || "timeline"}.${ext}`;
}
