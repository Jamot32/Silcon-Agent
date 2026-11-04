import { readFileSync } from "node:fs";
import { expect, test, type Locator, type Page } from "@playwright/test";
import type { LayoutQuestion, LayoutRegionInput, Metric, PublicRun } from "../lib/api";

const recording = JSON.parse(readFileSync(new URL("../../demo_recordings/uart-repair/recording.json", import.meta.url), "utf8")) as {
  run: PublicRun; metrics: Metric[]; files: Record<string, string>; layouts: Record<string, string>;
};
const id = recording.run.id, tag = recording.run.best_run_tag!;
const png = readFileSync(new URL(`../../demo_recordings/uart-repair/${recording.layouts[tag]}`, import.meta.url));
const imageWidth = png.readUInt32BE(16), imageHeight = png.readUInt32BE(20);
const keyboardBounds = { x0: 0.1, y0: 0.2, x1: 0.6, y1: 0.8 };

function questionJob(selection: LayoutRegionInput, question = "Explain this selected region."): LayoutQuestion {
  const bounds = selection.bounds;
  return { id: "mock-layout-question", run_id: id, status: "pending", question,
    region: { ...selection, image_sha256: "a".repeat(64), image_width: imageWidth, image_height: imageHeight,
      coordinate_space: "image_normalized_top_left", pixel_bounds: { x0: Math.floor(bounds.x0 * imageWidth), y0: Math.floor(bounds.y0 * imageHeight), x1: Math.ceil(bounds.x1 * imageWidth), y1: Math.ceil(bounds.y1 * imageHeight) } },
    answer: null, error: null, provider: null, model: null, input_tokens: 0, output_tokens: 0, cost_usd: null };
}

async function serve(page: Page) {
  const state = { run: { ...recording.run }, mutations: [] as { path: string; body: unknown }[], history: [] as LayoutQuestion[], job: null as LayoutQuestion | null, polls: 0 };
  // Every API call stays in the fixture. Selecting, asking, and submitting cannot spend model/EDA calls.
  await page.route("**/api/**", async (route) => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() === "POST") {
      const body = request.postData() ? request.postDataJSON() : null;
      state.mutations.push({ path, body });
      if (path === `/api/runs/${id}/layout-questions`) {
        state.job = questionJob(body.selection, body.question); state.polls = 0;
        return route.fulfill({ json: state.job });
      }
      if (path.endsWith("/cancel")) {
        state.job = { ...state.job!, status: "running", cancel_requested: true };
        return route.fulfill({ json: state.job });
      }
      return route.fulfill({ status: 409, json: { detail: "Test queue is busy" } });
    }
    if (path === `/api/runs/${id}`) return route.fulfill({ json: state.run });
    if (path.endsWith("/files")) return route.fulfill({ json: recording.files });
    if (path.endsWith("/metrics")) return route.fulfill({ json: recording.metrics });
    if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: "" });
    if (path.includes("/layout/") && path.endsWith(".png")) return route.fulfill({ contentType: "image/png", body: png });
    if (path.endsWith("/layout-questions")) return route.fulfill({ json: state.history });
    if (path.includes("/layout-questions/")) {
      state.polls++;
      state.job = state.job!.cancel_requested ? { ...state.job!, status: "cancelled" } : state.polls > 1
        ? { ...state.job!, status: "done", answer: "Fixture answer: this image crop contains dense routing. Exact net identity requires additional evidence.", model: "mock-vision-model", input_tokens: 100, output_tokens: 25 }
        : { ...state.job!, status: "running" };
      return route.fulfill({ json: state.job });
    }
    return route.fulfill({ json: [] });
  });
  return state;
}

