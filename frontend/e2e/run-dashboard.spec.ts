import { expect, test, type Page } from "@playwright/test";
import type { Metric, PublicRun } from "../lib/api";

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

test("result page selects the best real layout and downloads its bundle", async ({ page, request }, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const runsResponse = await request.get("/api/runs");
  expect(runsResponse.ok()).toBeTruthy();
  const runs = await runsResponse.json() as PublicRun[];
  const run = process.env.READONLY_RUN_ID
    ? runs.find((candidate) => candidate.id === process.env.READONLY_RUN_ID)
    : runs.find((candidate) => candidate.status === "done" && !candidate.is_replay && candidate.best_run_tag);
  if (process.env.READONLY_RUN_ID) expect(run, "READONLY_RUN_ID must identify an existing run").toBeDefined();
  test.skip(!run, "No completed real run is available; this test never creates one.");
  expect(run!.status).toBe("done");
  expect(run!.is_replay).toBe(false);
  expect(run!.best_run_tag).toBeTruthy();
  const metricsResponse = await request.get(`/api/runs/${run!.id}/metrics`);
  expect(metricsResponse.ok()).toBeTruthy();
  const metrics = await metricsResponse.json() as Metric[];
  const best = metrics.find((metric) => metric.run_tag === run!.best_run_tag);
  expect(best, "The selected result must have an actual metric record").toBeDefined();
  testInfo.annotations.push({ type: "existing_run_id", description: run!.id });
  testInfo.annotations.push({ type: "selected_best_tag", description: run!.best_run_tag! });

  await page.goto(`/runs/${run!.id}/result`);
  await expect(page.getByTestId("result-dashboard")).toBeVisible();
  const layout = page.getByTestId("result-layout-image");
  await expect(layout).toBeVisible();
  const expectedLayout = `/api/runs/${run!.id}/layout/${encodeURIComponent(run!.best_run_tag!)}.png`;
  await expect(layout).toHaveAttribute("src", expectedLayout);
  await expect.poll(async () => layout.evaluate((node) => node instanceof HTMLImageElement && node.complete && node.naturalWidth > 0)).toBeTruthy();

  const targets = { ...run!.design_spec?.targets, ...run!.targets };
  const targetTable = page.getByTestId("result-targets");
  const displayNumber = (value: number, digits = 2) => value.toLocaleString("en-US", { maximumFractionDigits: digits });
  await expect(targetTable).toBeVisible();
  if (targets.clock_mhz != null) await expect(targetTable).toContainText(`${displayNumber(targets.clock_mhz)} MHz`);
  await expect(targetTable).toContainText(`${displayNumber(best!.clock_mhz)} MHz`);
  await expect(targetTable).toContainText(`${displayNumber(best!.wns_ns, 3)} ns`);
  await expect(targetTable).toContainText(displayNumber(best!.area_um2));
  if (targets.max_area_um2 != null) await expect(targetTable).toContainText(displayNumber(targets.max_area_um2));
  else await expect(targetTable).toContainText(/no target/i);
  if (targets.fit === "tt_1x1_tile" && !run!.tapeout_ready) await expect(targetTable).toContainText(/unverified/i);
  const signoff = page.getByTestId("result-signoff");
  await expect(signoff).toContainText(new RegExp(`DRC\\s*${best!.drc_ok === true ? "clean" : best!.drc_ok === false ? "failed" : "unknown"}`, "i"));
  await expect(signoff).toContainText(new RegExp(`LVS\\s*${best!.lvs_ok === true ? "clean" : best!.lvs_ok === false ? "failed" : "unknown"}`, "i"));

  const download = page.getByTestId("bundle-download");
  await expect(download).toBeVisible();
  const bundlePath = `/api/runs/${run!.id}/bundle.zip`;
  await expect(download).toHaveAttribute("href", bundlePath);
  const bundleResponse = await request.get(bundlePath);
  expect(bundleResponse.ok()).toBeTruthy();
  expect(bundleResponse.headers()["content-type"]).toContain("application/zip");
  expect(bundleResponse.headers()["content-disposition"]).toContain(`silicon-agent-${run!.id}.zip`);
  const bundle = await bundleResponse.body();
  expect([...bundle.subarray(0, 4)]).toEqual([0x50, 0x4b, 0x03, 0x04]);
  const back = page.getByRole("link", { name: /back to live run|view live run/i });
  await expect(back).toHaveAttribute("href", `/runs/${run!.id}`);
  await back.click();
  await expect(page.getByTestId("run-dashboard")).toBeVisible();
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
