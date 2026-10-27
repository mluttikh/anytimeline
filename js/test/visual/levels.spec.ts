// Levels of detail (levels.ts): layers of many events, samples and bars, sent as levels, in a
// marimo app run headless (apps/levels.py). Zoomed out the plot draws bins; zoomed in, the
// marks there come in windows from Python. #python-state shows what Python knows.

import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";

const hasPython = spawnSync("uv", ["--version"]).status === 0;
test.describe.configure({ mode: "default", retries: process.env.CI ? 1 : 0 });
let server: ChildProcess | null = null;
let url = "";

test.beforeAll(async ({}, info) => {
  if (!hasPython) return;
  const port = 2970 + info.workerIndex;
  url = `http://127.0.0.1:${port}/`;
  server = spawn("uv", ["run", "marimo", "run", "js/test/visual/apps/levels.py", "--headless", "--port", String(port), "--no-token"], { cwd: "..", stdio: "ignore" });
  for (let i = 0; i < 160; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not yet
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("marimo did not start");
});

test.afterAll(() => server?.kill());

async function open(page: Page) {
  await page.goto(url);
  await page.locator(".atl-root").waitFor({ timeout: 90_000 });
  await expect(page.locator(".atl-info")).toContainText("500 000 events", { timeout: 60_000 });
  return async () => JSON.parse(await page.locator("#python-state").innerText());
}

/** What the view draws of each layer: bins (a level's k) or its marks (a window's count). */
function drawn(page: Page) {
  return page.locator(".atl-root").evaluate((root) => {
    const v = (root as any).__view;
    const events = v.layers[0];
    return {
      bins: events.detail.shown ? events.detail.shown.data.k : null,
      events: events.data.count,
      samples: { count: v.values[0].data.count, k: v.values[0].data.spec.k ?? null, level: v.values[0].data.spec.bin_width !== undefined },
      bars: { count: v.bars[0].data.count, k: v.bars[0].data.spec.k ?? null, level: v.bars[0].data.spec.bin_width !== undefined },
    };
  });
}

/** Show a part (fractions f0..f1) of the time extent, with lane `top` at the top. */
function show(page: Page, f0: number, f1: number, top: string | null = null) {
  return page.locator(".atl-root").evaluate(
    (root, [f0, f1, top]) => {
      const v = (root as any).__view;
      const [t0, t1] = v.spec.time.extent;
      v.setView([t0 + (t1 - t0) * (f0 as number), t0 + (t1 - t0) * (f1 as number)], top);
    },
    [f0, f1, top] as const,
  );
}

test.describe("in marimo", () => {
  test.skip(!hasPython, "needs uv and Python");

  test("zoomed out it draws levels; zoomed in, the marks there come from Python", async ({ page }) => {
    const files: string[] = [];
    page.on("response", (r) => {
      if (r.url().includes("@file/") && r.url().endsWith(".bin")) files.push(r.url());
    });
    await open(page);
    await expect(page.locator(".atl-info")).toContainText("400 000 jobs");
    await expect(page.locator(".atl-info")).toContainText("1 800 000 samples");
    await expect.poll(async () => (await drawn(page)).bins).not.toBeNull();
    const start = await drawn(page);
    expect(start.events).toBe(0);
    expect(start.samples.level).toBe(true);
    expect(start.bars.level).toBe(true);
    // a few seconds: every event, sample and bar there
    await show(page, 0.42, 0.4205, "lane 00");
    await expect.poll(async () => (await drawn(page)).bins, { timeout: 20_000 }).toBeNull();
    await expect.poll(async () => (await drawn(page)).events).toBeGreaterThan(0);
    await expect.poll(async () => (await drawn(page)).samples.level).toBe(false);
    await show(page, 0.42, 0.4205, "worker 0");
    await expect.poll(async () => (await drawn(page)).bars.level, { timeout: 20_000 }).toBe(false);
    expect((await drawn(page)).bars.k).toBeNull();
    // in marimo, large buffers come as files
    expect(files.length).toBeGreaterThan(0);
  });

  test("a bin's tooltip counts its events by colour, from Python", async ({ page }) => {
    await open(page);
    await expect.poll(async () => (await drawn(page)).bins).not.toBeNull();
    const pos = await page.locator(".atl-root").evaluate((root) => {
      const v = (root as any).__view;
      const bins = v.layers[0].detail.shown;
      const stage = root.querySelector(".atl-stage")!.getBoundingClientRect();
      const bv = { left: v.camera.left, scale: v.camera.scale, plot: v.plot(), laneTop: v.plot().y - v.scrollY, laneH: v.laneH, maxBar: 24, sequence: false, slot: v.slot };
      for (let i = 0; i < bins.data.count; i++) {
        if (bins.data.n[i] < 20) continue;
        const b = bins.box(i, bv);
        const x = (b.x0 + b.x1) / 2;
        if (x > bv.plot.x + 40 && x < bv.plot.x + bv.plot.w - 40 && b.cy > bv.plot.y + 10 && b.cy < bv.plot.y + bv.plot.h - 10) return { x: stage.x + x, y: stage.y + b.cy };
      }
      return null;
    });
    expect(pos).not.toBeNull();
    await page.mouse.move(pos!.x, pos!.y);
    await expect(page.locator(".atl-tooltip")).toContainText("events");
    await expect(page.locator(".atl-tooltip")).toContainText("info", { timeout: 10_000 }); // from Python
  });

  test("the Order scale has levels too, and a box in bins selects in Python and shows over them", async ({ page }) => {
    const python = await open(page);
    await page.locator(".atl-root").evaluate((root) => (root as any).__view.setXScale("order"));
    await expect.poll(async () => (await drawn(page)).bins).not.toBeNull();
    await show(page, 0.0, 1.0);
    // a box over part of a lane, as the Select tool sends it
    await page.locator(".atl-root").evaluate((root) => {
      const v = (root as any).__view;
      const lane = v.spec.lanes.names.indexOf("lane 12");
      const a = v.camera.left + (v.camera.right - v.camera.left) * 0.5;
      const b = v.camera.left + (v.camera.right - v.camera.left) * 0.52;
      v.callbacks.onGesture({ kind: "box", x: [a, b], lanes: [lane, lane], shown: [lane], xscale: "order", mode: "replace", layer: "events" });
    });
    await expect.poll(async () => (await python()).selected.events ?? 0).toBeGreaterThan(0);
    const marked = await page.locator(".atl-root").evaluate((root) => (root as any).__view.marked.events?.length ?? 0);
    expect(marked / 3).toBe((await python()).selected.events);
    // zoomed in on the Order scale: the events there
    await show(page, 0.5, 0.5005);
    await expect.poll(async () => (await drawn(page)).bins, { timeout: 20_000 }).toBeNull();
    expect((await drawn(page)).events).toBeGreaterThan(0);
  });
});
