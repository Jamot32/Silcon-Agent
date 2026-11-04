import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import type { Metric, PublicRun, RunEvent } from "../lib/api";
import type { FlowDetail } from "../lib/flow-inspection";

const recording = JSON.parse(readFileSync(new URL("../../demo_recordings/uart-optimization/recording.json", import.meta.url), "utf8")) as { run: PublicRun; metrics: Metric[]; events: RunEvent[]; files: Record<string, string> };
const id = recording.run.id;
const metric = recording.metrics[0];

async function serve(page: Page, events: RunEvent[], metrics = [metric]) {
  // No test may submit a real build or modify the running app.
  await page.route("**/api/**", (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/runs/${id}`, (route) => route.fulfill({ json: { ...recording.run, best_run_tag: null } }));
  await page.route(`**/api/runs/${id}/files`, (route) => route.fulfill({ json: recording.files }));
  await page.route(`**/api/runs/${id}/metrics`, (route) => route.fulfill({ json: metrics }));
  await page.route(`**/api/runs/${id}/events*`, (route) => route.fulfill({ contentType: "text/event-stream", body: events.map((event) => `id: ${event.id}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("") }));
}

const events: RunEvent[] = [
  { id: 1, ts: "2026-11-03T00:00:00Z", type: "stage_changed", payload: { stage: "FLOW" } },
  { id: 2, ts: "2026-11-03T00:00:01Z", type: "tool_finished", payload: { tool: "run_flow", tool_call_id: "same_id", result: { ok: false, run_tag: metric.run_tag, error: "Routed netlist verification failed", metrics: { ...metric } } } },
  { id: 3, ts: "2026-11-03T00:00:02Z", type: "tool_finished", payload: { tool: "run_flow", tool_call_id: "same_id", result: { ok: false, error: "Source is not verified; no physical run started" } } },
];

// Synthetic failure modes exercise UI behavior; PPA values come from the committed recording.
const detail: FlowDetail = {
  event_id: 2, tool_call_id: "same_id", run_tag: metric.run_tag, status: "failed", selected: false,
  is_replay: false, physical_flow_started: true,
  requested_config: { SYNTH_STRATEGY: "AREA 0", FP_CORE_UTIL: 45 },
  planned_config: { SYNTH_STRATEGY: "AREA 1", FP_CORE_UTIL: 45, PL_TARGET_DENSITY_PCT: 45 },
  applied_config: { SYNTH_STRATEGY: "AREA 2", FP_CORE_UTIL: 45, PL_TARGET_DENSITY_PCT: 40 },
  resolved_config: { SYNTH_STRATEGY: "DELAY 2", FP_CORE_UTIL: 40, PL_TARGET_DENSITY_PCT: 35, CLOCK_PERIOD: 10, DIE_AREA: [0, 0, 100, 100] },
  metrics: { ...metric, tns_ns: 0 }, diagnostic: { kind: "routed_netlist_mismatch", message: "Routed netlist verification failed" },
  signoff: { drc_ok: true, lvs_ok: true, drv_ok: false, gls_ok: false, checks: {
    setup_wns_ns: 0, hold_wns_ns: 0, setup_violations: 0, hold_violations: 0,
    max_slew_violations: 11, max_cap_violations: null, max_fanout_violations: null,
    antenna_violating_nets: null, antenna_violating_pins: null, violating_corners: { max_slew: ["ss_100C_1v60"] },
  } },
  provenance: { evidence_status: "verified", execution_id: "fixture-execution", image_id: "sha256:fixture",
    source_sha256: "a".repeat(64), input_sha256: "b".repeat(64), duration_seconds: 42, snapshot_available: true },
  reports: { log: { available: true, excerpt: "Recorded failure excerpt", truncated: true },
    timing: { available: false, excerpt: null, truncated: false }, area: { available: false, excerpt: null, truncated: false },
    power: { available: false, excerpt: null, truncated: false }, drc: { available: false, excerpt: null, truncated: false } },
  warnings: ["This test uses a synthetic failure scenario."],
};

