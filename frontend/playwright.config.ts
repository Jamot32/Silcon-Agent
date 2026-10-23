import { defineConfig } from "@playwright/test";

// Use an explicitly started app. Offline checks create only a labeled replay;
// real model/EDA builds require the separate opt-in live test.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: "list",
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR ?? "/tmp/silicon-agent-playwright",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    viewport: { width: 1920, height: 1080 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    serviceWorkers: "block",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
