import { expect, test, type Page } from "@playwright/test";

// Tools, gestures, keys and full screen: what reaches the model (the harness logs what the
// plot sets and sends) and what the view shows.

async function open(page: Page, scene: string): Promise<void> {
  await page.goto(`/test/visual/harness.html?scene=${scene}&renderer=webgl2`);
  await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 15_000 });
}

const view = (page: Page) => page.locator(".atl-root");

async function stageBox(page: Page) {
  return (await page.locator(".atl-stage").boundingBox())!;
}

async function eventAt(page: Page, layer: number, index: number): Promise<{ x: number; y: number }> {
  const p = await view(page).evaluate((root: any, [l, i]) => root.__view.eventPosition(l, i), [layer, index]);
  const box = await stageBox(page);
  return { x: box.x + p.x, y: box.y + p.y };
}

const picks = (page: Page) => page.evaluate(() => (window as any).__log.filter((m: any) => m.set === "_pick").map((m: any) => m.value));
const views = (page: Page) => page.evaluate(() => (window as any).__log.filter((m: any) => m.type === "view").map((m: any) => m.range));
const state = (page: Page, key: string) => page.evaluate((k) => (window as any).__model.state[k], key);

test("Pan: a plain click selects nothing; a Shift-click adds the event", async ({ page }) => {
  await open(page, "order_only");
  const p = await eventAt(page, 0, 2);
  await page.mouse.move(p.x, p.y);
  await expect(page.locator(".atl-tooltip.atl-show")).toContainText("order");
  await page.mouse.click(p.x, p.y);
  expect(await picks(page)).toEqual([]);
  await page.keyboard.down("Shift");
  await page.mouse.click(p.x, p.y);
  await page.keyboard.up("Shift");
  expect(await picks(page)).toEqual([expect.objectContaining({ kind: "click", index: 2, mode: "toggle" })]);
});

test("Select: a click selects an event, a drag selects a box", async ({ page }) => {
  await open(page, "order_only");
  await page.locator('.atl-toolbar button[aria-label="Select"]').click();
  expect(await state(page, "tool")).toBe("select");
  await expect(page.locator(".atl-hint")).toContainText("select a box");
  const p = await eventAt(page, 0, 3);
  await page.mouse.click(p.x, p.y);
  const a = await eventAt(page, 0, 0);
  const b = await eventAt(page, 0, 5);
  await page.mouse.move(a.x - 10, a.y - 10);
  await page.mouse.down();
  await page.mouse.move(b.x + 10, b.y + 10, { steps: 4 });
  await page.mouse.up();
  const sent = await picks(page);
  expect(sent[0]).toMatchObject({ kind: "click", index: 3, mode: "replace" });
  expect(sent[1]).toMatchObject({ kind: "box", lanes: [0, 2], mode: "replace", xscale: "order" });
});

test("Zoom: a drag zooms to that time range, Back returns, the key z switches", async ({ page }) => {
  await open(page, "service_time");
  await view(page).click({ position: { x: 4, y: 4 } });
  await page.keyboard.press("z");
  expect(await state(page, "tool")).toBe("zoom");
  const box = await stageBox(page);
  const y = box.y + box.height / 2;
  await page.mouse.move(box.x + 300, y);
  await page.mouse.down();
  await page.mouse.move(box.x + 400, y, { steps: 4 });
  await page.mouse.up();
  await page.waitForTimeout(350);
  const [a, b] = (await views(page)).at(-1);
  const whole = 3_598_661_460; // the scene's extent in µs ticks
  expect(b - a).toBeLessThan(whole / 4);
  expect(b - a).toBeGreaterThan(whole / 20);
  await expect(page.locator('.atl-toolbar button[aria-label="Previous view"]')).toBeEnabled();
  await page.keyboard.press("Backspace");
  await page.waitForTimeout(350);
  const [c, d] = (await views(page)).at(-1);
  expect(d - c).toBeGreaterThan(whole);
  await expect(page.locator('.atl-toolbar button[aria-label="Whole timeline"]')).toBeDisabled();
});

test("Pan: a drag on the time axis or a Shift-drag zooms to a range", async ({ page }) => {
  await open(page, "service_time");
  const box = await stageBox(page);
  await page.mouse.move(box.x + 300, box.y + 20); // the axis
  await page.mouse.down();
  await page.mouse.move(box.x + 500, box.y + 20, { steps: 4 });
  await page.mouse.up();
  await page.waitForTimeout(350);
  const [a, b] = (await views(page)).at(-1);
  expect(b - a).toBeLessThan(3_598_661_460 / 2);
  await page.keyboard.down("Shift");
  await page.mouse.move(box.x + 300, box.y + 200);
  await page.mouse.down();
  await page.mouse.move(box.x + 340, box.y + 200, { steps: 4 });
  await page.mouse.up();
  await page.keyboard.up("Shift");
  await page.waitForTimeout(350);
  const [c, d] = (await views(page)).at(-1);
  expect(d - c).toBeLessThan((b - a) / 4);
  expect(await picks(page)).toEqual([]);
});

test("Clear, Esc, the legend switch and help", async ({ page }) => {
  await open(page, "service_routes"); // has a selection
  const clear = page.locator('.atl-toolbar button[aria-label="Clear the selection"]');
  await expect(clear).toBeVisible();
  await clear.click();
  expect((await picks(page)).at(-1)).toEqual(expect.objectContaining({ kind: "clear" }));
  await view(page).click({ position: { x: 4, y: 4 } });
  await page.keyboard.press("Escape");
  expect((await picks(page)).filter((p: any) => p.kind === "clear").length).toBe(2);
  await page.locator('.atl-toolbar button[aria-label="Legend"]').click();
  expect(await state(page, "legend")).toBe(false);
  await expect(page.locator(".atl-legend")).toBeHidden();
  await page.keyboard.press("?");
  await expect(page.locator(".atl-help")).toContainText("Mouse and keys");
  await page.keyboard.press("Escape");
  await expect(page.locator(".atl-help")).toHaveCount(0);
});

