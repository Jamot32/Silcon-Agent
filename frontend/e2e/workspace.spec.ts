import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import type { CreateRunInput, Metric, PublicRun } from "../lib/api";
import type { WorkspaceDraft } from "../lib/workspace";

// UI transitions are simulated; measurements and original files are from a
// committed real recording. Every API call is intercepted, including builds.
const recording = JSON.parse(readFileSync(new URL("../../demo_recordings/uart-optimization/recording.json", import.meta.url), "utf8")) as { run: PublicRun; files: Record<string, string>; metrics: Metric[] };
const A = "a".repeat(32), B = "b".repeat(32), CHILD = "c".repeat(32);
const SOURCE = "src/uart_tx.v";
const edited = `// User workspace edit\n${recording.files[SOURCE]}`;
const parent: PublicRun = { ...recording.run, id: A, display_name: "Editable UART", is_replay: false, parent_run_id: null, carried_files: [], pinned: false, archived: false };
const metric = recording.metrics[0];

async function serve(page: Page, patch: Partial<PublicRun> = {}) {
  const state = {
    draft: { files: null, revision: 0, updated_at: null, base_source: null } as WorkspaceDraft,
    runs: new Map([[A, { ...parent, ...patch }], [B, { ...parent, id: B, display_name: "Other UART" }]]),
    writes: [] as { method: string; path: string; body: unknown }[],
    sourceReads: [] as string[], builds: [] as CreateRunInput[], buildFailure: false, missingSource: false,
    errors: [] as string[],
  };
  page.on("pageerror", (error) => state.errors.push(error.message));
  await page.route("**/api/**", async (route) => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
    const body = request.postData() ? request.postDataJSON() : null;
    if (method !== "GET") state.writes.push({ method, path, body });
    if (path === "/api/runs") {
      if (method === "GET") return route.fulfill({ json: [...state.runs.values()] });
      state.builds.push(body);
      if (state.buildFailure) return route.fulfill({ status: 409, json: { detail: "The worker is busy. Your draft is saved." } });
      state.runs.set(CHILD, { ...parent, id: CHILD, status: "pending", stage: "SPEC", best_run_tag: null, parent_run_id: A, execution_mode: body.execution_mode, has_manual_edits: true });
      return route.fulfill({ json: { run_id: CHILD } });
    }
    if (path === "/api/recordings") return route.fulfill({ json: [] });
    const match = /^\/api\/runs\/([a-f0-9]{32})(?:\/(.*))?$/.exec(path);
    if (!match) return route.fulfill({ status: 404, json: { detail: "Unmocked API endpoint" } });
    const [, id, action] = match, run = state.runs.get(id);
    if (!run) return route.fulfill({ status: 404, json: { detail: "Run not found" } });
    if (!action) return route.fulfill({ json: run });
    if (action === "workspace") {
      if (method === "GET") return route.fulfill({ json: state.draft });
      if (body.expected_revision !== state.draft.revision) return route.fulfill({ status: 409, json: { detail: "Draft changed" } });
      state.draft = { files: body.files, revision: state.draft.revision + 1, base_source: body.base_source, updated_at: "2026-11-03T12:00:00Z" };
      return route.fulfill({ json: state.draft });
    }
    if (action === "files") return route.fulfill({ json: recording.files });
    if (action === "metrics") return route.fulfill({ json: id === CHILD ? [] : recording.metrics });
    if (action === "events") return route.fulfill({ contentType: "text/event-stream", body: "" });
    if (action === "sources") {
      state.sourceReads.push(`${id}${url.search}`);
      const missing = state.missingSource && id === B;
      return route.fulfill({ json: { available: !missing, files: missing ? {} : { ...recording.files, [SOURCE]: id === B ? edited : recording.files[SOURCE] }, run_tag: url.searchParams.get("run_tag"), event_id: null, provenance: missing ? "unavailable" : "selected_bundle", reason: missing ? "This flow has no immutable source snapshot." : "Offline UI fixture from recorded source." } });
    }
    if (action === "flow") {
      const selectedMetric = recording.metrics.find((item) => item.run_tag === url.searchParams.get("run_tag")) ?? metric;
      return route.fulfill({ json: { run_tag: selectedMetric.run_tag, metrics: selectedMetric,
        requested_config: { SYNTH_STRATEGY: "AREA 0" }, planned_config: null, applied_config: null,
        resolved_config: { SYNTH_STRATEGY: id === B ? "DELAY 2" : "AREA 0" },
        signoff: { checks: { violating_corners: {} } }, provenance: { evidence_status: "verified" }, reports: {}, warnings: [] } });
    }
    return route.fulfill({ status: 404, json: { detail: "Unmocked run endpoint" } });
  });
  return state;
}

