import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import type { Metric, PublicRun } from "../lib/api";

// Actual measured counter variants provide the baseline and revised result. All API requests
// are intercepted; these checks never queue a model or physical-design build.
const recording = JSON.parse(readFileSync(new URL("../../demo_recordings/counter-improvement/recording.json", import.meta.url), "utf8")) as {
  run: PublicRun; events: { type: string; payload: { run_tag: string; flow_index: number; metrics: Metric } }[];
};
const metrics = recording.events.filter((event) => event.type === "metric_recorded").map(({ payload }) => ({ ...payload.metrics, run_tag: payload.run_tag, flow_index: payload.flow_index }));
const PARENT = "c".repeat(32), CHILD = "d".repeat(32);
const parent: PublicRun = { ...recording.run, id: PARENT, status: "done", best_run_tag: metrics[0].run_tag, parent_run_id: null, carried_files: [], targets: { clock_mhz: 50, max_area_um2: 1100 } };
const child: PublicRun = { ...recording.run, id: CHILD, status: "done", parent_run_id: PARENT, carried_files: [], targets: { clock_mhz: 50, max_area_um2: 900 } };

async function serve(page: Page, options: { parentMetrics?: Metric[]; child?: PublicRun; childMetrics?: Metric[]; failParent?: boolean } = {}) {
  let parentUnavailable = options.failParent ?? false;
  await page.route("**/api/**", (route) => {
    if (route.request().method() !== "GET") return route.abort("blockedbyclient");
    const path = new URL(route.request().url()).pathname;
    if (path === `/api/runs/${PARENT}`) {
      if (parentUnavailable) return route.fulfill({ status: 503, json: { detail: "Parent temporarily unavailable" } });
      return route.fulfill({ json: parent });
    }
    if (path === `/api/runs/${CHILD}`) return route.fulfill({ json: options.child ?? child });
    if (path === `/api/runs/${PARENT}/metrics`) return route.fulfill({ json: options.parentMetrics ?? metrics });
    if (path === `/api/runs/${CHILD}/metrics`) return route.fulfill({ json: options.childMetrics ?? metrics });
    if (path.endsWith("/files")) return route.fulfill({ json: {} });
    if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: "" });
    if (path.includes("/layout/")) {
      const tag = path.split("/").at(-1);
      return route.fulfill({ contentType: "image/png", body: readFileSync(new URL(`../../demo_recordings/counter-improvement/layouts/${tag}`, import.meta.url)) });
    }
    return route.fulfill({ json: [] });
  });
  return { restoreParent: () => { parentUnavailable = false; } };
}

test("revision comparison uses chosen variants, signed deltas and each result’s targets on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 812 });
  await serve(page);
  await page.goto(`/runs/${CHILD}/result`);
  const comparison = page.getByTestId("revision-comparison");
  await expect(comparison.getByRole("link", { name: "Parent run cccccccc" })).toHaveAttribute("href", `/runs/${PARENT}/result`);
  const area = comparison.getByRole("row", { name: /^Area/ });
  await expect(area).toContainText("1,097.3 µm²");
  await expect(area).toContainText("980.941 µm²");
  await expect(area).toContainText("Target ≤ 1,100 µm² · Met");
  await expect(area).toContainText("Target ≤ 900 µm² · Missed");
  await expect(comparison.getByTestId("revision-delta-area_um2")).toHaveText("-116.359 µm²-10.6%");
  await expect(comparison.getByTestId("revision-delta-clock_mhz")).toHaveText("0 MHz0%");
  await expect(comparison).toContainText("nonnegative WNS confirms timing");
  await expect(comparison).toContainText(`Parent selected flow: ${metrics[0].run_tag}`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await comparison.locator('[data-slot="table-container"]').evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
});

for (const scenario of ["parent missing selected metric", "revision missing selected metric", "failed revision", "no selected revision"] as const) {
  test(`${scenario} reports unavailable without inventing a change`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 812 });
    await serve(page, {
      parentMetrics: scenario === "parent missing selected metric" ? metrics.slice(1) : metrics,
      childMetrics: scenario === "revision missing selected metric" ? metrics.slice(0, 1) : metrics,
      child: scenario === "failed revision" ? { ...child, status: "failed" } : scenario === "no selected revision" ? { ...child, best_run_tag: null } : child,
    });
    await page.goto(`/runs/${CHILD}/result`);
    const comparison = page.getByTestId("revision-comparison");
    await expect(comparison.getByTestId("revision-delta-area_um2")).toHaveText("No data");
    await expect(comparison.getByTestId("revision-delta-clock_mhz")).toHaveText("No data");
    await expect(comparison.getByTestId(scenario.startsWith("parent") ? "parent-result-unavailable" : "revision-result-unavailable")).toBeVisible();
    expect(await comparison.locator('[data-slot="table-container"]').evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
  });
}

test("parent fetch failure is visible and retry loads the comparison", async ({ page }) => {
  const { restoreParent } = await serve(page, { failParent: true });
  await page.goto(`/runs/${CHILD}/result`);
  const comparison = page.getByTestId("revision-comparison");
  await expect(comparison.getByRole("alert")).toContainText("Parent temporarily unavailable");
  await expect(comparison.getByTestId("revision-comparison-table")).toHaveCount(0);
  restoreParent();
  await comparison.getByRole("button", { name: "Retry comparison" }).click();
  await expect(comparison.getByTestId("revision-delta-area_um2")).toHaveText("-116.359 µm²-10.6%");
});