test("a tool set from Python shows in the toolbar", async ({ page }) => {
  await open(page, "service_time");
  await page.evaluate(() => {
    (window as any).__model.state.tool = "zoom";
    (window as any).__model.emit("change:tool");
  });
  await expect(page.locator('.atl-toolbar button[aria-label="Zoom"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".atl-stage")).toHaveAttribute("data-tool", "zoom");
});

test("full screen: the plot fills the screen, lanes fill its height, the time range stays", async ({ page }) => {
  await open(page, "service_time");
  await page.waitForTimeout(300);
  const before = await view(page).evaluate((root: any) => ({ span: root.__view.camera.span, laneH: root.__view.laneH }));
  await page.locator('.atl-toolbar button[aria-label="Full screen"]').click();
  await expect.poll(() => view(page).evaluate((root) => root.matches(":fullscreen"))).toBe(true);
  await page.waitForTimeout(300);
  const viewport = page.viewportSize()!;
  const stage = await stageBox(page);
  expect(stage.height).toBeGreaterThan(viewport.height - 80);
  const inside = await view(page).evaluate((root: any) => {
    const v = root.__view;
    return { laneH: v.laneH, lanes: v.spec.lanes.names.length, plotH: v.plot().h, span: v.camera.span, left: v.camera.left };
  });
  expect(inside.laneH * inside.lanes).toBeCloseTo(inside.plotH, 0); // lanes fill the height
  expect(inside.laneH).toBeGreaterThan(before.laneH * 2);
  expect(inside.span).toBeCloseTo(before.span, -2); // the same time range
  await page.locator(".atl-root").screenshot({ path: "test-results/shots/service_time-fullscreen.png" });
  await page.locator('.atl-toolbar button[aria-label="Leave full screen"]').click();
  await expect.poll(() => view(page).evaluate((root) => root.matches(":fullscreen"))).toBe(false);
  await page.waitForTimeout(300);
  const after = await view(page).evaluate((root: any) => root.__view.laneH);
  expect(after).toBeCloseTo(before.laneH, 3); // back as it was
});

test("Time and Order are icons; the text size changes all text and reaches Python", async ({ page }) => {
  await open(page, "service_time");
  await page.locator('.atl-toolbar button[aria-label="Order"]').click();
  expect(await state(page, "xscale")).toBe("order");
  await expect(page.locator('.atl-toolbar button[aria-label="Order"]')).toHaveAttribute("aria-pressed", "true");
  const axis = () => view(page).evaluate((root: any) => root.__view.axisH);
  expect(await axis()).toBe(44);
  await page.locator('.atl-toolbar button[aria-label="Display"]').click();
  const larger = page.locator('.atl-popover button[aria-label="Larger text"]');
  for (let i = 0; i < 4; i++) await larger.click();
  await expect(page.locator(".atl-popover .atl-size").first()).toHaveText("16 px");
  expect(await state(page, "font_size")).toBe(16);
  expect(await axis()).toBe(59);
  const titleSize = await page.locator(".atl-title").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(titleSize).toBeCloseTo(16 * 1.08, 1);
  await page.locator('.atl-popover button[aria-label="Default text size"]').click();
  expect(await state(page, "font_size")).toBe(12);
  await page.mouse.click(5, 300); // outside: the popover closes
  await expect(page.locator(".atl-popover")).toBeHidden();
});

test("larger text: screenshot", async ({ page }) => {
  await page.goto("/test/visual/harness.html?scene=service_time&renderer=webgl2&font_size=16");
  await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 15_000 });
  await page.waitForTimeout(400);
  await expect(page.locator("#plot")).toHaveScreenshot("service_time-font16-webgl2.png", { maxDiffPixelRatio: 0.01 });
});

async function barAt(page: Page, layer: number, index: number): Promise<{ x: number; y: number }> {
  const p = await view(page).evaluate((root: any, [l, i]) => root.__view.barPosition(l, i), [layer, index]);
  const box = await stageBox(page);
  return { x: box.x + p.x, y: box.y + p.y };
}

test("Gantt: hovering a task shows its dates, a Select click selects it, Order keeps the bars", async ({ page }) => {
  await open(page, "gantt_plan");
  const p = await barAt(page, 0, 4); // Build backend
  await page.mouse.move(p.x, p.y);
  const tip = page.locator(".atl-tooltip.atl-show");
  await expect(tip).toContainText("Build backend");
  await expect(tip).toContainText("duration");
  await expect(tip).toContainText("18 d");
  await expect(tip).toContainText("60%");
  const m = await barAt(page, 0, 3); // Review: a milestone
  await page.mouse.move(m.x, m.y);
  await expect(tip).toContainText("milestone");
  await page.keyboard.press("s").catch(() => {});
  await page.locator('.atl-toolbar button[aria-label="Select"]').click();
  await page.mouse.click(p.x, p.y);
  expect((await picks(page)).at(-1)).toMatchObject({ kind: "click", layer: "tasks", index: 4, mode: "replace" });
  await page.locator('.atl-toolbar button[aria-label="Order"]').click();
  const q = await barAt(page, 0, 4);
  expect(q.x).toBeGreaterThan(0);
  await page.mouse.move(q.x, q.y);
  await expect(tip).toContainText("Build backend");
  await page.locator("#plot").screenshot({ path: "test-results/shots/gantt_plan-order.png" });
});

