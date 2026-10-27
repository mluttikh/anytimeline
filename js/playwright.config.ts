import { defineConfig } from "@playwright/test";

// Visual tests (npm run test:visual). esbuild bundles the harness and serves js/.
// Scenes come from `uv run python scripts/make_scenes.py`.
export default defineConfig({
  testDir: "test/visual",
  testMatch: "*.spec.ts",
  snapshotPathTemplate: "{testDir}/screenshots/{arg}-{platform}{ext}",
  ignoreSnapshots: process.platform !== "darwin",
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4183",
    viewport: { width: 940, height: 640 },
    // what a failure on CI looked like (uploaded with the test results)
    screenshot: process.env.CI ? "only-on-failure" : "off",
    trace: process.env.CI ? "retain-on-failure" : "off",
    deviceScaleFactor: 1,
    // full Chromium in new headless mode uses the real GPU; the minimal headless shell
    // cannot present WebGPU canvases
    channel: "chromium",
    launchOptions: {
      args: [
        "--enable-unsafe-webgpu",
        "--ignore-gpu-blocklist",
        ...(process.env.CI ? ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] : []),
      ],
    },
  },
  // notebooks (a JupyterLab, a marimo with kernels) after the rest: they start servers and
  // kernels, which a machine busy drawing every scene on every backend slows down too much
  projects: [
    { name: "browser", testIgnore: ["**/jupyterlab.spec.ts", "**/notebook.spec.ts", "**/levels.spec.ts"] },
    { name: "notebooks", testMatch: ["**/jupyterlab.spec.ts", "**/notebook.spec.ts", "**/levels.spec.ts"], dependencies: ["browser"] },
  ],
  webServer: {
    command:
      "npx esbuild test/visual/harness.ts --bundle --format=esm --outdir=test/visual/dist --servedir=. --serve=127.0.0.1:4183",
    url: "http://127.0.0.1:4183/test/visual/harness.html",
    reuseExistingServer: !process.env.CI,
  },
});