test("a measured failure and a rejected preflight remain visible as separate failed attempts", async ({ page }) => {
  await serve(page, events);
  await page.goto(`/runs/${id}`);
  const cards = page.getByTestId("flow-comparison").getByRole("article");
  await expect(cards).toHaveCount(2);
  await expect(cards.first()).toHaveAttribute("data-status", "failed");
  await expect(cards.first()).toContainText("Failed · measurements available");
  await expect(cards.first()).toContainText("Routed netlist verification failed");
  await expect(cards.first()).toContainText("Area (µm²)");
  await expect(cards.last()).toContainText("no physical run recorded");
  await expect(cards.last()).toContainText("Source is not verified");
  await page.getByRole("tab", { name: "Each agent", exact: true }).click();
  await expect(page.getByTestId("flow-worker").first()).toContainText("Failed · measurements available");
  await expect(page.getByTestId("flow-worker").first()).toContainText("Routed netlist verification failed");
});

test("inspector uses the exact event and prepares only safe resolved settings without starting a build", async ({ page }) => {
  await serve(page, events);
  const selectors: string[] = [];
  await page.route(`**/api/runs/${id}/flow?*`, (route) => { selectors.push(new URL(route.request().url()).search); return route.fulfill({ json: detail }); });
  const submissions: unknown[] = [];
  await page.route("**/api/runs", (route) => {
    if (route.request().method() === "POST") { submissions.push(route.request().postDataJSON()); return route.fulfill({ status: 409, json: { detail: "Test queue is busy" } }); }
    return route.fulfill({ json: [] });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/runs/${id}`);
  await page.getByTestId("flow-comparison").getByRole("button", { name: "Inspect flow" }).first().click();
  const inspector = page.getByTestId("flow-inspector");
  await expect(inspector).toContainText("Recorded diagnosis · routed_netlist_mismatch");
  expect(selectors).toEqual(["?event_id=2"]);
  await expect(inspector.getByTestId("extended-signoff")).toContainText("Recorded signoff checks failed");
  await expect(inspector.getByTestId("extended-signoff")).toContainText(/Slew violations\s*11/);
  await page.screenshot({ path: test.info().outputPath("inspector-mobile.png"), animations: "disabled" });
  for (const name of ["Requested overrides", "Planned settings", "Applied configuration", "Resolved configuration"]) await inspector.locator("summary").filter({ hasText: name }).click();
  await expect(inspector).toContainText("AREA 0");
  await expect(inspector).toContainText("DELAY 2");
  await inspector.locator("summary").filter({ hasText: /^log report/ }).click();
  await expect(inspector).toContainText("Recorded failure excerpt");
  expect(await inspector.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await inspector.getByRole("button", { name: "Use settings in follow-up" }).click();
  await expect(page.getByRole("heading", { name: "Continue this design", exact: true })).toBeVisible();
  expect(submissions).toEqual([]);
  await expect(page.getByLabel("Initial synthesis strategy", { exact: true })).toHaveValue("DELAY 2");
  const draft = page.getByRole("dialog", { name: "Continue this design", exact: true });
  expect(await draft.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await page.getByLabel("Initial synthesis strategy", { exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Core utilization (%)", { exact: true })).toBeFocused();
  await page.screenshot({ path: test.info().outputPath("prepared-settings-mobile.png"), animations: "disabled" });
  await expect(page.getByLabel("Target clock (MHz)", { exact: true })).toHaveValue("50");
  await expect(page.getByLabel("What should change?", { exact: true })).toHaveValue(new RegExp(metric.run_tag));
  await page.getByTestId("revise-submit").click();
  await expect(page.getByRole("alert").filter({ hasText: "Test queue is busy" })).toBeVisible();
  expect(submissions).toHaveLength(1);
  expect(submissions[0]).toMatchObject({ parent_run_id: id, revision_intent: "optimize", build: { initial_flow: { SYNTH_STRATEGY: "DELAY 2", FP_CORE_UTIL: 40, PL_TARGET_DENSITY_PCT: 35 } } });
  expect(Object.keys((submissions[0] as { build: { initial_flow: object } }).build.initial_flow)).toHaveLength(3);
  await draft.getByRole("button", { name: "Close", exact: true }).click();
  await expect(inspector.getByRole("button", { name: "Use settings in follow-up" })).toBeFocused();
});

test("preflight inspection uses its own event and handles unavailable evidence and retry honestly", async ({ page }) => {
  await serve(page, events);
  let attempts = 0;
  const preflight = { ...detail, event_id: 3, run_tag: null, metrics: null, physical_flow_started: false,
    requested_config: null, planned_config: null, applied_config: null, resolved_config: null,
    diagnostic: { kind: "verification_required", message: "Source is not verified; no physical run started" } };
  await page.route(`**/api/runs/${id}/flow?event_id=3`, (route) => ++attempts === 1 ? route.fulfill({ status: 503, json: { detail: "Evidence temporarily unavailable" } }) : route.fulfill({ json: preflight }));
  await page.goto(`/runs/${id}`);
  await page.getByTestId("flow-comparison").getByRole("button", { name: "Inspect flow" }).last().click();
  const inspector = page.getByTestId("flow-inspector");
  await expect(inspector).toContainText("Evidence temporarily unavailable");
  await inspector.getByRole("button", { name: "Retry evidence" }).click();
  await expect(inspector).toContainText("Stopped before physical design started");
  await expect(inspector).toContainText("No measured PPA is available");
  await expect(inspector.getByRole("button", { name: "Use settings in follow-up" })).toHaveCount(0);
  await expect(inspector).toContainText("No reusable, valid engineering settings");
});

test("selected result shows extended signoff violations inline even when DRC and LVS are clean", async ({ page }) => {
  await serve(page, [], [metric]);
  await page.route(`**/api/runs/${id}`, (route) => route.fulfill({ json: { ...recording.run, best_run_tag: metric.run_tag } }));
  await page.route(`**/api/runs/${id}/flow?run_tag=${metric.run_tag}`, (route) => route.fulfill({ json: { ...detail, selected: true } }));
  await page.goto(`/runs/${id}/result`);
  const summary = page.getByTestId("selected-flow-checks");
  await expect(summary).toContainText("Recorded signoff checks failed");
  await expect(summary).toContainText(/Slew violations\s*11/);
  await expect(page.getByTestId("result-signoff")).toContainText("DRC and LVS are clean.");
  await expect(page.getByTestId("result-signoff")).not.toContainText("Block signoff is clean.");
  await summary.getByRole("button", { name: "Inspect selected flow" }).click();
  await expect(page.getByTestId("flow-inspector")).toContainText(metric.run_tag);
});

test("unverified integrity blocks settings reuse and missing checks remain unknown", async ({ page }) => {
  await serve(page, events);
  const unknown = { ...detail, status: "unknown", metrics: null, resolved_config: null,
    provenance: { ...detail.provenance, evidence_status: "invalid" },
    signoff: { drc_ok: null, lvs_ok: null, drv_ok: null, gls_ok: null,
      checks: { ...Object.fromEntries(Object.keys(detail.signoff.checks).map((key) => [key, null])), violating_corners: {} } },
  };
  await page.route(`**/api/runs/${id}/flow?*`, (route) => route.fulfill({ json: unknown }));
  await page.goto(`/runs/${id}`);
  await page.getByTestId("flow-comparison").getByRole("button", { name: "Inspect flow" }).first().click();
  const inspector = page.getByTestId("flow-inspector");
  await expect(inspector).toContainText("Outcome unknown");
  await expect(inspector).toContainText("failed its integrity check");
  await expect(inspector.getByTestId("extended-signoff")).toContainText("Unknown checks are not passes");
  await expect(inspector.getByRole("button", { name: "Use settings in follow-up" })).toHaveCount(0);
});

for (const [slack, outcome] of [[-0.01, "Recorded signoff checks failed"], [null, "Some signoff checks were not recorded"]] as const) {
  test(`hold WNS ${slack} cannot become a complete pass from zero violation counts`, async ({ page }) => {
    await serve(page, [], [metric]);
    await page.route(`**/api/runs/${id}`, (route) => route.fulfill({ json: { ...recording.run, best_run_tag: metric.run_tag } }));
    const response = { ...detail, status: "passed", signoff: { drc_ok: true, lvs_ok: true, drv_ok: true, gls_ok: true,
      checks: { ...Object.fromEntries(Object.keys(detail.signoff.checks).map((key) => [key, 0])), violating_corners: {}, hold_wns_ns: slack } } };
    await page.route(`**/api/runs/${id}/flow?*`, (route) => route.fulfill({ json: response }));
    await page.goto(`/runs/${id}/result`);
    const summary = page.getByTestId("selected-flow-checks");
    await expect(summary).toContainText(outcome);
    await expect(summary).not.toContainText("All listed signoff checks passed");
    if (slack !== null) await expect(summary.getByText("-0.01 ns", { exact: true })).toHaveClass(/text-destructive/);
  });
}
