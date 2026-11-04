import { readFileSync } from "node:fs";
import { expect, test, type Locator, type Page } from "@playwright/test";
import type { Metric, PublicRun, RunEvent } from "../lib/api";

// Reuse measured simulator/EDA evidence; all requests are intercepted and no builds are queued.
const recording = JSON.parse(readFileSync(new URL("../../demo_recordings/uart-repair/recording.json", import.meta.url), "utf8")) as {
  run: PublicRun; events: RunEvent[]; metrics: Metric[]; files: Record<string, string>; layouts: Record<string, string>;
};
const id = recording.run.id;
async function serve(page: Page, run = recording.run, events = recording.events, metrics = recording.metrics) {
  await page.route("**/api/**", (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/runs/${id}`, (route) => route.fulfill({ json: run }));
  await page.route(`**/api/runs/${id}/files`, (route) => route.fulfill({ json: recording.files }));
  await page.route(`**/api/runs/${id}/metrics`, (route) => route.fulfill({ json: metrics }));
  await page.route(`**/api/runs/${id}/events*`, (route) => route.fulfill({ contentType: "text/event-stream", body: events.map((event) => `id: ${event.id}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("") }));
  for (const [tag, path] of Object.entries(recording.layouts)) {
    await page.route(`**/api/runs/${id}/layout/${tag}.png`, (route) => route.fulfill({ contentType: "image/png", body: readFileSync(new URL(`../../demo_recordings/uart-repair/${path}`, import.meta.url)) }));
  }
}

async function noHorizontalScroll(locator: Locator) {
  expect(await locator.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
}

test("result measurements and the fitted layout stay fully visible on a phone", async ({ page }) => {
  await serve(page);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`/runs/${id}/result`);
    const measurements = page.getByRole("region", { name: "Targets and measurements" });
    await expect(measurements).toBeVisible();
    for (const table of await measurements.locator('[data-slot="table-container"]:visible').all()) await noHorizontalScroll(table);
    await noHorizontalScroll(page.locator("html"));
    const image = page.getByTestId("result-layout-image");
    await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
    const fits = () => image.evaluate((node) => {
      const image = node.getBoundingClientRect(), frame = node.parentElement!.getBoundingClientRect();
      return image.left >= frame.left && image.right <= frame.right && image.top >= frame.top && image.bottom <= frame.bottom;
    });
    await expect.poll(fits).toBe(true);
    await page.getByRole("button", { name: "Zoom in layout" }).click();
    await expect(image).toHaveAttribute("style", /scale\(1.25\)/);
    const frame = await image.locator("..").boundingBox();
    await page.mouse.move(frame!.x + 80, frame!.y + 80);
    await page.mouse.down();
    await page.mouse.move(frame!.x + 100, frame!.y + 95);
    await page.mouse.up();
    await expect(image).toHaveAttribute("style", /translate\(20px, 15px\)/);
    await page.getByRole("button", { name: "Fit", exact: true }).click();
    await expect.poll(fits).toBe(true);
    await expect(image).toHaveAttribute("style", /translate\(0px, 0px\) scale\(1\)/);
    await expect(page.getByTestId("revise-run")).toBeVisible();
  }
});

test("laptop dashboard gives source and log room and keeps best-run values in view", async ({ page }) => {
  await serve(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`/runs/${id}`);
  const source = page.getByRole("region", { name: "Design source code" });
  await expect(source).toBeVisible();
  expect((await source.boundingBox())!.width).toBeGreaterThan(400);
  await page.setViewportSize({ width: 320, height: 844 });
  const best = page.getByRole("region", { name: "Best measured physical run" });
  await expect(best).toContainText("LVS");
  for (const table of await best.locator('[data-slot="table-container"]:visible').all()) await noHorizontalScroll(table);
  await noHorizontalScroll(best);
  await noHorizontalScroll(page.locator("html"));
});

test("long design and test names wrap, and test messages open with the keyboard", async ({ page }) => {
  const name = "uart_transmitter_with_programmable_baud_and_synchronous_reset";
  const testName = `test_${name}_reset_while_transmitting`;
  const events = recording.events.map((event) => event.type === "test_result" ? { ...event, payload: { ...event.payload, cases: Array.from({ length: 7 }, (_, index) => ({ test: `${testName}_${index}`, ok: true, message: "Reset returned the transmitter to idle." })) } } : event);
  await serve(page, { ...recording.run, design_spec: { ...recording.run.design_spec!, top_module: name } }, events);
  await page.setViewportSize({ width: 320, height: 844 });
  for (const suffix of ["", "/result"]) {
    await page.goto(`/runs/${id}${suffix}`);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(name);
    await noHorizontalScroll(page.locator("html"));
    if (!suffix) {
      const summary = page.getByTestId("test-results").locator("summary").filter({ hasText: testName }).first();
      await summary.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByText("Reset returned the transmitter to idle.", { exact: true }).first()).toBeVisible();
      await noHorizontalScroll(page.getByTestId("test-results"));
      await page.setViewportSize({ width: 1536, height: 960 });
      const inspection = page.getByRole("region", { name: "Verification and Metrics" });
      expect(await inspection.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(1);
      await page.setViewportSize({ width: 320, height: 844 });
    }
  }
});

test("a selected layout never borrows measurements or signoff from another physical run", async ({ page }) => {
  const metrics = recording.metrics.filter((metric) => metric.run_tag !== recording.run.best_run_tag);
  const events = recording.events.filter((event) => event.type !== "metric_recorded");
  await serve(page, recording.run, events, metrics);
  await page.goto(`/runs/${id}/result`);
  await expect(page.getByRole("alert").filter({ hasText: "Measurements for the selected physical run" })).toBeVisible();
  await expect(page.getByTestId("result-targets").getByRole("row", { name: /^Clock/ })).toContainText("Unknown");
  await expect(page.getByTestId("result-signoff")).toContainText(/DRC\s*unknown/);
  await expect(page.getByTestId("result-signoff")).toContainText(/LVS\s*unknown/);
  await expect(page.getByTestId("result-layout-image")).toHaveAttribute("src", new RegExp(recording.run.best_run_tag!));
});