test("packed bars: each job is found where it is drawn", async ({ page }) => {
  await open(page, "schedule");
  for (const i of [0, 40, 80, 120]) {
    const p = await barAt(page, 0, i);
    const hit = await view(page).evaluate((root: any, [x, y]) => {
      const v = root.__view;
      const r = root.querySelector(".atl-stage").getBoundingClientRect();
      return v.pick(x - r.left, y - r.top);
    }, [p.x, p.y]);
    expect(hit).toEqual({ layer: 0, index: i, bar: true });
  }
});

/** The middle of the name of the lane on row `row` (page px). */
async function laneName(page: Page, row: number): Promise<{ x: number; y: number }> {
  const p = await view(page).evaluate((root: any, r) => {
    const v = root.__view;
    const plot = v.plot();
    return { x: plot.x / 2, y: plot.y - v.scrollY + (r + 0.5) * v.laneH };
  }, row);
  const box = await stageBox(page);
  return { x: box.x + p.x, y: box.y + p.y };
}

const rows = (page: Page) => view(page).evaluate((root: any) => Array.from(root.__view.laneAt as Int32Array));

test("Spans: a click on a name folds and unfolds; keys fold all; a double-click zooms to it", async ({ page }) => {
  await open(page, "trace_list");
  const tree = await view(page).evaluate((root: any) => root.__view.spec.lanes.tree);
  const roots = tree.depth.map((d: number, i: number) => (d === 0 ? i : -1)).filter((i: number) => i >= 0);
  expect(await rows(page)).toEqual(roots); // expand=1: the roots only
  const first = await laneName(page, 0);
  await page.mouse.click(first.x, first.y);
  const open1 = await rows(page);
  // the first trace's own spans show under it (they stay folded themselves)
  const under = open1.slice(1, open1.indexOf(roots[1]));
  expect(under.length).toBeGreaterThan(0);
  expect(under.every((l: number) => tree.depth[l] === 1)).toBe(true);
  expect(open1.length).toBe(roots.length + under.length);
  await page.waitForTimeout(400);
  await page.mouse.click(first.x, first.y); // fold it again
  expect(await rows(page)).toEqual(roots);
  await page.keyboard.press("]");
  expect((await rows(page)).length).toBe(tree.depth.length);
  await page.keyboard.press("[");
  expect(await rows(page)).toEqual(roots);

  // a double-click on the third trace: its time range, its spans unchanged (folded)
  const third = await laneName(page, 2);
  await page.mouse.dblclick(third.x, third.y);
  expect(await rows(page)).toEqual(roots);
  const [a, b] = await view(page).evaluate((root: any) => [root.__view.camera.left, root.__view.camera.right]);
  const span = await view(page).evaluate((root: any, lane) => {
    const bars = root.__view.bars[0].data;
    const size = root.__view.spec.lanes.tree.size[lane];
    let lo = Infinity;
    let hi = -Infinity;
    for (let i = 0; i < bars.count; i++) {
      if (bars.lane[i] >= lane && bars.lane[i] < lane + size) {
        lo = Math.min(lo, bars.start[i]);
        hi = Math.max(hi, bars.end[i]);
      }
    }
    return [lo, hi];
  }, roots[2]);
  expect(a).toBeLessThanOrEqual(span[0]);
  expect(b).toBeGreaterThanOrEqual(span[1]);
  expect(b - a).toBeLessThan((span[1] - span[0]) * 1.2);
});

test("plot.view: the lane set in Python comes to the top, unfolded, and its view comes back", async ({ page }) => {
  // short, so the lanes do not all fit
  await page.goto("/test/visual/harness.html?scene=trace_list&renderer=webgl2&height=220");
  await page.waitForFunction(() => (window as any).__perf?.frame_ms !== undefined, null, { timeout: 15_000 });
  const tree = await view(page).evaluate((root: any) => root.__view.spec.lanes.tree);
  const names: string[] = await view(page).evaluate((root: any) => root.__view.spec.lanes.names.map(String));
  // a span of the third trace, folded away (expand=1) under its parents, with a name of its own
  const roots = tree.depth.map((d: number, i: number) => (d === 0 ? i : -1)).filter((i: number) => i >= 0);
  const lane = names.findIndex((n, i) => i > roots[2] && i < roots[2] + tree.size[roots[2]] && tree.depth[i] >= 1 && names.indexOf(n) === i);
  expect(lane).toBeGreaterThan(0);
  expect(await rows(page)).not.toContain(lane);
  const set = (zoom: unknown) =>
    page.evaluate((z) => {
      const m = (window as any).__model;
      m.state._zoom = z;
      m.emit("change:_zoom");
    }, zoom);
  await set({ n: 1, range: null, lanes: names[lane] });
  const shown = await rows(page);
  expect(shown).toContain(lane);
  expect(shown.indexOf(roots[2])).toBeLessThan(shown.indexOf(lane)); // its parents unfolded
  await expect.poll(async () => (await page.evaluate(() => (window as any).__log.filter((m: any) => m.type === "view").at(-1)?.lanes))?.[0]).toBe(names[lane]);
  // null: from the top again, the lanes as they are
  await set({ n: 2, range: null, lanes: null });
  await expect.poll(async () => (await page.evaluate(() => (window as any).__log.filter((m: any) => m.type === "view").at(-1)?.lanes))?.[0]).toBe(names[roots[0]]);
  expect(await rows(page)).toEqual(shown);
});

