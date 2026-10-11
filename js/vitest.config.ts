import { defineConfig } from "vitest/config";

// unit tests only; the visual tests (test/visual) run with Playwright
export default defineConfig({ test: { include: ["test/*.test.ts"] } });
