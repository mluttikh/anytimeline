import { expect, type Page, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// Plots shown as HTML in a notebook (Timeline(display="html")): each output holds the plot's
// data and the drawing code, runs that code once per page, and starts its own plot. Scenes
// from scripts/make_scenes.py (notebook_outputs).
const scenes = resolve(dirname(fileURLToPath(import.meta.url)), "scenes");

/** Per plot on the page: the time range shown, in absolute ms (the plots have their own
 * origins and units). */
const ranges = (page: Page) =>
  page.locator(".atl-root").evaluateAll((roots) =>
    roots.map((r: any) => {
      const v = r.__view;
      const t = v.spec.time;
      const unitMs = ({ s: 1e3, ms: 1, us: 1e-3, ns: 1e-6 } as Record<string, number>)[t.unit];
      const origin = Number(BigInt(t.origin_ns) / 1000000n);
      return [origin + v.camera.left * unitMs, origin + v.camera.right * unitMs];
    }),
  );

async function ready(page: Page, count: number) {
  const hosts = page.locator(".anytimeline-embed");
  await expect(hosts).toHaveCount(count);
  for (let i = 0; i < count; i++) await expect(hosts.nth(i)).toHaveAttribute("data-state", "ready", { timeout: 15_000 });
}

async function zoomFirst(page: Page) {
  const stage = (await page.locator(".atl-stage").first().boundingBox())!;
  await page.mouse.move(stage.x + stage.width / 2, stage.y + stage.height / 2);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -400);
  await page.keyboard.up("Control");
}

test("outputs of an exported notebook draw, look as widgets and stay linked", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.setViewportSize({ width: 1000, height: 900 });
  await page.goto(pathToFileURL(resolve(scenes, "notebook_outputs.html")).href);
  await ready(page, 2);
  expect(errors).toEqual([]);
  // the note for where scripts do not run is gone, and the output's HTML styling with it
  await expect(page.locator(".anytimeline-note")).toHaveCount(0);
  await expect(page.locator(".jp-RenderedHTMLCommon")).toHaveCount(0);
  // the drawing code ran once, for both outputs
  expect(await page.evaluate(() => Object.keys((window as any).anytimelineEmbeds).length)).toBe(1);
  const before = await ranges(page);
  await zoomFirst(page);
  await expect.poll(async () => (await ranges(page))[0][1] - (await ranges(page))[0][0]).toBeLessThan(before[0][1] - before[0][0]);
  await expect.poll(async () => {
    const [a, b] = await ranges(page);
    return Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]);
  }).toBeLessThan((before[0][1] - before[0][0]) / 1000);
});

test("outputs added as JupyterLab adds them start, and a cell run again replaces its plot", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const outputs: string[] = JSON.parse(readFileSync(resolve(scenes, "notebook_outputs.json"), "utf8"));
  await page.setViewportSize({ width: 1000, height: 900 });
  await page.setContent("<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>");
  // an output's HTML, its scripts run (innerHTML does not run them; JupyterLab copies them)
  const show = (html: string, id: string) =>
    page.evaluate(
      ([html, id]) => {
        const old = document.getElementById(id);
        const cell = document.createElement("div");
        cell.id = id;
        cell.className = "jp-OutputArea-output jp-RenderedHTMLCommon";
        cell.innerHTML = html;
        if (old) old.replaceWith(cell);
        else document.body.append(cell);
        for (const s of [...cell.querySelectorAll("script:not([type])")]) {
          const run = document.createElement("script");
          run.textContent = s.textContent;
          s.replaceWith(run);
        }
      },
      [html, id],
    );
  await show(outputs[0], "cell-1");
  await show(outputs[1], "cell-2");
  await ready(page, 2);
  await show(outputs[0], "cell-1"); // the first cell run again
  await ready(page, 2);
  await expect(page.locator(".atl-root")).toHaveCount(2);
  // the replaced plot left its group of linked plots
  const group = await page.evaluate(() => {
    const reg: Map<string, Set<unknown>> = (globalThis as any).__anytimelineLinks;
    return [...reg.values()].map((s) => s.size);
  });
  expect(group).toEqual([2]);
  expect(errors).toEqual([]);
});

test("a notebook run and exported by nbconvert shows the plot shown as HTML", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(pathToFileURL(resolve(scenes, "nbconvert_export.html")).href);
  await ready(page, 1);
  // (the notebook's widget draws too where its widget manager loads from the internet)
  await expect(page.locator(".anytimeline-embed .atl-root")).toHaveCount(1);
  await expect(page.locator(".anytimeline-embed .atl-title")).toContainText("Exported");
  // the page's own scripts (MathJax, RequireJS) may fail offline; the plot's must not
  expect(errors.filter((e) => /anytimeline|atl-/i.test(e))).toEqual([]);
  await page.screenshot({ path: "test-results/shots/nbconvert_export.png", fullPage: true });
});

test("a marimo app exported as HTML shows the plot shown as HTML (needs internet)", async ({ page }) => {
  // the exported page loads marimo's own code from a CDN; the plot is in a frame of its own
  await page.goto(pathToFileURL(resolve(scenes, "marimo_export.html")).href);
  const frame = page.frameLocator("iframe").first();
  await expect(frame.locator(".anytimeline-embed")).toHaveAttribute("data-state", "ready", { timeout: 30_000 });
  await expect(frame.locator(".atl-title")).toContainText("Exported from marimo");
});
