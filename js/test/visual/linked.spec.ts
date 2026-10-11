import { expect, type Page, test } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// Linked plots (Timeline.link), in a page from save_html: the plots line up, zoom together and
// show each other's pointer.
const file = resolve(dirname(fileURLToPath(import.meta.url)), "scenes/saved_linked.html");

async function open(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto(pathToFileURL(file).href);
  const hosts = page.locator(".anytimeline-embed");
  await expect(hosts).toHaveCount(2);
  for (let i = 0; i < 2; i++) await expect(hosts.nth(i)).toHaveAttribute("data-state", "ready", { timeout: 15_000 });
  return errors;
}

const views = (page: Page) =>
  page.locator(".atl-root").evaluateAll((roots) =>
    roots.map((r: any) => {
      const v = r.__view;
      const plot = v.plot();
      // the shown range as absolute ms: the plots have their own origins and units
      const t = v.spec.time;
      const unitMs = ({ s: 1e3, ms: 1, us: 1e-3, ns: 1e-6 } as Record<string, number>)[t.unit];
      const origin = Number(BigInt(t.origin_ns) / 1000000n);
      const abs = (x: number) => origin + x * unitMs;
      return {
        x: plot.x,
        w: plot.w,
        left: abs(v.camera.left),
        right: abs(v.camera.right),
        cursor: v.linkedCursor === null ? null : abs(v.linkedCursor),
      };
    }),
  );

/** Half a pixel of a plot's time: closer than that, two plots show the same. */
const halfPixel = (v: { left: number; right: number; w: number }) => ((v.right - v.left) / v.w) * 0.5;

test("linked plots line up, zoom together and show each other's pointer", async ({ page }) => {
  const errors = await open(page);
  let [a, b] = await views(page);
  // the same gutter and width: the time axes line up
  expect(a.x).toBe(b.x);
  expect(a.w).toBe(b.w);
  // the same time range, though in other units
  expect(Math.abs(a.left - b.left)).toBeLessThan(halfPixel(a));
  // a wheel zoom in the first: the second follows
  const first = page.locator(".atl-stage").first();
  const box = (await first.boundingBox())!;
  await first.click({ position: { x: box.width * 0.6, y: box.height * 0.5 } });
  const before = a.right - a.left;
  await page.mouse.wheel(0, -400);
  await page.waitForTimeout(150);
  [a, b] = await views(page);
  expect(a.right - a.left).toBeLessThan(before * 0.95); // zoomed in
  expect(Math.abs(a.left - b.left)).toBeLessThan(halfPixel(a));
  expect(Math.abs(a.right - b.right)).toBeLessThan(halfPixel(a));
  // the pointer over the first: a line in the second, at the same time
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.6);
  [a, b] = await views(page);
  expect(b.cursor).not.toBeNull();
  expect(b.cursor).toBeGreaterThan(a.left);
  expect(b.cursor).toBeLessThan(a.right);
  await page.mouse.move(box.x + box.width * 0.5, box.y - 40); // off the plot
  [, b] = await views(page);
  expect(b.cursor).toBeNull();
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/shots/saved_linked.png", fullPage: true });
});
