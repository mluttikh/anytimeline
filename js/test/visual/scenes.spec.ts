import { expect, test, type Page } from "@playwright/test";

// Every scene with every backend: it draws (no errors, not blank), with the backend asked
// for, and looks as stored. Scenes: `uv run python scripts/make_scenes.py`.

const SCENES = ["service_time", "service_routes", "service_sequence", "order_overview", "gantt_plan", "schedule", "spans_events", "trace_waterfall", "trace_list", "service_health", "latency_series", "host_groups", "trace_groups", "trace_compare", "story_incident", "story_teams", "dense", "centuries", "nanoseconds", "order_only"];
const RENDERERS = ["webgpu", "webgl2", "canvas2d"] as const;

async function open(page: Page, scene: string, renderer: string): Promise<string[]> {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.goto(`/test/visual/harness.html?scene=${scene}&renderer=${renderer}`);
  await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 15_000 });
  await page.waitForTimeout(600);
  return errors;
}

for (const renderer of RENDERERS) {
  for (const scene of SCENES) {
    test(`${scene} with ${renderer}`, async ({ page }) => {
      const errors = await open(page, scene, renderer);
      const perf = await page.evaluate(() => (window as any).__perf);
      if (renderer === "webgpu" && perf.renderer !== "webgpu") test.skip(true, "no WebGPU here");
      expect(perf.renderer).toBe(renderer);
      expect(errors).toEqual([]);
      const plot = page.locator("#plot");
      await plot.screenshot({ path: `test-results/shots/${scene}-${renderer}.png` });
      await expect(plot).toHaveScreenshot(`${scene}-${renderer}.png`, { maxDiffPixelRatio: 0.01 });
    });
  }
}
