import { expect, test } from "@playwright/test";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// The built documentation (uv run python scripts/build_docs.py): its live plots draw.
const site = resolve(dirname(fileURLToPath(import.meta.url)), "../../../site");
const pages = ["index.html", "tutorials/first-chart.html", "tutorials/order.html", "how-to/time.html", "how-to/large.html", "how-to/gantt.html", "how-to/intervals.html", "how-to/traces.html", "how-to/states-values.html", "how-to/groups.html", "how-to/story.html"];

for (const page of pages) {
  test(`docs: ${page}`, async ({ page: p }) => {
    test.skip(!existsSync(`${site}/index.html`), "build the docs first");
    const errors: string[] = [];
    p.on("pageerror", (e) => errors.push(String(e)));
    await p.setViewportSize({ width: 1280, height: 900 });
    await p.goto(pathToFileURL(`${site}/${page}`).href);
    const plots = p.locator(".anytimeline-embed");
    const n = await plots.count();
    expect(n).toBeGreaterThan(0);
    for (let i = 0; i < n; i++) {
      await plots.nth(i).scrollIntoViewIfNeeded();
      await expect(plots.nth(i)).toHaveAttribute("data-state", "ready", { timeout: 15_000 });
    }
    expect(errors).toEqual([]);
    await p.waitForTimeout(300);
    await p.screenshot({ path: `test-results/docs/${page.replace(/\//g, "_")}.png`, fullPage: true });
  });
}

test("docs: plots follow the dark theme", async ({ page: p }) => {
  test.skip(!existsSync(`${site}/index.html`), "build the docs first");
  await p.setViewportSize({ width: 1280, height: 900 });
  await p.goto(pathToFileURL(`${site}/index.html`).href);
  await expect(p.locator(".anytimeline-embed").first()).toHaveAttribute("data-state", "ready", { timeout: 15_000 });
  await p.evaluate(() => document.body.setAttribute("data-md-color-scheme", "slate"));
  await p.waitForTimeout(300);
  const bg = await p.locator(".atl-root").first().evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).toBe("rgb(18, 23, 29)");
  await p.screenshot({ path: "test-results/docs/index-dark.png" });
});
