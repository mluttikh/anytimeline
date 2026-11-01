import { expect, test } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";

// Save as PNG: the picture has the title, the bars (also from the GPU canvas) and the legend.
for (const renderer of ["webgpu", "webgl2", "canvas2d"] as const) {
  test(`a PNG of the plot with ${renderer}`, async ({ page }) => {
    await page.goto(`/test/visual/harness.html?scene=trace_waterfall&renderer=${renderer}`);
    await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 15_000 });
    const perf = await page.evaluate(() => (window as any).__perf);
    if (renderer === "webgpu" && perf.renderer !== "webgpu") test.skip(true, "no WebGPU here");
    // a software WebGPU (SwiftShader on Linux CI) the plot never picks itself ("auto" refuses
    // it); reading its frames back is not reliable
    if (renderer === "webgpu" && /\(software\)/.test(perf.description ?? "")) test.skip(true, "software WebGPU");
    const result = await page.locator(".atl-root").evaluate(async (root: any) => {
      const v = root.__view;
      const blob: Blob = await v.snapshot();
      const bmp = await createImageBitmap(blob);
      const c = document.createElement("canvas");
      c.width = bmp.width;
      c.height = bmp.height;
      const ctx = c.getContext("2d")!;
      ctx.drawImage(bmp, 0, 0);
      // the middle of the first bar (the root span), in the picture's pixels
      const p = v.barPosition(0, 0);
      const k = bmp.width / v.width;
      const titleH = Math.round(v.fs * 2.4);
      const px = ctx.getImageData(Math.round(p.x * k), Math.round((p.y + titleH) * k), 1, 1).data;
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let bin = "";
      for (const b of bytes) bin += String.fromCharCode(b);
      return { w: bmp.width, h: bmp.height, cssW: v.width, px: Array.from(px), png: btoa(bin) };
    });
    mkdirSync("test-results/shots", { recursive: true });
    writeFileSync(`test-results/shots/snapshot-${renderer}.png`, Buffer.from(result.png, "base64"));
    expect(result.w).toBeGreaterThanOrEqual(result.cssW * 2);
    // the root span is purple (gateway), not the background
    const [r, g, b] = result.px;
    expect(Math.abs(r - 148) + Math.abs(g - 103) + Math.abs(b - 189)).toBeLessThan(60);
  });
}

const ready = async (page: import("@playwright/test").Page) => {
  await page.goto("/test/visual/harness.html?scene=trace_waterfall&renderer=webgl2");
  await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 15_000 });
};
const menu = (page: import("@playwright/test").Page) => page.locator('.atl-export-menu');
const entry = (page: import("@playwright/test").Page, how: string) => menu(page).locator(`button[data-how="${how}"]`);

test("the Export menu lists what works here and opens with the key e", async ({ page }) => {
  await ready(page);
  await expect(menu(page)).toBeHidden();
  await page.locator(".atl-root").focus();
  await page.keyboard.press("e");
  await expect(menu(page)).toBeVisible();
  // a secure page (localhost) with Python (the harness answers): every entry
  const hows = await menu(page).locator("button").evaluateAll((bs) => bs.map((b) => (b as HTMLElement).dataset.how));
  expect(hows).toEqual(["copy", "copy-svg", "png", "svg", "save-png", "save-svg"]);
  await page.keyboard.press("Escape");
  await expect(menu(page)).toBeHidden();
  await page.locator('.atl-toolbar button[aria-label="Export image"]').click();
  await expect(menu(page)).toBeVisible();
  await page.mouse.click(5, 600); // outside: closes
  await expect(menu(page)).toBeHidden();
});

test("Download PNG and Download SVG save files named after the title", async ({ page }) => {
  await ready(page);
  const exportButton = page.locator('.atl-toolbar button[aria-label="Export image"]');
  await exportButton.click();
  const [png] = await Promise.all([page.waitForEvent("download"), entry(page, "png").click()]);
  expect(png.suggestedFilename()).toBe("one-trace.png");
  await exportButton.click();
  const [svg] = await Promise.all([page.waitForEvent("download"), entry(page, "svg").click()]);
  expect(svg.suggestedFilename()).toBe("one-trace.svg");
  await expect(page.locator(".atl-notice")).toContainText("Downloaded one-trace.svg");
  // Python was asked for the view as shown: its size (with the title), range, lanes, folds, theme
  const asked = await page.evaluate(() => (window as any).__log.filter((m: any) => m.type === "figure"));
  expect(asked).toHaveLength(1);
  const v = await page.locator(".atl-root").evaluate((root: any) => ({ w: root.__view.width, h: root.__view.height, fs: root.__view.fs, lanes: root.__view.spec.lanes.tree.size.length }));
  expect(asked[0].width).toBe(v.w);
  expect(asked[0].height).toBe(v.h + Math.round(v.fs * 2.4));
  expect(asked[0].range).toHaveLength(2);
  expect(asked[0].open).toHaveLength(v.lanes);
  expect(asked[0].theme).toBe("light");
});

test("Save next to the notebook sends the PNG to Python, and says where it went", async ({ page }) => {
  await ready(page);
  await page.locator('.atl-toolbar button[aria-label="Export image"]').click();
  await entry(page, "save-png").click();
  await expect(page.locator(".atl-notice")).toContainText("Saved as /notebooks/one-trace.png");
  const saved = await page.evaluate(() => (window as any).__log.filter((m: any) => m.type === "save-image"));
  expect(saved[0].name).toBe("one-trace.png");
  expect(saved[0].bytes).toBeGreaterThan(1000); // the PNG went with it
  await page.locator('.atl-toolbar button[aria-label="Export image"]').click();
  await entry(page, "save-svg").click();
  await expect(page.locator(".atl-notice")).toContainText("Saved as /notebooks/one-trace.svg");
});

test("Copy image and Copy as vector put pictures on the clipboard", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await ready(page);
  const exportButton = page.locator('.atl-toolbar button[aria-label="Export image"]');
  const types = () => page.evaluate(async () => (await navigator.clipboard.read()).flatMap((item) => [...item.types]));
  await exportButton.click();
  await entry(page, "copy").click();
  await expect(page.locator(".atl-notice")).toContainText("Copied");
  expect(await types()).toEqual(["image/png"]);
  await exportButton.click();
  await entry(page, "copy-svg").click();
  await expect(page.locator(".atl-notice")).toContainText("Copied as SVG");
  expect((await types()).sort()).toEqual(["image/png", "image/svg+xml"]);
});
