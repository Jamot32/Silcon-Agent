import { expect, test, type Page } from "@playwright/test";

interface PublicRun {
  id: string;
  status: string;
  stage: string;
  is_replay: boolean;
}

test.beforeEach(async ({ page }) => {
  // These checks only observe runs. Block mutations even if a UI regression
  // accidentally submits the form or cancels the existing live run.
  await page.route("**/api/**", async (route) => {
    if (["GET", "HEAD"].includes(route.request().method())) await route.continue();
    else await route.abort("blockedbyclient");
  });
});

async function assertFinishedDashboard(page: Page, runId: string, minimumFlowPoints = 2) {
  await expect(page.getByTestId("run-dashboard")).toBeVisible();
  await expect(page.getByTestId("stage-timeline")).toContainText("DONE");
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "done");
  await expect(page.getByTestId("event-log")).not.toBeEmpty();
  await expect.poll(async () => Number(await page.getByTestId("test-results").getAttribute("data-test-count"))).toBeGreaterThanOrEqual(4);
  await expect.poll(async () => Number(await page.getByTestId("metrics-chart").getAttribute("data-point-count"))).toBeGreaterThanOrEqual(minimumFlowPoints);

  const metricsResponse = await page.request.get(`/api/runs/${runId}/metrics`);
  expect(metricsResponse.ok()).toBeTruthy();
  const metrics = await metricsResponse.json() as unknown[];
  expect(metrics.length).toBeGreaterThanOrEqual(minimumFlowPoints);
  await expect(page.getByTestId("metrics-chart")).toHaveAttribute("data-point-count", String(metrics.length));
  await assertChartRendered(page);

  const filesResponse = await page.request.get(`/api/runs/${runId}/files`);
  expect(filesResponse.ok()).toBeTruthy();
  const files = await filesResponse.json() as Record<string, string>;
  const rtlPath = Object.keys(files).find((path) => path.startsWith("src/") && path.endsWith(".v"));
  const testPath = Object.keys(files).find((path) => path.startsWith("test/") && path.endsWith(".py"));
  expect(rtlPath).toBeTruthy();
  expect(testPath).toBeTruthy();
  const source = page.getByTestId("source-editor");
  await expect(source).toBeVisible();
  for (const path of [testPath!, rtlPath!]) {
    await page.getByRole("tab", { name: path, exact: true }).click();
    await expect(source).toHaveAttribute("data-file-path", path);
    await expect(source.locator(".monaco-editor:visible .view-lines:visible").first()).toBeVisible();
  }

  const layout = page.getByTestId("layout-image");
  await expect(layout).toBeVisible();
  await expect(layout).toHaveAttribute("src", new RegExp(`/api/runs/${runId}/layout/`));
  await expect.poll(async () => layout.evaluate((node) => node instanceof HTMLImageElement && node.complete && node.naturalWidth > 0)).toBeTruthy();
}

async function assertChartRendered(page: Page) {
  const chart = page.getByTestId("metrics-chart").locator("svg.recharts-surface").first();
  await expect(chart).toBeVisible();
  const bounds = await chart.boundingBox();
  expect(bounds?.width).toBeGreaterThan(0);
  expect(bounds?.height).toBeGreaterThan(0);
}

test("new-design screen loads and presets change the specification without creating a job", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/");
  await expect(page).toHaveTitle(/Silicon Agent/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const specification = page.getByRole("textbox", { name: /describe|specification/i });
  await expect(specification).toBeVisible();
  await page.getByRole("button", { name: /PWM/i, exact: true }).click();
  await expect(specification).toHaveValue(/PWM/i);
  await page.getByRole("button", { name: /Counter/i, exact: true }).click();
  await expect(specification).toHaveValue(/counter/i);
  expect(pageErrors).toEqual([]);
});

