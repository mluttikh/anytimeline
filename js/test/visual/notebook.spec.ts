// The notebook connection (widget.ts): a plot in a marimo app run headless, its kernel running
// the real Python package. The data comes from Python; what the plot changes reaches Python.
// The app (apps/connection.py) shows what Python knows of the plot in #python-state.

import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";

const hasPython = spawnSync("uv", ["--version"]).status === 0;
// a marimo app with a kernel: one retry on a busy CI machine
test.describe.configure({ mode: "default", retries: process.env.CI ? 1 : 0 });
let server: ChildProcess | null = null;
let url = "";

test.beforeAll(async ({}, info) => {
  if (!hasPython) return;
  const port = 2950 + info.workerIndex;
  url = `http://127.0.0.1:${port}/`;
  server = spawn("uv", ["run", "marimo", "run", "js/test/visual/apps/connection.py", "--headless", "--port", String(port), "--no-token"], { cwd: "..", stdio: "ignore" });
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
  await page.locator(".atl-root").waitFor({ timeout: 60_000 });
  await expect(page.locator(".atl-info")).toContainText("events", { timeout: 30_000 });
  return async () => JSON.parse(await page.locator("#python-state").innerText());
}

test.describe("in marimo", () => {
  test.skip(!hasPython, "needs uv and Python");

  test("the plot draws data from Python, and clicks and the scale switch reach Python", async ({ page }) => {
    const python = await open(page);
    await expect.poll(async () => (await python()).xscale).toBe("time");
    // a click on an event selects its row in Python
    const pos = await page.locator(".atl-root").evaluate((root) => {
      const view = (root as any).__view;
      for (let i = 0; i < 300; i++) {
        const p = view.eventPosition(0, i);
        if (p && p.x > 120 && p.x < 700) return p;
      }
      return null;
    });
    expect(pos).not.toBeNull();
    const box = (await page.locator(".atl-stage").boundingBox())!;
    await page.mouse.move(box.x + pos.x, box.y + pos.y);
    await expect(page.locator(".atl-tooltip")).toContainText("request", { timeout: 10_000 }); // from Python
    await page.mouse.click(box.x + pos.x, box.y + pos.y); // Pan: a plain click selects nothing
    await page.locator('.atl-toolbar button[aria-label="Select"]').click();
    await expect.poll(async () => (await python()).tool).toBe("select");
    await page.mouse.click(box.x + pos.x, box.y + pos.y);
    await expect.poll(async () => (await python()).selected.events).toBe(1);
    await page.locator('.atl-toolbar button[aria-label="Order"]').click();
    await expect.poll(async () => (await python()).xscale).toBe("order");
  });

  test("a cell of anytimeline.marimo.selection runs again on a selection, and on nothing else", async ({ page }) => {
    const python = await open(page);
    const runs = async () => JSON.parse(await page.locator("#selection-runs").innerText());
    await expect.poll(async () => (await runs()).runs).toEqual([0]);
    // a tool and the scale switch change synced settings, not the selection
    await page.locator('.atl-toolbar button[aria-label="Select"]').click();
    await expect.poll(async () => (await python()).tool).toBe("select");
    await page.locator('.atl-toolbar button[aria-label="Order"]').click();
    await expect.poll(async () => (await python()).xscale).toBe("order");
    expect((await runs()).runs).toEqual([0]);
    const pos = await page.locator(".atl-root").evaluate((root) => {
      const view = (root as any).__view;
      for (let i = 0; i < 300; i++) {
        const p = view.eventPosition(0, i);
        if (p && p.x > 120 && p.x < 700) return p;
      }
      return null;
    });
    const box = (await page.locator(".atl-stage").boundingBox())!;
    await page.mouse.click(box.x + pos.x, box.y + pos.y);
    await expect.poll(async () => (await runs()).runs).toEqual([0, 1]);
    expect((await runs()).requests).toHaveLength(1);
  });
});
