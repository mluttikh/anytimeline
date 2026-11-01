import { expect, test } from "@playwright/test";

// The toolbar's tips (tips.ts): shown 0.15 s after the pointer comes to a button, also a
// greyed one (which says why), and when a button gets the keyboard's focus.
test("a button's tip shows at once, also on a greyed button and on keyboard focus", async ({ page }) => {
  await page.goto("/test/visual/harness.html?scene=trace_waterfall&renderer=canvas2d");
  await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 15_000 });
  const tip = page.locator(".atl-button-tip");
  await expect(tip).toBeHidden();
  // no title: the browser's own tooltip would show a second one, a second later
  expect(await page.locator(".atl-toolbar button[title]").count()).toBe(0);
  // a greyed button: Back, before any zoom
  const back = page.locator('.atl-toolbar button[aria-label="Previous view"]');
  await expect(back).toBeDisabled();
  const box = (await back.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await expect(tip).toBeVisible({ timeout: 600 });
  await expect(tip).toContainText("none yet");
  // under its button
  const t = (await tip.boundingBox())!;
  expect(t.y).toBeGreaterThan(box.y + box.height);
  // to the next button: its tip at once
  const legend = page.locator('.atl-toolbar button[aria-label="Legend"]');
  const lb = (await legend.boundingBox())!;
  await page.mouse.move(lb.x + lb.width / 2, lb.y + lb.height / 2);
  await expect(tip).toContainText("legend");
  await expect(legend).toHaveAttribute("aria-describedby", /atl-tip-/);
  // away: gone
  await page.mouse.move(5, 600);
  await expect(tip).toBeHidden();
  // keyboard focus shows it (WebKit on macOS does not tab to buttons: a key, then focus)
  await page.locator(".atl-root").focus();
  await page.keyboard.press("Shift");
  await legend.focus();
  await expect(tip).toBeVisible();
  await expect(tip).toContainText("legend");
});