test("completed real run displays recorded evidence and a loadable layout", async ({ page, request }, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const response = await request.get("/api/runs");
  expect(response.ok()).toBeTruthy();
  const runs = await response.json() as PublicRun[];
  const run = process.env.READONLY_RUN_ID
    ? runs.find((candidate) => candidate.id === process.env.READONLY_RUN_ID)
    : runs.find((candidate) => candidate.status === "done" && !candidate.is_replay);
  if (process.env.READONLY_RUN_ID) expect(run, "READONLY_RUN_ID must identify an existing run").toBeDefined();
  test.skip(!run, "No completed real run is available; this test never creates one.");
  expect(run!.status).toBe("done");
  expect(run!.is_replay).toBe(false);
  testInfo.annotations.push({ type: "existing_run_id", description: run!.id });
  await page.goto(`/runs/${run!.id}`);
  await assertFinishedDashboard(page, run!.id);
  await page.setViewportSize({ width: 390, height: 844 });
  await assertChartRendered(page);
  expect(pageErrors).toEqual([]);
});

test.describe("real active run @live", () => {
  test.skip(process.env.LIVE_EDA !== "1", "Opt in with LIVE_EDA=1 and an existing new LIVE_RUN_ID; no run is created by this test.");

  test("receives new stage, log, code, tests, metrics, and layout over SSE", async ({ page, request }, testInfo) => {
    test.setTimeout(20 * 60_000);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const runId = process.env.LIVE_RUN_ID ?? "";
    const minimumFlowPoints = Number(process.env.LIVE_MIN_FLOW_POINTS ?? "2");
    expect(Number.isInteger(minimumFlowPoints) && minimumFlowPoints >= 2 && minimumFlowPoints <= 6, "LIVE_MIN_FLOW_POINTS must be an integer from 2 to 6").toBe(true);
    expect(runId, "Supply the ID of a run created explicitly through the app").toMatch(/^[0-9a-f]{32}$/);
    const initialResponse = await request.get(`/api/runs/${runId}`);
    expect(initialResponse.ok()).toBeTruthy();
    const initial = await initialResponse.json() as PublicRun;
    expect(initial.is_replay).toBe(false);
    expect(["pending", "running"]).toContain(initial.status);
    testInfo.annotations.push({ type: "live_run_id", description: runId });
    testInfo.annotations.push({ type: "attachment_stage", description: initial.stage });
    const recovery = process.env.LIVE_RECOVERY === "1";
    testInfo.annotations.push({ type: "observation", description: recovery ? "recovery: new SSE events and completion; earlier stages not observed live" : "new stage, code, and test events" });

    await page.goto(`/runs/${runId}`);
    await expect(page.getByTestId("run-dashboard")).toBeVisible();
    const log = page.getByTestId("event-log");
    const source = page.getByTestId("source-editor");
    const tests = page.getByTestId("test-results");
    const firstEvent = Number(await log.getAttribute("data-last-event-id") ?? "0");
    const firstFile = Number(await source.getAttribute("data-last-file-event-id") ?? "0");
    const firstTest = Number(await tests.getAttribute("data-last-test-event-id") ?? "0");

    await Promise.all([
      expect.poll(async () => {
        const stage = (await page.getByTestId("stage-current").textContent())?.trim();
        return stage !== initial.stage && /^(SPEC|RTL|VERIFY|SYNTH|FLOW|OPTIMIZE|SIGNOFF|PACKAGE|DONE)$/.test(stage ?? "");
      }, { timeout: 3 * 60_000 }).toBe(true),
      expect.poll(async () => Number(await log.getAttribute("data-last-event-id") ?? "0"), { timeout: 3 * 60_000 }).toBeGreaterThan(firstEvent),
      ...(recovery ? [] : [
        expect.poll(async () => Number(await source.getAttribute("data-last-file-event-id") ?? "0"), { timeout: 6 * 60_000 }).toBeGreaterThan(firstFile),
        expect.poll(async () => Number(await tests.getAttribute("data-last-test-event-id") ?? "0"), { timeout: 10 * 60_000 }).toBeGreaterThan(firstTest),
      ]),
      (async () => {
        await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", /^(done|failed|cancelled)$/, { timeout: 19 * 60_000 });
        await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "done");
      })(),
    ]);
    await expect(page.getByTestId("stage-current")).toHaveText("DONE");
    await assertFinishedDashboard(page, runId, minimumFlowPoints);
    expect(pageErrors).toEqual([]);
  });
});
