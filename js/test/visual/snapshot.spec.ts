import { expect, test } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";

// Save as PNG: the picture has the title, the bars (also from the GPU canvas) and the legend.
for (const renderer of ["webgpu", "webgl2", "canvas2d"] as const) {
  test(`a PNG of the plot with ${renderer}`, async ({ page }) => {
    await page.goto(`/test/visual/harness.html?scene=trace_waterfall&renderer=${renderer}`);
    await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 15_000 });
    const perf = await page.evaluate(() => (window as any).__perf);
    if (renderer === "webgpu" && perf.renderer !== "webgpu") test.skip(true, "no WebGPU here");
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

test("the toolbar's button downloads a PNG named after the title", async ({ page }) => {
  await page.goto("/test/visual/harness.html?scene=trace_waterfall&renderer=webgl2");
  await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 15_000 });
  const [file] = await Promise.all([page.waitForEvent("download"), page.locator('.atl-toolbar button[aria-label="Save as PNG"]').click()]);
  expect(file.suggestedFilename()).toBe("one-trace.png");
});
