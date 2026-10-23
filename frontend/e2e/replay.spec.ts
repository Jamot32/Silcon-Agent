import { expect, test } from "@playwright/test";
import type { Metric, PublicRun, Recording } from "../lib/api";

test("recorded UART replays at 4× with actual metrics and artifacts @replay", async ({ page, request }, testInfo) => {
  test.setTimeout(150_000);
  const recordingId = "uart-optimization";
  const blockedMutations: string[] = [];
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/api/**", async (route) => {
    const call = route.request();
    if (["GET", "HEAD"].includes(call.method())) return route.continue();
    if (call.method() === "POST" && new URL(call.url()).pathname === "/api/replays") {
      const body = call.postDataJSON() as { recording_id?: unknown; speed?: unknown };
      if (body.recording_id === recordingId && body.speed === 4) return route.continue();
    }
    blockedMutations.push(`${call.method()} ${new URL(call.url()).pathname}`);
    await route.abort("blockedbyclient");
  });

  const [catalogResponse, runsResponse] = await Promise.all([
    request.get("/api/recordings"), request.get("/api/runs"),
  ]);
  expect(catalogResponse.ok()).toBeTruthy();
  expect(runsResponse.ok()).toBeTruthy();
  const catalog = await catalogResponse.json() as Recording[];
  const recording = catalog.find((entry) => entry.id === recordingId);
  expect(recording, "The committed real UART recording must be installed").toBeDefined();
  expect(recording!.flow_count).toBeGreaterThanOrEqual(3);
  const runs = await runsResponse.json() as PublicRun[];
  expect(runs.find((run) => ["pending", "running"].includes(run.status)), "Finish the active job before running offline replay checks").toBeUndefined();

  await page.goto("/");
  const row = page.locator(`[data-recording-id="${recordingId}"]`);
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: `Replay ${recording!.name} at 4×`, exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f]{32}$/);
  const runId = new URL(page.url()).pathname.split("/").at(-1)!;
  testInfo.annotations.push({ type: "replay_run_id", description: runId });
  testInfo.annotations.push({ type: "recorded_source_run_id", description: recording!.source_run_id });
  await expect(page.getByTestId("run-dashboard")).toHaveAttribute("data-is-replay", "true");
  await expect(page.getByText("REPLAY 4×", { exact: true })).toBeVisible();
  const log = page.getByTestId("event-log");
  const initialEvent = Number(await log.getAttribute("data-last-event-id") ?? "0");
  await expect.poll(async () => Number(await log.getAttribute("data-last-event-id") ?? "0"), { timeout: 30_000 }).toBeGreaterThan(initialEvent);
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", /^(done|failed|cancelled)$/, { timeout: 120_000 });
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "done");
  await expect(page.getByTestId("stage-current")).toHaveText("DONE");
  await expect(page.getByText("REPLAY 4×", { exact: true })).toBeVisible();

  const [runResponse, metricsResponse, bundleResponse, filesResponse] = await Promise.all([
    request.get(`/api/runs/${runId}`), request.get(`/api/runs/${runId}/metrics`),
    request.get(`/api/runs/${runId}/bundle.zip`), request.get(`/api/runs/${runId}/files`),
  ]);
  for (const response of [runResponse, metricsResponse, bundleResponse, filesResponse]) expect(response.ok()).toBeTruthy();
  const run = await runResponse.json() as PublicRun;
  expect(run.is_replay).toBe(true);
  expect(run.recording_id).toBe(recordingId);
  expect(run.replay_speed).toBe(4);
  const metrics = await metricsResponse.json() as Metric[];
  expect(metrics.length).toBe(recording!.flow_count);
  expect(metrics.length).toBeGreaterThanOrEqual(3);
  await expect(page.getByTestId("metrics-chart")).toHaveAttribute("data-point-count", String(metrics.length));
  await expect(page.getByTestId("metrics-chart").locator("svg.recharts-surface").first()).toBeVisible();
  const layout = page.getByTestId("layout-image");
  await expect(layout).toBeVisible();
  await expect(layout).toHaveAttribute("src", new RegExp(`/api/runs/${runId}/layout/`));
  await expect.poll(async () => layout.evaluate((node) => node instanceof HTMLImageElement && node.complete && node.naturalWidth > 0)).toBeTruthy();
  expect(bundleResponse.headers()["content-type"]).toContain("application/zip");
  expect(bundleResponse.headers()["content-disposition"]).toContain(`silicon-agent-${runId}.zip`);
  expect([...(await bundleResponse.body()).subarray(0, 4)]).toEqual([0x50, 0x4b, 0x03, 0x04]);

  // Exercise the recorded files and diffs after playback. This also runs from a
  // clean database and catches models being disposed while attached to Monaco.
  const files = await filesResponse.json() as Record<string, string>;
  const rtl = Object.keys(files).find((path) => path.startsWith("src/") && path.endsWith(".v"));
  const tests = Object.keys(files).find((path) => path.startsWith("test/") && path.endsWith(".py"));
  expect(rtl).toBeTruthy();
  expect(tests).toBeTruthy();
  const source = page.getByTestId("source-editor");
  const changes = page.getByRole("button", { name: "Changes", exact: true });
  for (let round = 0; round < 3; round++) {
    await page.getByRole("tab", { name: rtl!, exact: true }).click();
    if (await changes.getAttribute("aria-pressed") === "true") await changes.click();
    await changes.click();
    await expect(source.locator(".monaco-diff-editor").first()).toBeVisible();
    await page.getByRole("tab", { name: tests!, exact: true }).click();
    await expect(source.locator(".monaco-editor:visible .view-lines:visible").first()).toBeVisible();
    await changes.click();
    await expect(source.locator(".monaco-diff-editor").first()).toBeVisible();
    await changes.click();
    await expect(source.locator(".monaco-editor:visible .view-lines:visible").first()).toBeVisible();
  }
  expect(blockedMutations).toEqual([]);
  expect(pageErrors).toEqual([]);
});