test("Spans: a box over folded lanes selects only the lanes that show", async ({ page }) => {
  await open(page, "trace_list");
  await page.locator('.atl-toolbar button[aria-label="Select"]').click();
  const box = await stageBox(page);
  const top = await laneName(page, 0);
  const bottom = await laneName(page, 2);
  await page.mouse.move(box.x + box.width * 0.3, top.y - 5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5, bottom.y + 5, { steps: 5 });
  await page.mouse.up();
  const roots = await rows(page);
  expect((await picks(page)).at(-1)).toMatchObject({ kind: "box", shown: roots.slice(0, 3) });
});

test("Spans: the bar under the pointer of a deeper lane, after unfolding", async ({ page }) => {
  await open(page, "trace_waterfall");
  const n = await view(page).evaluate((root: any) => root.__view.bars[0].data.count);
  for (const i of [0, Math.floor(n / 2), n - 1]) {
    const p = await barAt(page, 0, i);
    const hit = await view(page).evaluate((root: any, [x, y]) => {
      const v = root.__view;
      const r = root.querySelector(".atl-stage").getBoundingClientRect();
      return v.pick(x - r.left, y - r.top);
    }, [p.x, p.y]);
    expect(hit).toEqual({ layer: 0, index: i, bar: true });
  }
  const p = await barAt(page, 0, 0);
  await page.mouse.move(p.x, p.y);
  await expect(page.locator(".atl-tooltip.atl-show")).toContainText("GET /orders");
});

test("States and values: a sample's value and a state's reason on hover; Order keeps the lines", async ({ page }) => {
  await open(page, "service_health");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  // the CPU sample in the middle of the gateway lane's view
  const p = await view(page).evaluate((root: any) => {
    const v = root.__view;
    const layer = v.values[0];
    const vv = v.valueView();
    const xs = layer.xs(vv);
    const mid = (v.camera.left + v.camera.right) / 2;
    let i = 0;
    while (i + 1 < layer.data.runStarts[1] && xs[i] < mid) i++;
    return layer.position(i, vv);
  });
  const box = await stageBox(page);
  await page.mouse.move(box.x + p.x, box.y + p.y);
  const tip = page.locator(".atl-tooltip.atl-show");
  await expect(tip).toContainText("value");
  await expect(tip).toContainText("cpu %");
  // the cache's "down" state
  const down = await view(page).evaluate((root: any) => {
    const v = root.__view;
    const bars = v.bars[0];
    const i = bars.data.text.indexOf("down");
    return v.barPosition(0, i);
  });
  await page.mouse.move(box.x + down.x, box.y + down.y - 12);
  await expect(tip).toContainText("down"); // (its tooltip columns come from Python: tested there)
  await page.locator('.atl-toolbar button[aria-label="Order"]').click();
  await page.waitForTimeout(200);
  expect(errors).toEqual([]);
  await page.locator("#plot").screenshot({ path: "test-results/shots/service_health-order.png" });
});

test("Values only: Order is off", async ({ page }) => {
  await open(page, "latency_series");
  await expect(page.locator('.atl-toolbar button[aria-label="Order"]')).toBeDisabled();
  await page.keyboard.press("t");
  expect(await view(page).evaluate((root: any) => root.__view.xscale)).toBe("time");
});

test("Groups: a header folds its lanes, a box selects across groups, the plot is one", async ({ page }) => {
  await open(page, "host_groups");
  await expect(page.locator(".atl-root")).toHaveCount(1);
  const tree = await view(page).evaluate((root: any) => root.__view.spec.lanes.tree);
  expect(tree.header).toEqual([0, 6]);
  const all = await rows(page);
  expect(all.length).toBe(12);
  // fold web-1: its five lanes go, web-2 moves up
  const header = await laneName(page, 0);
  await page.mouse.click(header.x, header.y);
  expect(await rows(page)).toEqual([0, 6, 7, 8, 9, 10, 11]);
  await page.waitForTimeout(400);
  await page.mouse.click(header.x, header.y);
  expect((await rows(page)).length).toBe(12);
  // a box from web-1's db to web-2's gateway: lanes of both groups
  await page.locator('.atl-toolbar button[aria-label="Select"]').click();
  const box = await stageBox(page);
  const a = await laneName(page, 5);
  const b = await laneName(page, 7);
  await page.mouse.move(box.x + box.width * 0.3, a.y - 4);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5, b.y + 4, { steps: 5 });
  await page.mouse.up();
  expect((await picks(page)).at(-1)).toMatchObject({ kind: "box", lanes: [5, 7] });
});

test("Groups compared from their start: the axis counts from 0", async ({ page }) => {
  await open(page, "trace_compare");
  const time = await view(page).evaluate((root: any) => root.__view.spec.time);
  expect(time.kind).toBe("duration");
  expect(time.extent[0]).toBe(0);
});

