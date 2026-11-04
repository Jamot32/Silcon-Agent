import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import type { CreateRunInput, DesignSpec, PublicRun } from "../lib/api";

// The committed counter recording supplies a real model-drafted DesignSpec. Every API call is fulfilled or
// intercepted here, so nothing queues a real model/EDA build.
const recording = JSON.parse(readFileSync(new URL("../../demo_recordings/counter-improvement/recording.json", import.meta.url), "utf8")) as { run: PublicRun };
const RUN = "c".repeat(32);
const draft = recording.run.design_spec as DesignSpec;
const build = { optimize: true, max_flow_runs: 6, max_repair_loops: 5, initial_flow: {} };
const waiting: PublicRun = { ...recording.run, id: RUN, status: "running", stage: "REVIEW", is_replay: false, parent_run_id: null, carried_files: [], review_requested: true, review_submitted: false };
const events = [
  { type: "stage_changed", payload: { stage: "SPEC", goal: "Return only DesignSpec JSON", previous_ok: null } },
  { type: "stage_changed", payload: { stage: "REVIEW", goal: "Wait for the user to review", previous_ok: true, design_spec: draft } },
  { type: "note", payload: { stage: "REVIEW", text: "Waiting for your review.", review_request: { design_spec: draft, build, locked: [] } } },
];
const stream = events.map((event, index) => `id: ${index + 1}\nevent: ${event.type}\ndata: ${JSON.stringify({ id: index + 1, ts: "2026-11-01T00:00:00Z", ...event })}\n\n`).join("");

async function serve(page: Page, onReview: (body: { design_spec: DesignSpec; build: typeof build }) => { status: number; json: object }) {
  let run = waiting;
  await page.route("**/api/**", (route) => ["GET", "HEAD"].includes(route.request().method()) ? route.continue() : route.abort("blockedbyclient"));
  await page.route(`**/api/runs/${RUN}`, (route) => route.fulfill({ json: run }));
  await page.route(`**/api/runs/${RUN}/files`, (route) => route.fulfill({ json: {} }));
  await page.route(`**/api/runs/${RUN}/metrics`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/runs/${RUN}/events*`, (route) => route.fulfill({ contentType: "text/event-stream", body: stream }));
  await page.route(`**/api/runs/${RUN}/review`, (route) => {
    const { status, json } = onReview(route.request().postDataJSON());
    if (status === 200) run = { ...run, review_submitted: true };
    return route.fulfill({ status, json });
  });
}

test("expert mode is off by default and, once on, asks for a review before RTL", async ({ page }) => {
  const requests: CreateRunInput[] = [];
  await page.route("**/api/**", (route) => ["GET", "HEAD"].includes(route.request().method()) ? route.continue() : route.abort("blockedbyclient"));
  await page.route("**/api/runs", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    requests.push(route.request().postDataJSON() as CreateRunInput);
    return route.fulfill({ status: 409, json: { detail: "One chip build is already active. Wait for it or cancel it first." } });
  });
  await page.goto("/");
  await expect(page.getByLabel("Review spec before RTL")).toHaveCount(0);
  await page.goto("/settings");
  await expect(page.getByRole("checkbox", { name: "Expert mode" })).not.toBeChecked();
  await page.getByRole("checkbox", { name: "Expert mode" }).click();
  await page.getByRole("button", { name: "Save defaults" }).click();
  await page.goto("/");
  await expect(page.getByRole("checkbox", { name: "Review spec before RTL" })).toBeChecked();
  await page.getByRole("button", { name: "Build my chip" }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].review).toBe(true);
});

test("the review form edits every spec field and build setting, and reports field errors", async ({ page }) => {
  const reviews: { design_spec: DesignSpec; build: typeof build }[] = [];
  await serve(page, (body) => {
    reviews.push(body);
    return reviews.length === 1
      ? { status: 422, json: { detail: [{ loc: ["body", "design_spec", "test_plan"], msg: "List should have at least 4 items after validation, not 3" }] } }
      : { status: 200, json: { ...waiting, review_submitted: true } };
  });
  await page.goto(`/runs/${RUN}`);
  const form = page.getByTestId("spec-review");
  await expect(form).toHaveAttribute("data-state", "open");
  await expect(page.getByTestId("stage-timeline")).toContainText("REVIEW");
  await expect(form.getByLabel("Top module")).toHaveValue(draft.top_module);
  await expect(form.getByLabel("Port 1 name", { exact: true })).toHaveValue(draft.ports[0].name);
  await form.getByRole("button", { name: "Add behavior line" }).click();
  await form.getByLabel(`Behavior ${draft.behavior.length + 1}`, { exact: true }).fill("Count holds while enable is low.");
  await form.getByLabel("Flow attempts (1–6)").fill("3");
  // Enter in a one-line field must not approve: approval starts paid work.
  await form.getByLabel("Flow attempts (1–6)").press("Enter");
  await expect(page.getByTestId("agent-now")).toContainText("Waiting for your spec review");
  expect(reviews).toHaveLength(0);
  await form.getByLabel("Synthesis strategy").selectOption("DELAY 1");
  await form.getByLabel("Placement density (%)").fill("55");
  await form.getByLabel("Let the PPA optimizer compare variants after the first layout").click();
  await form.getByLabel("Clock (MHz)").fill("40");
  await form.getByTestId("approve-review").click();
  await expect(form.getByRole("alert")).toContainText("design_spec.test_plan: List should have at least 4 items");
  await form.getByTestId("approve-review").click();
  await expect(form).toHaveAttribute("data-state", "submitted");
  expect(reviews[1]).toEqual({
    design_spec: { ...draft, behavior: [...draft.behavior, "Count holds while enable is low."], targets: { ...draft.targets, clock_mhz: 40 } },
    build: { optimize: false, max_flow_runs: 3, max_repair_loops: 5, initial_flow: { SYNTH_STRATEGY: "DELAY 1", PL_TARGET_DENSITY_PCT: 55 } },
  });
});