async function contentRect(image: Locator) {
  return image.evaluate((image: HTMLImageElement) => {
    const box = image.getBoundingClientRect();
    const scale = Math.min(box.width / image.naturalWidth, box.height / image.naturalHeight);
    const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
    return { x: box.x + (box.width - width) / 2, y: box.y + (box.height - height) / 2, width, height };
  });
}
async function selectWithPointer(page: Page, bounds = { x0: 0.2, y0: 0.3, x1: 0.7, y1: 0.8 }) {
  const image = page.getByTestId("result-layout-image");
  await image.locator("..").scrollIntoViewIfNeeded();
  const rect = await contentRect(image);
  await page.mouse.move(rect.x + bounds.x0 * rect.width, rect.y + bounds.y0 * rect.height);
  await page.mouse.down();
  await page.mouse.move(rect.x + bounds.x1 * rect.width, rect.y + bounds.y1 * rect.height, { steps: 5 });
  await page.mouse.up();
  const overlay = await page.getByTestId("layout-region-overlay").boundingBox();
  expect(overlay!.x).toBeCloseTo(rect.x + bounds.x0 * rect.width, 0);
  expect(overlay!.y).toBeCloseTo(rect.y + bounds.y0 * rect.height, 0);
  expect(overlay!.width).toBeCloseTo((bounds.x1 - bounds.x0) * rect.width, 0);
  expect(overlay!.height).toBeCloseTo((bounds.y1 - bounds.y0) * rect.height, 0);
  return bounds;
}
async function enterBounds(page: Page) {
  await page.getByText("Enter region bounds", { exact: true }).click();
  for (const [label, value] of [["Left (%)", "10"], ["Top (%)", "20"], ["Right (%)", "60"], ["Bottom (%)", "80"]]) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Apply bounds", exact: true }).click();
}
async function expectCrop(page: Page, bounds: LayoutRegionInput["bounds"]) {
  const crop = (await page.getByRole("img", { name: "Selected layout region", exact: true }).getAttribute("viewBox"))!.split(" ").map(Number);
  for (const [index, value] of [bounds.x0 * imageWidth, bounds.y0 * imageHeight, (bounds.x1 - bounds.x0) * imageWidth, (bounds.y1 - bounds.y0) * imageHeight].entries()) expect(crop[index]).toBeCloseTo(value, 0);
}

