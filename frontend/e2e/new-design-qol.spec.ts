import { expect, test, type Page } from "@playwright/test";

const draftKey = "silicon-agent.design-draft";
const health = { status: "degraded", llm_provider: "codex", milestone: "M11", checks: {
  database: { status: "ok", detail: "Database reachable" }, eda: { status: "ok", detail: "EDA tools ready" },
  llm: { status: "not_verified", detail: "Run the model smoke test" }, worker: { status: "not_verified", detail: "Start the host worker" },
} };

async function serve(page: Page, buildStatus = 409) {
  const requests: unknown[] = [];
  let healthCalls = 0;
  await page.route("**/api/**", (route) => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path === "/api/health") { healthCalls++; return route.fulfill({ json: health }); }
    if (path === "/api/settings") return route.fulfill({ json: { provider: "codex", model: "gpt-6.1-sol", reasoning_effort: null, max_calls: 50, max_tokens: null, budget_usd: 2 } });
    if (path === "/api/runs" && request.method() === "POST") {
      requests.push(request.postDataJSON());
      return route.fulfill({ status: buildStatus, json: buildStatus === 202 ? { run_id: "a".repeat(32) } : { detail: "Another build is active" } });
    }
    return route.fulfill({ json: [] });
  });
  return { requests, healthCalls: () => healthCalls };
}

test("a design draft survives reload with its clock and tile constraint", async ({ page }) => {
  await serve(page);
  await page.goto("/");
  await page.getByLabel("Describe your chip").fill("A custom 12-bit counter with synchronous reset.");
  await page.getByLabel("Target clock (MHz)").fill("62.5");
  await page.getByLabel("Fit in one Tiny Tapeout tile").click();
  await page.reload();
  await expect(page.getByLabel("Describe your chip")).toHaveValue("A custom 12-bit counter with synchronous reset.", { timeout: 1500 });
  await expect(page.getByLabel("Target clock (MHz)")).toHaveValue("62.5");
  await expect(page.getByLabel("Fit in one Tiny Tapeout tile")).toBeChecked();
});

test("fractional saved clock defaults pass the browser's native validation", async ({ page }) => {
  await serve(page);
  await page.addInitScript(() => localStorage.setItem("silicon-agent.run-defaults", JSON.stringify({ clock: 62.5, fit: false, expert: false })));
  await page.goto("/");
  await expect(page.getByLabel("Target clock (MHz)")).toHaveValue("62.5");
  expect(await page.getByLabel("Target clock (MHz)").evaluate((input: HTMLInputElement) => input.validity.valid)).toBe(true);
});

test("a rejected build keeps the draft, and discard restores current defaults", async ({ page }) => {
  const api = await serve(page);
  await page.addInitScript(() => localStorage.setItem("silicon-agent.run-defaults", JSON.stringify({ clock: 75, fit: false, expert: true })));
  await page.goto("/");
  await page.getByLabel("Describe your chip").fill("A counter that holds when enable is low.");
  await page.getByLabel("Target clock (MHz)").fill("62.5");
  await page.getByLabel("Review spec before RTL").uncheck();
  await page.getByRole("button", { name: "Build my chip" }).click();
  await expect(page.getByText("Another build is active", { exact: true })).toBeVisible();
  expect(api.requests).toEqual([{ spec_text: "A counter that holds when enable is low.", targets: { clock_mhz: 62.5 } }]);
  await page.reload();
  await expect(page.getByLabel("Review spec before RTL")).not.toBeChecked();
  await expect(page.getByLabel("Target clock (MHz)")).toHaveValue("62.5");
  await page.getByRole("button", { name: "Discard draft" }).click();
  await expect(page.getByLabel("Target clock (MHz)")).toHaveValue("75");
  await expect(page.getByLabel("Review spec before RTL")).toBeChecked();
  expect(await page.evaluate((key) => localStorage.getItem(key), draftKey)).toBeNull();
});

test("a successfully queued build clears its draft", async ({ page }) => {
  const api = await serve(page, 202);
  await page.goto("/");
  await page.getByLabel("Target clock (MHz)").fill("62.5");
  await page.getByRole("button", { name: "Build my chip" }).click();
  await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), draftKey)).toBeNull();
  expect(api.requests).toHaveLength(1);
  expect(api.requests[0]).toMatchObject({ preset_id: "counter", targets: { clock_mhz: 62.5 } });
});

