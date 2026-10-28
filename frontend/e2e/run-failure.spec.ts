import { expect, test } from "@playwright/test";
import type { APIRequestContext, Page, TestInfo } from "@playwright/test";
import type { Metric, PublicRun, RunEvent } from "../lib/api";

async function persistedEvents(request: APIRequestContext, runId: string): Promise<RunEvent[]> {
  const response = await request.get(`/api/runs/${runId}/events?after=0`);
  expect(response.ok()).toBeTruthy();
  return (await response.text()).split("\n")
    .filter((line) => line.startsWith("data: "))
    .map((line) => JSON.parse(line.slice(6)) as RunEvent);
}

async function assertSimulatorEvidence(page: Page, events: RunEvent[], testInfo: TestInfo) {
  const latest = events.filter((event) => event.type === "test_result").at(-1);
  const panel = page.getByTestId("test-results");
  if (!latest) {
    testInfo.annotations.push({ type: "simulator_evidence", description: "No persisted test_result event." });
    await expect(panel).toHaveAttribute("data-last-test-event-id", "0");
    await expect(panel).toHaveAttribute("data-test-count", "0");
    await expect(panel).toContainText("No results");
    await expect(panel).toContainText("No simulator results were recorded before this run ended.");
    return;
  }
  const { passed, failed, skipped } = latest.payload;
  testInfo.annotations.push({ type: "simulator_evidence", description: JSON.stringify({ event_id: latest.id, passed, failed, skipped }) });
  await expect(panel).toHaveAttribute("data-last-test-event-id", String(latest.id));
  await expect(panel).not.toContainText("No results");
  if (typeof passed === "number" && typeof failed === "number") {
    const total = passed + failed + (typeof skipped === "number" ? skipped : 0);
    await expect(panel).toHaveAttribute("data-test-count", String(total));
    await expect(panel).toContainText(`${passed} / ${total} passed`);
  } else {
    await expect(panel).toContainText("Execution failed");
  }
}

test.beforeEach(async ({ page }) => {
  // These checks observe existing evidence only, including terminal states.
  await page.route("**/api/**", async (route) => {
    if (["GET", "HEAD"].includes(route.request().method())) await route.continue();
    else await route.abort("blockedbyclient");
  });
});

for (const evidence of ["none", "partial"] as const) {
  test(`existing failed run preserves ${evidence} physical evidence without offering a bundle`, async ({ page, request }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const runsResponse = await request.get("/api/runs");
    expect(runsResponse.ok()).toBeTruthy();
    const runs = await runsResponse.json() as PublicRun[];
    const run = runs.find((candidate) => candidate.status === "failed" && !candidate.is_replay
      && Boolean(candidate.best_run_tag) === (evidence === "partial") && candidate.error);
    test.skip(!run, `No existing failed run with ${evidence} evidence is available; this check never creates one.`);
    testInfo.annotations.push({ type: "existing_failed_run_id", description: run!.id });
    const metricsResponse = await request.get(`/api/runs/${run!.id}/metrics`);
    expect(metricsResponse.ok()).toBeTruthy();
    const metrics = await metricsResponse.json() as Metric[];
    const events = await persistedEvents(request, run!.id);

    await page.goto(`/runs/${run!.id}`);
    await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "failed");
    await expect(page.getByTestId("run-dashboard").getByRole("alert")).toContainText(run!.error!);
    await expect(page.getByRole("link", { name: "Download bundle" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /cancel run|stop replay/i })).toHaveCount(0);
    await expect(page.getByTestId("metrics-chart")).toHaveAttribute("data-point-count", String(metrics.length));
    await assertSimulatorEvidence(page, events, testInfo);
    if (evidence === "none") {
      expect(metrics).toHaveLength(0);
      await expect(page.getByTestId("layout-image")).toHaveCount(0);
      await expect(page.getByText("No layout was produced before this run ended.")).toBeVisible();
    }

    await page.goto(`/runs/${run!.id}/result`);
    await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "failed");
    await expect(page.getByTestId("result-dashboard").getByRole("alert")).toContainText(run!.error!);
    await expect(page.getByTestId("bundle-download")).toHaveCount(0);
    if (evidence === "none") {
      await expect(page.getByTestId("result-layout-image")).toHaveCount(0);
      await expect(page.getByTestId("result-targets").getByRole("row", { name: /^Clock/ })).toContainText("Unknown");
      await expect(page.getByTestId("result-signoff")).toContainText("Block signoff is incomplete.");
      await expect(page.getByTestId("result-signoff").getByText("unknown", { exact: true })).toHaveCount(2);
    } else {
      const selected = metrics.find((metric) => metric.run_tag === run!.best_run_tag);
      expect(selected, "A displayed partial layout must have real metric evidence").toBeDefined();
      const image = page.getByTestId("result-layout-image");
      await expect(image).toHaveAttribute("src", `/api/runs/${run!.id}/layout/${encodeURIComponent(run!.best_run_tag!)}.png`);
      await expect.poll(async () => image.evaluate((node) => node instanceof HTMLImageElement && node.complete && node.naturalWidth > 0)).toBe(true);
      await expect(page.getByTestId("result-targets")).toContainText(new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(selected!.area_um2));
    }
    await page.getByRole("link", { name: "Back to live run" }).click();
    await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "failed");
    expect(errors).toEqual([]);
  });
}

test("existing failed run without simulator evidence shows the genuine no-test state", async ({ page, request }, testInfo) => {
  const response = await request.get("/api/runs");
  expect(response.ok()).toBeTruthy();
  const runs = await response.json() as PublicRun[];
  let selected: { run: PublicRun; events: RunEvent[] } | undefined;
  for (const run of runs.filter((candidate) => candidate.status === "failed" && !candidate.is_replay)) {
    const events = await persistedEvents(request, run.id);
    if (!events.some((event) => event.type === "test_result")) {
      selected = { run, events };
      break;
    }
  }
  test.skip(!selected, "No existing failed run without simulator evidence is available; this check never creates one.");
  testInfo.annotations.push({ type: "existing_failed_run_id", description: selected!.run.id });
  await page.goto(`/runs/${selected!.run.id}`);
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "failed");
  await assertSimulatorEvidence(page, selected!.events, testInfo);
});

test("unreachable API shows unavailable states and a return path without manufacturing run evidence", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // Deliberately fail transport; no synthetic health, run, metric, or event payloads.
  await page.route("**/api/**", (route) => route.abort("internetdisconnected"));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Toolchain" })).toBeVisible();
  for (const label of ["API", "Database", "EDA", "Model"]) {
    await expect(page.locator(".check-row").filter({ has: page.getByText(label, { exact: true }) })).toContainText("Unavailable");
  }
  await page.goto("/runs");
  await expect(page.getByText("Recordings could not be loaded.")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Replay/ })).toHaveCount(0);
  await page.goto("/runs/00000000000000000000000000000000");
  await expect(page.getByRole("heading", { name: "Run unavailable." })).toBeVisible();
  await expect(page.getByTestId("run-dashboard")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Download bundle" })).toHaveCount(0);
  await page.getByRole("link", { name: /Return to run history/ }).click();
  await expect(page).toHaveURL(/\/runs$/);
  await expect(page.getByRole("heading", { level: 1, name: "Run history." })).toBeVisible();
  expect(errors).toEqual([]);
});