test("Display: mark size and spreading reach the plot and Python; the key d switches spreading", async ({ page }) => {
  await open(page, "service_time");
  const marks = () =>
    view(page).evaluate((root: any) => {
      const l = root.__view.layers[0];
      let spread = 0;
      for (const d of l.draw.dy.data) spread = Math.max(spread, Math.abs(d));
      return { size: l.data.size[0], spread };
    });
  const before = await marks();
  expect(before.spread).toBeGreaterThan(0);
  await page.locator('.atl-toolbar button[aria-label="Display"]').click();
  await page.locator('.atl-popover button[aria-label="Smaller marks"]').click();
  await expect(page.locator(".atl-popover .atl-size").nth(1)).toHaveText("×0.75");
  expect(await state(page, "mark_scale")).toBe(0.75);
  await expect.poll(async () => (await marks()).size).toBeCloseTo(before.size * 0.75, 5);
  // spreading off: every event on its lane's line
  await page.locator(".atl-popover-check input").uncheck();
  expect(await state(page, "dodge")).toBe(false);
  await expect.poll(async () => (await marks()).spread).toBe(0);
  await page.locator('.atl-popover button[aria-label="Default mark size"]').click();
  expect(await state(page, "mark_scale")).toBe(1);
  await page.mouse.click(5, 300); // close the panel
  await view(page).click({ position: { x: 400, y: 200 } });
  await page.keyboard.press("d");
  expect(await state(page, "dodge")).toBe(true);
  // the next frame dodges again (a slow runner draws it later)
  await expect.poll(async () => (await marks()).spread).toBeGreaterThan(0);
});

test("Dodging in a tall lane: the rows spread out until marks no longer overlap", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await open(page, "service_time");
  const stats = await view(page).evaluate((root: any) => {
    const v = root.__view;
    v.setHeight(1000);
    const t = v.spec.time;
    // the burst of requests
    v.camera.fit(t.extent[0] + (t.extent[1] - t.extent[0]) * 0.55, t.extent[0] + (t.extent[1] - t.extent[0]) * 0.6, 0);
    v.renderFrame();
    const l = v.layers[0];
    const dy = l.draw.dy.data;
    const vis = Array.from(l.draw.visible.subarray(0, l.draw.visibleCount)) as number[];
    let overlapping = 0;
    for (const i of vis) {
      for (const j of vis) {
        if (i !== j && l.data.lane[i] === l.data.lane[j] && Math.abs(l.xs[i] - l.xs[j]) < l.data.size[i] * 0.85 && Math.abs(dy[i] - dy[j]) < l.data.size[i] * 0.85) {
          overlapping++;
          break;
        }
      }
    }
    let spread = 0;
    for (const i of vis) spread = Math.max(spread, Math.abs(dy[i]));
    return { laneH: v.laneH, inView: vis.length, overlapping, spread };
  });
  expect(stats.inView).toBeGreaterThan(200);
  expect(stats.overlapping).toBe(0); // was 283 of 312 with rows 0.6 of a mark apart
  expect(stats.spread).toBeLessThan(stats.laneH / 2); // and the marks stay in their lane
});

/** What a story draws: boxes, badges, whether boxes overlap or leave their lane, and whether a
 * stem passes behind a box. */
const stemCheck = (page: Page) =>
  view(page).evaluate((root: any) => {
    const v = root.__view;
    v.renderFrame();
    const boxes = v.stemHits;
    let overlap = false;
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        if (a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1) overlap = true;
      }
    }
    const plot = v.plot();
    const inLane = boxes.every((b: any) => {
      const lane = Math.floor(((b.y0 + b.y1) / 2 - (plot.y - v.scrollY)) / v.laneH);
      const top = plot.y - v.scrollY + lane * v.laneH;
      return b.y0 >= top - 0.5 && b.y1 <= top + v.laneH + 0.5;
    });
    const above = boxes.filter((b: any) => (b.y0 + b.y1) / 2 < plot.y - v.scrollY + v.laneH / 2).length;
    // stems behind boxes: a stem's x within a box nearer the line, on the same side
    const placed = [...v.stemCache.get(v.layers[0]).placed.values()].flat();
    let behind = 0;
    for (const a of placed) {
      for (const b of placed) {
        if (a === b || Math.sign(a.level) !== Math.sign(b.level) || Math.abs(b.level) >= Math.abs(a.level)) continue;
        if (a.cx > b.x0 && a.cx < b.x0 + b.w) behind++;
      }
    }
    const badged = v.badgeHits.reduce((n: number, h: any) => n + h.n, 0);
    return { count: boxes.length, badged, overlap, inLane, above, below: boxes.length - above, behind };
  });

test("Story: no box overlaps another or hides a stem; badges count the rest and zoom in", async ({ page }) => {
  await open(page, "story_incident");
  let s = await stemCheck(page);
  expect(s.count + s.badged).toBe(20); // every event: a box, or counted in a badge
  expect(s.overlap).toBe(false);
  expect(s.behind).toBe(0);
  expect(s.inLane).toBe(true);
  expect(s.badged).toBeGreaterThan(0); // the burst at the start does not fit at this zoom
  // a click on the biggest badge zooms in: more boxes there
  const badge = await view(page).evaluate((root: any) => [...root.__view.badgeHits].sort((a: any, b: any) => b.n - a.n)[0]);
  const stage = await stageBox(page);
  await page.mouse.click(stage.x + (badge.x0 + badge.x1) / 2, stage.y + (badge.y0 + badge.y1) / 2);
  await page.waitForTimeout(150);
  const zoomed = await stemCheck(page);
  expect(zoomed.overlap).toBe(false);
  expect(zoomed.behind).toBe(0);
  expect(zoomed.above).toBeGreaterThan(0);
  expect(zoomed.below).toBeGreaterThan(0); // both sides of the line, not one row
  // zoomed far out: still nothing overlaps or hides
  await view(page).evaluate((root: any) => {
    const v = root.__view;
    const t = v.spec.time.extent;
    v.camera.fit(t[0] - (t[1] - t[0]) * 10, t[1] + (t[1] - t[0]) * 10, 0);
  });
  s = await stemCheck(page);
  expect(s.overlap).toBe(false);
  expect(s.behind).toBe(0);
  expect(s.inLane).toBe(true);
  // the Order scale
  await page.locator('.atl-toolbar button[aria-label="Order"]').click();
  await page.keyboard.press("0");
  s = await stemCheck(page);
  expect(s.overlap).toBe(false);
  expect(s.behind).toBe(0);
  expect(s.count + s.badged).toBe(20);
  // hovering a box shows its event
  const box = await view(page).evaluate((root: any) => root.__view.stemHits[0]);
  await page.mouse.move(stage.x + (box.x0 + box.x1) / 2, stage.y + (box.y0 + box.y1) / 2);
  await expect(page.locator(".atl-tooltip.atl-show")).toBeVisible();
  await page.locator("#plot").screenshot({ path: "test-results/shots/story_incident-order.png" });
});

