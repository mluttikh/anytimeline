// JupyterLab: a notebook with a plot, run in a real JupyterLab with a Python kernel. The plot
// draws data from Python, its tooltips ask Python, a selection reaches Python, and it follows
// JupyterLab's dark theme when the theme is switched.

import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, type Page, test } from "@playwright/test";

const hasPython = spawnSync("uv", ["--version"]).status === 0;
test.describe.configure({ mode: "serial" });
let server: ChildProcess | null = null;
let url = "";

const cells = [
  `from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = service_log(300)
plot = Timeline(title="Lab test", renderer="webgl2", height=340)
plot.events(log, time="time", lane="service", color="level", symbol="event",
            tooltip=["request", "user"])
plot`,
  `print("SELECTED", plot.selection, plot.tool)`,
  `plot.save_png("shot.png")`,
  `import pathlib
print("PNG", pathlib.Path("shot.png").read_bytes()[:8] == b"\\x89PNG\\r\\n\\x1a\\n", pathlib.Path("shot.png").stat().st_size)`,
  `other = Timeline(title="Linked", renderer="webgl2", height=220)
other.events(log, time="time", lane="service", color="level")
other.link(plot)
other`,
];

function notebook(): string {
  return JSON.stringify({
    nbformat: 4,
    nbformat_minor: 5,
    metadata: { kernelspec: { name: "python3", display_name: "Python 3", language: "python" } },
    cells: cells.map((source, i) => ({ cell_type: "code", id: `c${i}`, metadata: {}, execution_count: null, outputs: [], source })),
  });
}