test("blocked browser storage is explained and does not prevent editing", async ({ page }) => {
  await serve(page);
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new DOMException("Storage blocked", "SecurityError"); };
    Storage.prototype.setItem = () => { throw new DOMException("Storage blocked", "SecurityError"); };
  });
  await page.goto("/");
  await page.getByLabel("Describe your chip").fill("My draft stays editable even if storage is blocked.");
  await expect(page.getByRole("status").filter({ hasText: "Draft could not be saved" })).toBeVisible();
  await expect(page.getByLabel("Describe your chip")).toHaveValue("My draft stays editable even if storage is blocked.");
});

test("toolchain status has a worker check, keyboard details and a refresh action", async ({ page }) => {
  const api = await serve(page);
  await page.goto("/");
  const worker = page.getByRole("button", { name: "Worker: Not verified. Show details" });
  await worker.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Start the host worker", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  const before = api.healthCalls();
  await page.getByRole("button", { name: "Refresh toolchain status" }).click();
  await expect.poll(api.healthCalls).toBe(before + 1);
});

for (const action of ["queue", "discard"] as const) {
  test(`${action} in an older tab preserves a newer draft from another tab`, async ({ page, context }) => {
    const api = await serve(page, 202);
    await page.goto("/");
    await page.getByLabel("Describe your chip").fill("First tab's independent counter request.");
    const other = await context.newPage();
    await serve(other);
    await other.goto("/");
    await other.getByLabel("Describe your chip").fill("Second tab's newer UART request must survive.");
    await other.getByLabel("Target clock (MHz)").fill("84.5");
    const newer = await other.evaluate((key) => localStorage.getItem(key), draftKey);
    if (action === "queue") {
      await page.getByRole("button", { name: "Build my chip" }).click();
      await expect(page).toHaveURL(/\/runs\/[a-f0-9]{32}$/);
      expect(api.requests).toHaveLength(1);
      expect(api.requests[0]).toMatchObject({ spec_text: "First tab's independent counter request." });
    } else {
      await page.getByRole("button", { name: "Discard draft" }).click();
    }
    expect(await other.evaluate((key) => localStorage.getItem(key), draftKey)).toBe(newer);
    if (action === "discard") await expect(page.getByRole("status").filter({ hasText: "A newer draft from another tab was kept" })).toBeVisible();
    await other.reload();
    await expect(other.getByLabel("Describe your chip")).toHaveValue("Second tab's newer UART request must survive.");
    await expect(other.getByLabel("Target clock (MHz)")).toHaveValue("84.5");
    await other.close();
  });
}

test("physical flow configuration survives reload and only valid settings are submitted", async ({ page }) => {
  const api = await serve(page);
  await page.goto("/");
  await page.getByText("Configure physical flow", { exact: true }).click();
  await page.getByLabel("Flow attempts (1–6)", { exact: true }).fill("");
  await expect(page.getByRole("button", { name: "Build my chip", exact: true })).toBeDisabled();
  await page.reload();
  await page.getByText(/Configure physical flow/).click();
  await expect(page.getByLabel("Flow attempts (1–6)", { exact: true })).toHaveValue("");
  await page.getByLabel("Flow attempts (1–6)", { exact: true }).fill("2");
  await page.getByLabel("RTL repair loops (0–5)", { exact: true }).fill("0");
  await page.getByLabel("Initial synthesis strategy", { exact: true }).selectOption("DELAY 1");
  await page.getByLabel("Core utilization (%)", { exact: true }).fill("38.5");
  await page.getByLabel("Placement density (%)", { exact: true }).fill("44.25");
  await page.getByLabel("Compare optimization variants after the first layout").uncheck();
  await page.getByRole("button", { name: "Build my chip", exact: true }).click();
  await expect(page.getByText("Another build is active", { exact: true })).toBeVisible();
  expect(api.requests).toHaveLength(1);
  expect(api.requests[0]).toMatchObject({ build: { optimize: false, max_flow_runs: 2, max_repair_loops: 0, initial_flow: { SYNTH_STRATEGY: "DELAY 1", FP_CORE_UTIL: 38.5, PL_TARGET_DENSITY_PCT: 44.25 } } });
});