test("Story: long titles wrap within the box width", async ({ page }) => {
  await open(page, "story_wrapped");
  const widths = await view(page).evaluate((root: any) => {
    const v = root.__view;
    v.renderFrame();
    return v.stemHits.map((b: any) => b.x1 - b.x0);
  });
  expect(widths.length).toBeGreaterThan(5);
  for (const w of widths) expect(w).toBeLessThanOrEqual(16 * 12 + 1); // 16 × the text size
});

test("Story: the Display panel has no spreading switch, the plot no column of lane names", async ({ page }) => {
  await open(page, "story_incident");
  await page.locator('.atl-toolbar button[aria-label="Display"]').click();
  await expect(page.locator(".atl-popover-check")).toBeHidden();
  expect(await view(page).evaluate((root: any) => root.__view.gutter)).toBe(12);
});

test("a states tooltip shows every lane's state at the pointer's time, and follows the pointer", async ({ page }) => {
  await open(page, "service_health");
  const box = await stageBox(page);
  // a point in the cache's "down" state, a fraction of the way along it
  const target = (fraction: number) =>
    view(page).evaluate((root: any, f) => {
      const v = root.__view;
      const d = v.bars[0].data;
      const i = d.states.indexOf("down");
      const plot = v.plot();
      const x0 = Math.max(plot.x + (d.start[i] - v.camera.left) * v.camera.scale, plot.x) + 2;
      const x1 = Math.min(plot.x + (d.end[i] - v.camera.left) * v.camera.scale, plot.x + plot.w) - 2;
      return { x: x0 + (x1 - x0) * f, y: v.barPosition(0, i).y - 12 };
    }, fraction);
  // every lane's state at the pointer's time, from the bars one by one
  const expected = () =>
    view(page).evaluate((root: any) => {
      const v = root.__view;
      const d = v.bars[0].data;
      const t = v.camera.fromPx(v.pointer.x - v.plot().x);
      const states: Record<string, string> = {};
      for (let k = 0; k < d.count; k++) {
        if (d.start[k] <= t && t <= d.end[k]) states[v.spec.lanes.names[d.lane[k]]] = d.states[k];
      }
      return { states, time: v.axis.formatFull(t) };
    });
  const tip = page.locator(".atl-tooltip.atl-show");
  const rows = () =>
    tip.locator(".atl-tip-row").evaluateAll((els) =>
      els.map((e) => [...e.children].map((c) => c.textContent).concat(e.classList.contains("atl-tip-here") ? ["here"] : [])),
    );
  const times: string[] = [];
  for (const f of [0.1, 0.9]) {
    const p = await target(f);
    await page.mouse.move(box.x + p.x, box.y + p.y);
    const want = await expected();
    times.push(want.time);
    await expect.poll(async () => (await rows()).find((r) => r[0] === "time")?.[1]).toBe(want.time);
    const got = await rows();
    expect(Object.keys(want.states)).toHaveLength(5);
    for (const [lane, state] of Object.entries(want.states)) {
      expect(got.find((r) => r[0] === lane)?.slice(1, 2)).toEqual([state]);
    }
    expect(got.filter((r) => r.includes("here"))).toEqual([["cache", "down", "here"]]);
  }
  expect(times[0]).not.toBe(times[1]);
  await page.screenshot({ path: "test-results/shots/states_tooltip.png" });
  // the hovered state's own rows follow the lanes; its tooltip columns come from Python
  await expect(tip).toContainText("duration");
});

test("Find: / opens the search box, Enter steps through lanes and marks, Esc closes it", async ({ page }) => {
  await open(page, "gantt_plan");
  await view(page).click({ position: { x: 4, y: 4 } });
  await page.keyboard.press("/");
  const box = page.locator(".atl-finder input");
  await expect(box).toBeFocused();
  await box.fill("build");
  // two lanes by name, two bars by their text
  await expect(page.locator(".atl-finder-status")).toHaveText("4 found");
  // the plot's keys stay out of the box
  await box.press("z");
  expect(await state(page, "tool")).toBe("pan");
  await box.fill("build");
  await expect(page.locator(".atl-finder-status")).toHaveText("4 found");
  for (let i = 0; i < 3; i++) await box.press("Enter");
  await expect(page.locator(".atl-finder-status")).toHaveText("3 of 4");
  const focus = () => view(page).evaluate((root: any) => root.__view.focus);
  expect(await focus()).toMatchObject({ text: "Build backend" });
  await box.press("Shift+Enter");
  await expect(page.locator(".atl-finder-status")).toHaveText("2 of 4");
  await box.press("Escape");
  await expect(page.locator(".atl-finder")).toBeHidden();
  expect(await focus()).toBeNull();
  // Ctrl/Cmd+F opens it too
  await page.keyboard.press("ControlOrMeta+f");
  await expect(box).toBeFocused();
  await box.press("Escape");
});

