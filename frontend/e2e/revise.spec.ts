import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import type { CreateRunInput, PublicRun } from "../lib/api";

// The committed repair recording supplies a real finished run and its real final sources. Every API call is
// fulfilled here, and the build request is intercepted, so these checks never queue a real model/EDA build.
const recording = JSON.parse(readFileSync(new URL("../../demo_recordings/uart-repair/recording.json", import.meta.url), "utf8")) as {
  run: PublicRun; events: { type: string; payload: { path?: string; content?: string } }[];
};
const PARENT = "a".repeat(32), CHILD = "b".repeat(32);
const parent: PublicRun = { ...recording.run, id: PARENT, status: "done", is_replay: false, parent_run_id: null, carried_files: [] };
const files = Object.fromEntries(recording.events.flatMap((event) => event.type === "file_written" && event.payload.path && event.payload.content !== undefined ? [[event.payload.path, event.payload.content]] : []));

// Server-sent events exactly as the API frames them.
const stream = (events: object[]) => events.map((event, index) => `id: ${index + 1}\nevent: ${(event as { type: string }).type}\ndata: ${JSON.stringify({ id: index + 1, ts: "2026-11-01T00:00:00Z", ...event })}\n\n`).join("");

async function serve(page: Page, onCreate: (body: CreateRunInput) => { status: number; json: object }, child: { status: string; events: object[] } = { status: "pending", events: [] }) {
  await page.route("**/api/**", (route) => ["GET", "HEAD"].includes(route.request().method()) ? route.continue() : route.abort("blockedbyclient"));
  for (const run of [parent, { ...parent, id: CHILD, status: child.status, stage: "SPEC", parent_run_id: PARENT, carried_files: ["src/uart_tx.v"], starter_id: null }]) {
    await page.route(`**/api/runs/${run.id}`, (route) => route.fulfill({ json: run }));
    await page.route(`**/api/runs/${run.id}/files`, (route) => route.fulfill({ json: run.id === PARENT ? files : {} }));
    await page.route(`**/api/runs/${run.id}/metrics`, (route) => route.fulfill({ json: [] }));
    await page.route(`**/api/runs/${run.id}/events*`, (route) => route.fulfill({ contentType: "text/event-stream", body: run.id === CHILD ? stream(child.events) : "" }));
  }
  await page.route("**/api/runs", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const { status, json } = onCreate(route.request().postDataJSON() as CreateRunInput);
    return route.fulfill({ status, json });
  });
}

test("an edited request starts a linked revision from the run's RTL", async ({ page }) => {
  const requests: CreateRunInput[] = [];
  await serve(page, (body) => { requests.push(body); return { status: 202, json: { run_id: CHILD } }; });
  await page.goto(`/runs/${PARENT}`);
  await page.getByTestId("revise-run").click();
  const request = page.getByLabel("Request");
  await expect(request).toHaveValue(parent.spec_text);
  await expect(page.getByRole("checkbox", { name: "Start from this run's RTL" })).toBeChecked();
  await expect(page.getByRole("dialog")).toContainText("loads the selected design from its bundle");
  await request.fill(`${parent.spec_text} Use BAUD_DIV 8 instead of 4.`);
  await page.getByTestId("revise-submit").click();
  await expect(page).toHaveURL(new RegExp(`/runs/${CHILD}$`));
  expect(requests).toEqual([{ spec_text: `${parent.spec_text} Use BAUD_DIV 8 instead of 4.`, targets: parent.targets, parent_run_id: PARENT, reuse_design: true }]);
  const notice = page.getByTestId("revision-notice");
  await expect(notice).toContainText("Follows run aaaaaaaa.");
  // The child has no events yet: the notice must not claim a carry-over that has not happened.
  await expect(notice).toContainText("Will start from its RTL (src/uart_tx.v).");
  await expect(notice.getByRole("link", { name: "aaaaaaaa" })).toHaveAttribute("href", `/runs/${PARENT}`);
});

test("an untouched request runs again exactly and a busy queue is reported", async ({ page }) => {
  const requests: CreateRunInput[] = [];
  await serve(page, (body) => { requests.push(body); return { status: 409, json: { detail: "One chip build is already active. Wait for it or cancel it first." } }; });
  await page.goto(`/runs/${PARENT}/result`);
  await page.getByTestId("revise-run").click();
  await page.getByRole("checkbox", { name: "Start from this run's RTL" }).click();
  await expect(page.getByTestId("revise-submit")).toHaveText("Run again");
  await page.getByTestId("revise-submit").click();
  await expect(page.getByRole("alert").filter({ hasText: "One chip build is already active" })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/runs/${PARENT}/result$`));
  expect(requests).toEqual([{ spec_text: parent.spec_text.trim(), targets: parent.targets, parent_run_id: PARENT, reuse_design: false, preset_id: "uart", starter_id: "uart_off_by_one" }]);
});

test("the revision notice reports what the orchestrator actually did with the carried RTL", async ({ page }) => {
  const loaded = { type: "note", payload: { stage: "RTL", carry_over: "loaded", text: "Carried over the RTL of run aaaaaaaa." } };
  const skipped = { type: "note", payload: { stage: "RTL", carry_over: "skipped", text: "No RTL from run aaaaaaaa defines top module uart_rx; the RTL designer starts from scratch." } };
  for (const [status, events, text] of [
    ["running", [loaded], "Started from its RTL (src/uart_tx.v); tests are written fresh"],
    ["failed", [skipped], "Its RTL was not used. No RTL from run aaaaaaaa defines top module uart_rx"],
    ["cancelled", [], "Ended before its RTL (src/uart_tx.v) was loaded."],
  ] as const) {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await serve(page, () => ({ status: 500, json: {} }), { status, events: [...events] });
    await page.goto(`/runs/${CHILD}`);
    await expect(page.getByTestId("revision-notice")).toContainText(text);
  }
});
