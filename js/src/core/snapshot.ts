// A picture of the plot (Save as PNG): the title, the three canvases and the legend, drawn
// into one canvas. The legend is HTML, so it is painted from its elements as laid out: text
// where each piece of text is, each swatch (an SVG) as an image where it is.

type Paint = (ctx: CanvasRenderingContext2D, dy: number) => void;

/**
 * Prepare to paint `legend` (positions relative to `stage`). Loading the swatch images is
 * asynchronous; the painting itself is not, so the caller can draw the GPU canvas and the
 * legend in one task (a WebGPU canvas can only be read in the task that drew it).
 */
export async function legendPainter(legend: HTMLElement, stage: HTMLElement): Promise<Paint> {
  const origin = stage.getBoundingClientRect();
  const at = (el: Element) => {
    const r = el.getBoundingClientRect();
    return { x: r.left - origin.left, y: r.top - origin.top, w: r.width, h: r.height };
  };
  const box = at(legend);
  const style = getComputedStyle(legend);
  const steps: Paint[] = [];
  // the legend's own box: its background, and its border when it has one
  steps.push((ctx, dy) => {
    ctx.fillStyle = style.backgroundColor;
    roundRect(ctx, box.x, box.y + dy, box.w, box.h, parseFloat(style.borderTopLeftRadius) || 0);
    ctx.fill();
    if (parseFloat(style.borderTopWidth) > 0) {
      ctx.strokeStyle = style.borderTopColor;
      ctx.lineWidth = parseFloat(style.borderTopWidth);
      ctx.stroke();
    }
  });
  const muted = getComputedStyle(legend).getPropertyValue("--atl-muted").trim() || "#5e6875";
  const images: Promise<void>[] = [];
  for (const el of legend.querySelectorAll<HTMLElement | SVGSVGElement>("*")) {
    if (el instanceof SVGSVGElement) {
      const r = at(el);
      const source = new XMLSerializer().serializeToString(el).replaceAll("var(--atl-muted)", muted);
      const img = new Image();
      images.push(
        new Promise((resolve) => {
          img.onload = () => resolve();
          img.onerror = () => resolve();
        }),
      );
      img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(source.includes("xmlns=") ? source : source.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"'))}`;
      steps.push((ctx, dy) => {
        if (img.complete && img.naturalWidth) ctx.drawImage(img, r.x, r.y + dy, r.w, r.h);
      });
      continue;
    }
    if (!(el instanceof HTMLElement) || el.closest("svg")) continue;
    if (el.classList.contains("atl-legend-bar")) {
      const r = at(el);
      const colors = el.style.background.match(/#[0-9a-f]{3,8}|rgba?\([^)]*\)/gi) ?? [];
      steps.push((ctx, dy) => {
        const g = ctx.createLinearGradient(r.x, 0, r.x + r.w, 0);
        colors.forEach((c, i) => g.addColorStop(colors.length > 1 ? i / (colors.length - 1) : 0, c));
        ctx.fillStyle = g;
        ctx.fillRect(r.x, r.y + dy, r.w, r.h);
      });
      continue;
    }
    // text: an element whose children are text only
    const text = [...el.childNodes].every((n) => n.nodeType === Node.TEXT_NODE) ? (el.textContent ?? "").trim() : "";
    if (!text) continue;
    const r = at(el);
    const s = getComputedStyle(el);
    steps.push((ctx, dy) => {
      ctx.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
      ctx.fillStyle = s.color;
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      ctx.fillText(text, r.x, r.y + dy + r.h / 2);
    });
  }
  await Promise.all(images);
  return (ctx, dy) => {
    ctx.save();
    for (const step of steps) step(ctx, dy);
    ctx.restore();
  };
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
  else ctx.rect(x, y, w, h);
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
