import { expect, test } from "@playwright/test";

// Not part of the regular run: PERF=1 npx playwright test perf (needs scenes/million.json,
// written by hand, see the README).
test.skip(!process.env.PERF, "set PERF=1");

for (const renderer of ["webgpu", "webgl2", "canvas2d"]) {
  test(`one million events with ${renderer}`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto(`/test/visual/harness.html?scene=million&renderer=${renderer}`);
    await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 60_000 });
    const perf = await page.evaluate(() => (window as any).__perf);
    if (perf.renderer !== renderer) test.skip(true, `no ${renderer}`);
    const whole = await page.locator(".atl-root").evaluate((root: any) => root.__view.benchmark(40));
    // zoomed in to a minute: the case where marks are readable
    await page.locator(".atl-root").evaluate((root: any) => root.__view.zoomTo([0, 60e9]));
    const zoomed = await page.locator(".atl-root").evaluate((root: any) => root.__view.benchmark(40));
    console.log(renderer, "load", perf.load_ms, "ms; whole day", whole, "; one minute", zoomed);
    expect(whole.median_ms).toBeGreaterThan(0);
  });
}