async function loadWorking(page: Page) {
  // First use opens an editable copy immediately, without a second load action.
  await expect(page.getByTestId("workspace-editor")).toHaveAttribute("data-file-path", SOURCE);
}
async function replaceCode(page: Page, value: string) {
  const editor = page.getByRole("textbox", { name: `Edit ${SOURCE}`, exact: true });
  await expect(page.getByTestId("workspace-editor").locator(".monaco-editor")).toBeVisible();
  await editor.focus();
  await page.keyboard.press("ControlOrMeta+A");
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.evaluate((text) => navigator.clipboard.writeText(text), value);
  await page.keyboard.press("ControlOrMeta+V");
}

test("editable Monaco saves a detached draft and recovers unsaved edits after navigation", async ({ page }) => {
  const state = await serve(page);
  await page.goto(`/runs/${A}/workspace`);
  await loadWorking(page);
  await replaceCode(page, edited);
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Draft saved on the server." })).toBeVisible();
  expect(state.draft.files?.[SOURCE]).toBe(edited);
  expect(state.draft.revision).toBe(1);
  expect(recording.files[SOURCE]).not.toBe(edited);
  const unsaved = `// Recovered after navigation\n${edited}`;
  await replaceCode(page, unsaved);
  await page.getByRole("link", { name: "Back to run", exact: true }).click();
  await page.getByRole("link", { name: "Code workspace", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Recovered your unsaved edits" })).toBeVisible();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect.poll(() => state.draft.files?.[SOURCE]).toBe(unsaved);
  expect(state.writes.every(({ path }) => path.endsWith("/workspace"))).toBe(true);
  expect(state.errors).toEqual([]);
});

test("concurrent saves keep local code and replacement requires confirmation", async ({ page }) => {
  const state = await serve(page);
  await page.goto(`/runs/${A}/workspace`);
  await loadWorking(page); await replaceCode(page, edited);
  state.draft = { files: recording.files, revision: 1, updated_at: "2026-11-03T12:00:00Z", base_source: null };
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Another tab saved a newer draft" })).toBeVisible();
  expect(state.draft.files).toEqual(recording.files);
  await page.reload();
  await expect(page.getByRole("alert").filter({ hasText: "server draft changed" })).toBeVisible();
  await page.getByRole("button", { name: "Reload saved draft", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Replace unsaved changes?", exact: true });
  await dialog.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Reload saved draft", exact: true }).click();
  await dialog.getByRole("button", { name: "Replace files", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved draft reloaded." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toBeDisabled();
  await expect(page.getByTestId("workspace-editor").locator(".view-lines")).not.toContainText("User workspace edit");
  expect(state.errors).toEqual([]);
});

test("default build saves edited snapshot and forks an agent-assisted child", async ({ page }) => {
  const state = await serve(page);
  await page.goto(`/runs/${A}/workspace`); await loadWorking(page); await replaceCode(page, edited);
  await expect(page.getByLabel("Build mode", { exact: true })).toHaveValue("agent");
  await expect(page.getByText(/writes fresh independent tests, and may repair/)).toBeVisible();
  await page.getByRole("button", { name: "Build edited design", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${CHILD}$`));
  expect(state.builds).toHaveLength(1);
  expect(state.builds[0]).toMatchObject({ execution_mode: "agent", parent_run_id: A, manual_files: { [SOURCE]: edited } });
  expect(state.writes.map(({ method }) => method)).toEqual(["PUT", "POST"]);
  expect(state.draft.files).toEqual(state.builds[0].manual_files);
  await expect(page.getByTestId("revision-notice")).toContainText("your edited RTL");
  expect(state.errors).toEqual([]);
});

test("manual mode uses edited tests and a busy queue leaves saved files available", async ({ page }) => {
  const state = await serve(page); state.buildFailure = true;
  await page.goto(`/runs/${A}/workspace`); await loadWorking(page);
  await page.getByLabel("Build mode", { exact: true }).selectOption("manual");
  await page.getByRole("button", { name: "Build edited design", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The worker is busy" })).toBeVisible();
  expect(state.builds[0]).toMatchObject({ execution_mode: "manual", manual_files: recording.files });
  expect(state.draft.files).toEqual(recording.files);
  await expect(page.getByRole("button", { name: "Build edited design", exact: true })).toBeEnabled();
  await page.getByRole("navigation", { name: "Workspace files" }).getByRole("button", { name: "test_uart_spec.py", exact: true }).click();
  await page.getByRole("button", { name: "Remove file", exact: true }).click();
  await page.getByRole("dialog", { name: "Remove this file?" }).getByRole("button", { name: "Remove file", exact: true }).click();
  await expect(page.getByRole("button", { name: "Build edited design", exact: true })).toBeDisabled();
  await page.getByLabel("Build mode", { exact: true }).selectOption("agent");
  await expect(page.getByRole("button", { name: "Build edited design", exact: true })).toBeEnabled();
  expect(state.errors).toEqual([]);
});

test("flow comparison uses selected sources across runs and never substitutes missing evidence", async ({ page }) => {
  const state = await serve(page);
  await page.goto(`/runs/${A}/workspace?view=compare`);
  await page.getByLabel("Candidate run", { exact: true }).selectOption(B);
  const diff = page.getByTestId("workspace-source-diff");
  await expect(diff.locator(".monaco-diff-editor")).toBeVisible();
  await expect(page.getByLabel("Compare file", { exact: true })).toHaveValue(SOURCE);
  await expect(page.getByText("Changes are highlighted between the two snapshots.", { exact: true })).toBeVisible();
  await page.locator("summary").filter({ hasText: /^Resolved configuration$/ }).click();
  await expect(page.getByTestId("workspace-comparison")).toContainText("DELAY 2");
  expect(state.sourceReads).toContain(`${B}?run_tag=${recording.run.best_run_tag}`);
  await page.screenshot({ path: test.info().outputPath("workspace-compare-desktop.png"), animations: "disabled" });
  state.missingSource = true;
  await page.getByLabel("Candidate flow", { exact: true }).selectOption(`tag:${recording.metrics[1].run_tag}`);
  await expect(page.getByLabel("Candidate provenance")).toContainText("This flow has no immutable source snapshot.");
  await expect(diff).toHaveCount(0);
  await expect(page.getByText(/Missing evidence is never replaced with current working files/)).toBeVisible();
  expect(state.writes).toEqual([]); expect(state.errors).toEqual([]);
});

test("small-screen editor validates file paths and retains usable controls", async ({ page }) => {
  const state = await serve(page, { status: "running", stage: "RTL" });
  await page.setViewportSize({ width: 320, height: 812 });
  await page.goto(`/runs/${A}/workspace`); await loadWorking(page);
  await expect(page.getByRole("button", { name: "Build edited design", exact: true })).toBeDisabled();
  await expect(page.getByLabel("Build requirements")).toContainText("Wait for the parent run to finish or stop");
  await page.locator("summary").filter({ hasText: /^Add file$/ }).click();
  await page.getByLabel("New file path", { exact: true }).fill("../outside.v");
  await page.getByRole("button", { name: "Add file", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Use src/name.v or test/name.py" })).toBeVisible();
  const longPath = `src/${"a".repeat(100)}.v`;
  await page.getByLabel("New file path", { exact: true }).fill(longPath);
  await page.getByRole("button", { name: "Add file", exact: true }).click();
  await expect(page.getByTestId("workspace-editor")).toHaveAttribute("data-file-path", longPath);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("workspace-editor-mobile.png"), animations: "disabled" });
  await page.getByRole("tab", { name: "Compare flows", exact: true }).click();
  await expect(page.getByTestId("workspace-source-diff").locator(".monaco-diff-editor")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("workspace-compare-mobile.png"), animations: "disabled" });
  expect(state.errors).toEqual([]);
});

test("editor fallback remains editable and blocked browser storage protects navigation", async ({ page }) => {
  const state = await serve(page);
  await page.route("**/monaco/editor.js", (route) => route.abort());
  await page.addInitScript(() => { Storage.prototype.setItem = () => { throw new DOMException("Storage disabled", "SecurityError"); }; });
  await page.goto(`/runs/${A}/workspace`); await loadWorking(page);
  const editor = page.getByRole("textbox", { name: `Edit ${SOURCE}`, exact: true });
  await editor.fill(edited);
  await expect(page.getByRole("alert").filter({ hasText: "Browser recovery could not be saved" })).toBeVisible();
  await page.getByRole("link", { name: "Back to run", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "Leave without saving?", exact: true });
  await expect(confirmation).toBeVisible();
  await confirmation.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(editor).toHaveValue(edited);
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect.poll(() => state.draft.files?.[SOURCE]).toBe(edited);
  await page.getByRole("link", { name: "Back to run", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${A}$`));
  expect(state.errors).toEqual([]);
});

for (const width of [1440, 390]) test(`Edit code opens a populated editor and accepts click typing at ${width}px`, async ({ page }) => {
  const state = await serve(page);
  await page.setViewportSize({ width, height: 1000 });
  await page.goto(`/runs/${A}`);
  const source = page.getByRole("region", { name: "Design source code", exact: true });
  await expect(source).toContainText("Read-only");
  await source.getByRole("link", { name: "Edit code", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${A}/workspace\\?`));
  await loadWorking(page);
  const editor = page.getByTestId("workspace-editor");
  await expect(editor.locator(".monaco-editor")).toBeVisible();
  // Actual pointer focus and physical key events: no programmatic focus,
  // Monaco API writes, clipboard paste, or textarea fallback.
  await editor.locator(".monaco-editor").click({ position: { x: 120, y: 80 } });
  await page.keyboard.press(process.platform === "darwin" ? "Meta+ArrowUp" : "Control+Home");
  await page.keyboard.type("// Typed directly in the code editor\n", { delay: 15 });
  await page.keyboard.press("ControlOrMeta+S");
  await expect.poll(() => state.draft.files?.[SOURCE]).toBe(`// Typed directly in the code editor\n${recording.files[SOURCE]}`);
  expect(state.writes).toHaveLength(1);
  expect(state.writes[0].path).toBe(`/api/runs/${A}/workspace`);
  const fileTree = page.getByRole("navigation", { name: "Workspace files", exact: true });
  await fileTree.getByRole("button", { name: "test_uart_spec.py", exact: true }).click();
  await expect(editor).toHaveAttribute("data-file-path", "test/test_uart_spec.py");
  await fileTree.getByRole("button", { name: "uart_tx.v", exact: true }).click();
  await expect(editor.locator(".view-lines")).toContainText("Typed directly in the code editor");
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: "Saved workspace loaded." })).toBeVisible();
  await expect(editor.locator(".view-lines")).toContainText("Typed directly in the code editor");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("code-directly-edited.png"), animations: "disabled" });
  expect(state.errors).toEqual([]);
});

test("Edit code keeps a saved draft and opens the selected test file", async ({ page }) => {
  const state = await serve(page);
  state.draft = { files: { ...recording.files, [SOURCE]: edited }, base_source: { kind: "working", run_tag: null, event_id: null }, revision: 2, updated_at: "2026-11-03T12:00:00Z" };
  await page.goto(`/runs/${A}`);
  const source = page.getByRole("region", { name: "Design source code", exact: true });
  await source.getByRole("tab", { name: "test/test_uart_spec.py", exact: true }).click();
  await source.getByRole("link", { name: "Edit code", exact: true }).click();
  await expect(page.getByTestId("workspace-editor")).toHaveAttribute("data-file-path", "test/test_uart_spec.py");
  await expect(page.getByRole("status").filter({ hasText: "Saved workspace loaded." })).toBeVisible();
  expect(state.draft.files?.[SOURCE]).toBe(edited);
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toBeDisabled();
  expect(state.writes).toEqual([]); expect(state.errors).toEqual([]);
});

test("an intentionally empty saved draft stays empty", async ({ page }) => {
  const state = await serve(page);
  state.draft = { files: {}, revision: 1, updated_at: "2026-11-03T12:00:00Z", base_source: null };
  await page.goto(`/runs/${A}/workspace`);
  await expect(page.getByText("No draft files", { exact: true })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Saved workspace loaded." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toBeDisabled();
  expect(state.writes).toEqual([]); expect(state.errors).toEqual([]);
});