test("Step: . and , go to the next and previous mark of a lane; F fits the view to it", async ({ page }) => {
  await open(page, "service_time");
  await view(page).click({ position: { x: 4, y: 4 } });
  const focus = () => view(page).evaluate((root: any) => root.__view.focus);
  const span = () => view(page).evaluate((root: any) => root.__view.camera.span);
  // a key, then the mark it went to (each step waits for Python, or here for the fallback)
  const press = async (key: string) => {
    const was = JSON.stringify(await focus());
    await page.keyboard.press(key);
    await expect.poll(async () => JSON.stringify(await focus())).not.toBe(was);
    return focus();
  };
  const first = await press(".");
  const second = await press(".");
  const third = await press(".");
  expect(second.x).toBeGreaterThanOrEqual(first.x);
  expect(third.x).toBeGreaterThanOrEqual(second.x);
  expect(third.lane).toBe(first.lane);
  const back = await press(",");
  expect(back.index).toBe(second.index);
  const before = await span();
  await page.keyboard.press("F");
  expect(await span()).toBeLessThan(before);
  await page.keyboard.press("Escape");
  expect(await focus()).toBeNull();
});

test("Summary: Python's numbers show in a panel while something is selected; × hides it", async ({ page }) => {
  await open(page, "gantt_plan");
  await expect(page.locator(".atl-summary")).toHaveCount(0);
  const summary = [{ layer: "tasks", columns: ["count", "total", "mean"], total: { count: "3", total: "30 d", mean: "10 d", open: "1 open" }, blocks: [{ title: "phase", rows: [{ count: "2", total: "16 d", mean: "8 d", label: "plan", color: "#4c78a8" }, { count: "1", total: "14 d", mean: "14 d", label: "build", color: "#f58518" }], more: 0 }] }];
  await page.evaluate((s) => {
    (window as any).__model.state._summary = s;
    (window as any).__model.emit("change:_summary");
  }, summary);
  const panel = page.locator(".atl-summary");
  await expect(panel).toContainText("3 selected");
  await expect(panel).toContainText("1 open: no duration");
  await expect(panel.locator(".atl-summary-all")).toContainText("30 d");
  await expect(panel).toContainText("by phase");
  await expect(panel.locator(".atl-summary-swatch")).toHaveCount(2);
  await panel.locator(".atl-summary-close").click();
  await expect(page.locator(".atl-summary")).toHaveCount(0);
  await page.evaluate((s) => {
    (window as any).__model.state._summary = s;
    (window as any).__model.emit("change:_summary");
  }, summary);
  await expect(page.locator(".atl-summary")).toHaveCount(1);
});

test("Annotate: a, then a drag, then text and Enter sends the note to Python; c joins two marks", async ({ page }) => {
  await open(page, "service_time");
  await view(page).click({ position: { x: 4, y: 4 } });
  const sent = (type: string) => page.evaluate((t) => (window as any).__log.filter((m: any) => m.type === t), type);
  await page.keyboard.press("a");
  await expect(page.locator(".atl-mode")).toContainText("Annotate");
  const a = await eventAt(page, 0, 10);
  const b = await eventAt(page, 0, 40);
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move(b.x, a.y + 2, { steps: 4 });
  await page.mouse.up();
  await expect(page.locator(".atl-mode")).toHaveCount(0);
  const input = page.locator(".atl-note-input");
  await expect(input).toBeFocused();
  await input.fill("incident");
  await input.press("Enter");
  await expect(input).toHaveCount(0);
  const [note] = await sent("annotate");
  expect(note).toMatchObject({ text: "incident" });
  expect(note.x1).toBeGreaterThan(note.x0);
  expect(note.lane).not.toBeNull(); // the drag stayed in one lane
  // Esc drops a note
  await page.keyboard.press("a");
  await page.mouse.click(b.x, b.y);
  await page.locator(".atl-note-input").press("Escape");
  expect(await sent("annotate")).toHaveLength(1);
  // c on a mark, then on another
  await page.mouse.move(a.x, a.y);
  await expect(page.locator(".atl-tooltip.atl-show")).toBeVisible();
  await page.keyboard.press("c");
  await expect(page.locator(".atl-mode")).toContainText("Connect");
  await page.mouse.move(b.x, b.y);
  await expect(page.locator(".atl-tooltip.atl-show")).toBeVisible();
  await page.keyboard.press("c");
  const [link] = await sent("connect");
  expect(link.a.index).not.toBe(link.b.index);
  // what Python sends back is drawn (no error), and pages draw it too
  await page.evaluate((n) => {
    (window as any).__model.state._notes = n;
    (window as any).__model.emit("change:_notes");
  }, { bands: [{ x0: note.x0, x1: note.x1, point: false, lane: note.lane, text: "incident", color: null }], arrows: [] });
  expect(await view(page).evaluate((root: any) => root.__view.notes.bands.length)).toBe(1);
});

/** Where bar `index` of the first intervals layer starts or ends (page px). */
async function barEdge(page: Page, index: number, side: "start" | "end"): Promise<{ x: number; y: number }> {
  const mid = await barAt(page, 0, index);
  const box = await stageBox(page);
  const x = await view(page).evaluate((root: any, [i, s]) => {
    const v = root.__view;
    const d = v.bars[0].data;
    return v.plot().x + v.camera.toPx(s === "start" ? d.start[i] : d.end[i]);
  }, [index, side] as const);
  return { x: box.x + x, y: mid.y };
}

