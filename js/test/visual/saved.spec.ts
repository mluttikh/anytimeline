import { expect, test } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// Timeline.save_html: one file that works from disk, without Python or a network.
const file = resolve(dirname(fileURLToPath(import.meta.url)), "scenes/saved_traces.html");

test("a saved page draws from disk, fills the window, has tooltips and folds", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const requests: string[] = [];
  page.on("request", (r) => requests.push(r.url()));
  await page.setViewportSize({ width: 1100, height: 700 });
  await page.goto(pathToFileURL(file).href);
  const host = page.locator(".anytimeline-embed");
  await expect(host).toHaveAttribute("data-state", "ready", { timeout: 15_000 });
  expect(errors).toEqual([]);
  expect(requests.filter((u) => !u.startsWith("file:") && !u.startsWith("data:"))).toEqual([]);
  // the plot fills the window
  const box = (await page.locator(".atl-root").boundingBox())!;
  expect(box.height).toBeGreaterThan(600);
  // a span's tooltip has its columns, from the page
  const p = await page.locator(".atl-root").evaluate((root: any) => root.__view.barPosition(0, 0));
  const stage = (await page.locator(".atl-stage").boundingBox())!;
  await page.mouse.move(stage.x + p.x, stage.y + p.y);
  const tip = page.locator(".atl-tooltip.atl-show");
  await expect(tip).toContainText("service");
  await expect(tip).toContainText("gateway");
  // a click on a name unfolds it
  const before = await page.locator(".atl-root").evaluate((root: any) => root.__view.laneAt.length);
  await page.mouse.click(stage.x + 40, stage.y + p.y);
  const after = await page.locator(".atl-root").evaluate((root: any) => root.__view.laneAt.length);
  expect(after).toBeGreaterThan(before);
  await page.screenshot({ path: "test-results/shots/saved_traces.png" });
});