test("pointer rectangles ignore letterboxes and keep image coordinates after zoom and pan", async ({ page }) => {
  const state = await serve(page);
  await page.goto(`/runs/${id}/result`);
  await page.getByRole("button", { name: "Select region", exact: true }).click();
  const image = page.getByTestId("result-layout-image"), frame = image.locator("..");
  await frame.scrollIntoViewIfNeeded();
  const rect = await contentRect(image), box = (await frame.boundingBox())!;
  expect(rect.x - box.x).toBeGreaterThan(30);
  await page.mouse.move(box.x + 15, rect.y + rect.height / 2);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
  await page.mouse.up();
  await expect(page.getByTestId("layout-region-overlay")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ask about region", exact: true })).toBeDisabled();
  const bounds = await selectWithPointer(page);
  await page.getByRole("button", { name: "Ask about region", exact: true }).click();
  await expectCrop(page, bounds);
  expect(state.mutations).toEqual([]);
  await page.getByTestId("layout-region-inspector").getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.getByRole("button", { name: "Ask about region", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Pan", exact: true }).click();
  await page.getByRole("button", { name: "Zoom in layout", exact: true }).click({ clickCount: 2 });
  await frame.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowUp");
  await expect(image).toHaveAttribute("style", /translate\(40px, -40px\) scale\(1.5625\)/);
  await page.getByRole("button", { name: "Select region", exact: true }).click();
  const zoomed = await selectWithPointer(page, { x0: 0.4, y0: 0.4, x1: 0.6, y1: 0.6 });
  await page.getByRole("button", { name: "Ask about region", exact: true }).click();
  await expectCrop(page, zoomed);
  expect(state.mutations).toEqual([]);
});

test("phone keyboard bounds ask the exact region, poll its answer, and prepare a change without auto-building", async ({ page }) => {
  const state = await serve(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/runs/${id}/result`);
  await page.getByRole("button", { name: "Select region", exact: true }).click();
  await enterBounds(page);
  await page.getByLabel("Left (%)", { exact: true }).fill("80");
  await expect(page.getByRole("button", { name: "Ask about region", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Apply bounds", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Left must be less than right" })).toBeVisible();
  await page.getByLabel("Left (%)", { exact: true }).fill("10");
  await page.getByLabel("Left (%)", { exact: true }).press("Enter");
  await page.setViewportSize({ width: 320, height: 844 });
  const frame = page.getByRole("group", { name: "Layout image", exact: true });
  await frame.scrollIntoViewIfNeeded();
  const rect = await contentRect(page.getByTestId("result-layout-image"));
  const overlay = (await page.getByTestId("layout-region-overlay").boundingBox())!;
  expect(overlay.x).toBeCloseTo(rect.x + rect.width * keyboardBounds.x0, 0);
  expect(overlay.y).toBeCloseTo(rect.y + rect.height * keyboardBounds.y0, 0);
  expect(overlay.width).toBeCloseTo(rect.width * (keyboardBounds.x1 - keyboardBounds.x0), 0);
  expect(overlay.height).toBeCloseTo(rect.height * (keyboardBounds.y1 - keyboardBounds.y0), 0);
  expect(await page.locator("html").evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: test.info().outputPath("selection-mobile.png"), animations: "disabled" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Ask about region", exact: true }).click();
  const inspector = page.getByTestId("layout-region-inspector");
  await expectCrop(page, keyboardBounds);
  expect(state.mutations).toEqual([]);
  await inspector.getByLabel("What would you like to know?", { exact: true }).fill("Explain this selected region.");
  await inspector.getByRole("button", { name: "Ask about this region", exact: true }).click();
  await expect(inspector.getByRole("region", { name: "Agent answer" })).toContainText("Fixture answer: this image crop contains dense routing.");
  expect(state.polls).toBe(2);
  expect(state.mutations).toEqual([{ path: `/api/runs/${id}/layout-questions`, body: { selection: { run_tag: tag, bounds: keyboardBounds }, question: "Explain this selected region." } }]);
  expect(await inspector.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: test.info().outputPath("region-answer-mobile.png"), animations: "disabled" });
  await inspector.getByRole("tab", { name: "Request a change", exact: true }).click();
  const change = "Investigate routing concentration in this area and reduce it while preserving behavior.";
  await inspector.getByLabel("What should change in this region?", { exact: true }).fill(change);
  await inspector.getByRole("button", { name: "Prepare region change", exact: true }).click();
  const draft = page.getByRole("dialog", { name: "Continue this design", exact: true });
  await expect(draft).toBeVisible();
  await expect(draft.getByRole("button", { name: "Fix a problem", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(draft.getByLabel("What should change?", { exact: true })).toHaveValue(change);
  await expect(draft.getByTestId("revision-layout-region")).toContainText(tag);
  expect(state.mutations).toHaveLength(1);
  expect(await draft.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: test.info().outputPath("region-change-mobile.png"), animations: "disabled" });
  await draft.getByTestId("revise-submit").click();
  await expect(draft.getByRole("alert")).toContainText("Test queue is busy");
  expect(state.mutations).toHaveLength(2);
  expect(state.mutations[1]).toMatchObject({ path: "/api/runs", body: { parent_run_id: id, revision_intent: "fix", follow_up: change,
    layout_region: { run_tag: tag, bounds: keyboardBounds, expected_image_sha256: "a".repeat(64) } } });
  await draft.getByRole("button", { name: "Close", exact: true }).click();
  await expect(inspector.getByRole("button", { name: "Prepare region change", exact: true })).toBeFocused();
});

test("touch drag selects the visible image without scrolling the page or starting a job", async ({ browser }) => {
  const context = await browser.newContext({ hasTouch: true, viewport: { width: 390, height: 844 } });
  const page = await context.newPage(), state = await serve(page);
  await page.goto(`${test.info().project.use.baseURL}/runs/${id}/result`);
  await page.getByRole("button", { name: "Select region", exact: true }).click();
  await page.getByRole("group", { name: "Layout image", exact: true }).scrollIntoViewIfNeeded();
  const rect = await contentRect(page.getByTestId("result-layout-image"));
  const y = await page.evaluate(() => window.scrollY);
  const session = await context.newCDPSession(page);
  const point = (x: number, y: number) => ({ x: rect.x + rect.width * x, y: rect.y + rect.height * y, radiusX: 2, radiusY: 2, force: 1, id: 1 });
  await session.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [point(0.25, 0.3)] });
  await session.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [point(0.65, 0.7)] });
  await session.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await expect(page.getByTestId("layout-region-overlay")).toBeVisible();
  expect(await page.evaluate(() => window.scrollY)).toBe(y);
  await page.getByRole("button", { name: "Ask about region", exact: true }).click();
  await expectCrop(page, { x0: 0.25, y0: 0.3, x1: 0.65, y1: 0.7 });
  expect(state.mutations).toEqual([]);
  await context.close();
});

test("a question pending for another region can be stopped before asking about the new selection", async ({ page }) => {
  const state = await serve(page);
  state.job = questionJob({ run_tag: tag, bounds: { x0: 0, y0: 0, x1: 0.2, y1: 0.2 } }, "An earlier region question");
  state.history = [state.job];
  await page.goto(`/runs/${id}/result`);
  await page.getByRole("button", { name: "Select region", exact: true }).click();
  await enterBounds(page);
  await page.getByRole("button", { name: "Ask about region", exact: true }).click();
  const inspector = page.getByTestId("layout-region-inspector");
  await expect(inspector).toContainText("A question for another region is still running: An earlier region question");
  await expect(inspector.getByLabel("What would you like to know?", { exact: true })).toBeDisabled();
  await inspector.getByRole("button", { name: "Stop answer", exact: true }).click();
  await expect(inspector.getByRole("button", { name: "Stopping…", exact: true })).toBeDisabled();
  await expect(inspector.getByLabel("What would you like to know?", { exact: true })).toBeEnabled();
  expect(state.mutations).toEqual([{ path: `/api/runs/${id}/layout-questions/mock-layout-question/cancel`, body: null }]);
  await inspector.getByLabel("What would you like to know?", { exact: true }).fill("Explain the new selection.");
  await inspector.getByRole("button", { name: "Ask about this region", exact: true }).click();
  expect(state.mutations[1]).toMatchObject({ body: { selection: { run_tag: tag, bounds: keyboardBounds }, question: "Explain the new selection." } });
});

test("a newly selected physical run clears the old region and closes its inspector", async ({ page }) => {
  const state = await serve(page);
  await page.addInitScript(() => {
    class RunEvents extends EventTarget {
      constructor() { super(); Object.assign(window, { testRunEvents: this }); }
      close() {}
    }
    Object.assign(window, { EventSource: RunEvents });
  });
  await page.goto(`/runs/${id}`);
  await page.getByRole("button", { name: "Select region", exact: true }).click();
  await enterBounds(page);
  await page.getByRole("button", { name: "Ask about region", exact: true }).click();
  await expect(page.getByTestId("layout-region-inspector")).toBeVisible();
  state.run.best_run_tag = Object.keys(recording.layouts).find((value) => value !== tag)!;
  await page.evaluate((runTag) => {
    const source = (window as unknown as { testRunEvents: EventTarget }).testRunEvents;
    source.dispatchEvent(new MessageEvent("layout_rendered", { data: JSON.stringify({ id: 1, ts: new Date().toISOString(), type: "layout_rendered", payload: { run_tag: runTag, image_url: "new-layout.png" } }) }));
  }, state.run.best_run_tag);
  await expect(page.getByTestId("layout-image")).toHaveAttribute("src", new RegExp(state.run.best_run_tag));
  await expect(page.getByTestId("layout-region-inspector")).toHaveCount(0);
  await expect(page.getByTestId("layout-region-overlay")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Select region", exact: true })).toHaveAttribute("aria-pressed", "false");
  expect(state.mutations).toEqual([]);
});