test("Measure: a drag between edges, a double-click on a bar, m; a measure's label selects it", async ({ page }) => {
  await open(page, "gantt_plan");
  const sent = (type: string) => page.evaluate((t) => (window as any).__log.filter((m: any) => m.type === t), type);
  await page.getByRole("button", { name: "Measure" }).click();
  expect(await state(page, "tool")).toBe("measure");
  // a drag from one bar's end to another's start, each taken from a few pixels off
  const a = await barEdge(page, 0, "end");
  const b = await barEdge(page, 4, "start");
  await page.mouse.move(a.x + 3, a.y);
  await page.mouse.down();
  await page.mouse.move(b.x - 3, b.y, { steps: 6 });
  await page.mouse.up();
  const [drag] = await sent("measure");
  expect(drag.a).toMatchObject({ side: "end", index: expect.any(Number) });
  expect(drag.b).toMatchObject({ side: "start" });
  expect(drag.a.index).not.toBe(drag.b.index);
  // a double-click on a bar: its own length
  const mid = await barAt(page, 0, 4);
  await page.mouse.dblclick(mid.x, mid.y);
  const own = (await sent("measure"))[1];
  expect(own.a).toMatchObject({ side: "start", index: own.b.index });
  expect(own.b.side).toBe("end");
  // m, then Esc: nothing measured
  await page.mouse.move(a.x, a.y);
  await page.keyboard.press("m");
  await expect(page.locator(".atl-mode")).toContainText("Measure");
  await page.keyboard.press("Escape");
  await expect(page.locator(".atl-mode")).toHaveCount(0);
  expect(await sent("measure")).toHaveLength(2);
  // what Python sends back is drawn; its label shows the times and selects it
  const end = (x: number) => ({ x, r: null, lane: 0, side: "start", layer: "intervals", index: 0 });
  const span = await view(page).evaluate((root: any) => root.__view.bars[0].data.end[0] - root.__view.bars[0].data.start[0]);
  await page.evaluate((n) => {
    (window as any).__model.state._notes = n;
    (window as any).__model.emit("change:_notes");
  }, { measures: [{ a: end(0), b: { ...end(span), side: "end" }, span, events: null, lane: null, text: null, color: null, id: 0 }] });
  await expect.poll(() => view(page).evaluate((root: any) => root.__view.measureHits.length)).toBe(1);
  const hit = await view(page).evaluate((root: any) => root.__view.measureHits[0]);
  const box = await stageBox(page);
  const label = { x: box.x + hit.lx + hit.tw / 2, y: box.y + hit.y };
  await page.mouse.move(label.x, label.y);
  await expect(page.locator(".atl-tooltip.atl-show")).toContainText("plot.notes[0]");
  await page.mouse.click(label.x, label.y);
  const menu = page.locator(".atl-menu");
  await expect(menu).toBeVisible();
  await menu.getByRole("menuitem", { name: "Remove" }).click();
  expect(await sent("note_remove")).toEqual([expect.objectContaining({ id: 0 })]);
});

test("Measure: between two samples of a values layer, with the change in value", async ({ page }) => {
  await open(page, "latency_series");
  await page.getByRole("button", { name: "Measure" }).click();
  // two samples of the first lane's first line (at the same time as the second line's)
  const [a, b] = await view(page).evaluate((root: any) => {
    const v = root.__view;
    const vv = v.valueView();
    const box = root.querySelector(".atl-stage").getBoundingClientRect();
    return [10, 30].map((i) => {
      const p = v.values[0].position(i, vv);
      return { x: box.x + p.x, y: box.y + p.y, value: v.values[0].data.value[i] };
    });
  });
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move(b.x, b.y, { steps: 6 });
  await page.mouse.up();
  const [sent] = await page.evaluate(() => (window as any).__log.filter((m: any) => m.type === "measure"));
  expect(sent.a).toEqual({ layer: "values", index: 10, side: "start" });
  expect(sent.b).toEqual({ layer: "values", index: 30, side: "start" });
  // drawn as Python sends it back: the change in its label
  const end = (index: number, x: number, value: number) => ({ x, r: null, lane: 0, side: "start", layer: "values", index, value });
  await page.evaluate((n) => {
    (window as any).__model.state._notes = n;
    (window as any).__model.emit("change:_notes");
  }, { measures: [{ a: end(10, 0, a.value), b: end(30, 600, b.value), span: 600, events: null, change: b.value - a.value, lane: null, text: null, color: null, id: 0 }] });
  await expect.poll(() => view(page).evaluate((root: any) => root.__view.measureHits[0]?.text ?? "")).toContain("Δ");
});

test("Undo: Ctrl/Cmd+Z asks Python to take back a change of the selection, Shift for redo", async ({ page }) => {
  await open(page, "service_time");
  await view(page).click({ position: { x: 4, y: 4 } });
  await page.keyboard.press("ControlOrMeta+z");
  await page.keyboard.press("ControlOrMeta+Shift+z");
  const sent = await page.evaluate(() => (window as any).__log.filter((m: any) => m.type === "undo" || m.type === "redo").map((m: any) => m.type));
  expect(sent).toEqual(["undo", "redo"]);
});

test.describe("touch", () => {
  test.use({ hasTouch: true });

  test("a tap gives the plot the fingers; before it, a touch does not take them", async ({ page }) => {
    await open(page, "service_time");
    const focused = () => view(page).evaluate((root: HTMLElement) => root.contains(document.activeElement));
    expect(await focused()).toBe(false);
    const box = await stageBox(page);
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    await expect.poll(focused).toBe(true);
    await expect(page.locator(".atl-notice")).toContainText("pinch to zoom");
    // a tap once it has them: a click as with a mouse (Pan: nothing selected)
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    expect(await picks(page)).toEqual([]);
  });
});