test.beforeAll(async ({}, info) => {
  if (!hasPython) return;
  test.setTimeout(120_000);
  const dir = mkdtempSync(join(tmpdir(), "atl-lab-"));
  writeFileSync(join(dir, "plot.ipynb"), notebook());
  const port = 8950 + info.workerIndex;
  url = `http://127.0.0.1:${port}/`;
  server = spawn(
    "uv",
    [
      "run", "jupyter", "lab", "--no-browser", `--port=${port}`, "--ip=127.0.0.1",
      "--IdentityProvider.token=", "--ServerApp.password=", `--ServerApp.root_dir=${dir}`,
      "--LabApp.news_url=", "--LabApp.check_for_updates_class=jupyterlab.NeverCheckForUpdate",
    ],
    {
      cwd: "..",
      stdio: "ignore",
      // settings (the theme the test switches), workspaces and config of the test's own, never
      // the user's
      env: {
        ...process.env,
        JUPYTERLAB_SETTINGS_DIR: join(dir, ".settings"),
        JUPYTERLAB_WORKSPACES_DIR: join(dir, ".workspaces"),
        JUPYTER_CONFIG_DIR: join(dir, ".config"),
      },
    },
  );
  for (let i = 0; i < 240; i++) {
    try {
      if ((await fetch(`${url}api/status`)).ok) return;
    } catch {
      // not yet
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("JupyterLab did not start");
});

test.afterAll(() => server?.kill());

/** Open the notebook and run all its cells; resolves when the plot has its data. */
async function openNotebook(page: Page): Promise<void> {
  await page.goto(`${url}lab/tree/plot.ipynb`);
  await page.locator(".jp-Notebook").waitFor({ timeout: 60_000 });
  await expect(page.locator(".jp-Notebook-ExecutionIndicator[data-status='idle']")).toHaveCount(1, { timeout: 60_000 });
  // Run All Cells; again if the kernel was not ready yet (a busy machine: the status may say
  // idle before the kernel takes requests)
  for (let attempt = 0; ; attempt++) {
    await page.getByRole("menuitem", { name: "Run", exact: true }).click();
    await page.locator('[data-command="runmenu:run-all"]').click();
    try {
      await expect(page.locator(".atl-info").first()).toContainText("events", { timeout: 25_000 });
      return;
    } catch (err) {
      if (attempt >= 2) throw err;
    }
  }
}

/** Run cell `n` again; resolves with its output's text once it has `expect`. */
async function runCell(page: Page, n: number, expected: string): Promise<string> {
  const cell = page.locator(".jp-Notebook .jp-Cell").nth(n);
  await cell.locator(".jp-InputArea-editor").click();
  const before = await cell.locator(".jp-InputPrompt").innerText();
  await page.keyboard.press("Shift+Enter");
  // ran: a new execution count in its prompt
  await expect(cell.locator(".jp-InputPrompt")).not.toHaveText(before, { timeout: 30_000 });
  await expect(cell.locator(".jp-InputPrompt")).toHaveText(/\[\d+\]/, { timeout: 30_000 });
  if (!expected) return "";
  const out = cell.locator(".jp-OutputArea-output");
  await expect(out).toContainText(expected, { timeout: 30_000 });
  return out.innerText();
}

/** What Python knows of the plot (the second cell's output). */
const python = (page: Page) => runCell(page, 1, "SELECTED");

/** Switch JupyterLab's theme from its Settings menu. */
async function setTheme(page: Page, name: string): Promise<void> {
  await page.getByRole("menuitem", { name: "Settings", exact: true }).click();
  await page.locator(".lm-Menu-item[data-type='submenu']", { hasText: "Theme" }).first().hover();
  await page.locator(".lm-Menu-item[data-command='apputils:change-theme']", { hasText: name }).first().click();
}

test.describe("in JupyterLab", () => {
  test.skip(!hasPython, "needs uv and Python");

  test("the plot draws, asks Python for tooltips, and its selection reaches Python", async ({ page }) => {
    test.setTimeout(120_000);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await openNotebook(page);
    await expect(page.locator(".atl-info").first()).toContainText("webgl2");
    const root = page.locator(".atl-root").first();
    await root.scrollIntoViewIfNeeded();
    const pos = await root.evaluate((r) => {
      const view = (r as any).__view;
      for (let i = 0; i < 300; i++) {
        const p = view.eventPosition(0, i);
        if (p && p.x > 120 && p.x < 600 && p.y > 60) return p;
      }
      return null;
    });
    expect(pos).not.toBeNull();
    const box = (await page.locator(".atl-stage").first().boundingBox())!;
    await page.mouse.move(box.x + pos.x, box.y + pos.y);
    await expect(page.locator(".atl-tooltip")).toContainText("request", { timeout: 15_000 }); // from Python
    await page.locator('.atl-toolbar button[aria-label="Select"]').click();
    await page.mouse.click(box.x + pos.x, box.y + pos.y);
    await expect.poll(() => python(page), { timeout: 30_000 }).toMatch(/SELECTED \{'events': \[\d+\]\} select/);
    expect(errors).toEqual([]);
    await page.screenshot({ path: "test-results/shots/jupyterlab-light.png" });
  });

  test("save_png writes the picture the browser draws", async ({ page }) => {
    test.setTimeout(120_000);
    await openNotebook(page);
    await runCell(page, 2, ""); // save_png: the file arrives after the cell
    await expect.poll(() => runCell(page, 3, "PNG"), { timeout: 30_000 }).toMatch(/PNG True \d{5,}/);
  });

  test("plots in different cells, linked, zoom together", async ({ page }) => {
    test.setTimeout(120_000);
    await openNotebook(page);
    const roots = page.locator(".atl-root");
    await expect(roots).toHaveCount(2, { timeout: 30_000 });
    await expect(roots.nth(1).locator(".atl-info")).toContainText("events", { timeout: 30_000 });
    const range = (i: number) => roots.nth(i).evaluate((r: any) => [r.__view.camera.left, r.__view.camera.right]);
    await roots.first().scrollIntoViewIfNeeded();
    const stage = page.locator(".atl-stage").first();
    const box = (await stage.boundingBox())!;
    await stage.click({ position: { x: box.width * 0.5, y: box.height * 0.5 } });
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(200);
    const [a0, a1] = await range(0);
    const [b0, b1] = await range(1);
    expect(Math.abs(a0 - b0)).toBeLessThan((a1 - a0) / 2000); // well under a pixel
    expect(Math.abs(a1 - b1)).toBeLessThan((a1 - a0) / 2000);
  });

  test("it follows JupyterLab's dark theme", async ({ page }) => {
    test.setTimeout(120_000);
    await openNotebook(page);
    const root = page.locator(".atl-root").first();
    const bg = () => root.evaluate((r) => (r as any).__view.theme.bg);
    expect(await bg()).toBe("#ffffff");
    await setTheme(page, "JupyterLab Dark");
    await expect(page.locator("body")).toHaveAttribute("data-jp-theme-light", "false", { timeout: 15_000 });
    await expect.poll(bg, { timeout: 10_000 }).toBe("#12171d");
    // buttons follow too: an unpressed one on the plot's dark background, a pressed one inverted
    const buttons = await root.evaluate((r) => {
      const style = (label: string) => getComputedStyle(r.querySelector(`.atl-toolbar button[aria-label="${label}"]`)!).backgroundColor;
      return { zoom: style("Zoom"), pan: style("Pan") };
    });
    expect(buttons.zoom).toBe("rgb(18, 23, 29)");
    expect(buttons.pan).toBe("rgb(229, 233, 237)");
    await expect(page.locator("#jupyterlab-splash")).toHaveCount(0, { timeout: 15_000 });
    await root.scrollIntoViewIfNeeded();
    await page.screenshot({ path: "test-results/shots/jupyterlab-dark.png" });
    // back to light, for the next run
    await setTheme(page, "JupyterLab Light");
    await expect.poll(bg, { timeout: 10_000 }).toBe("#ffffff");
  });
});
