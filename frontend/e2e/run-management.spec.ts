import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import type { Metric, Project, PublicRun, RunMetadata } from "../lib/api";

// Measured data and images come from the committed recording. Every API call is
// intercepted: these UI tests never rename, pin, cancel, or delete a real run.
const recordingRoot = new URL("../../demo_recordings/uart-repair/", import.meta.url);
const recording = JSON.parse(readFileSync(new URL("recording.json", recordingRoot), "utf8")) as {
  run: PublicRun; files: Record<string, string>; metrics: Metric[]; layouts: Record<string, string>;
};
const A = "a".repeat(32), B = "b".repeat(32), C = "c".repeat(32);
const D = "d".repeat(32), E = "e".repeat(32), F = "f".repeat(32);
const terminal = (status: string) => ["done", "failed", "cancelled"].includes(status);
const saved = (id: string, display_name: string, patch: Partial<PublicRun> = {}): PublicRun => ({
  ...recording.run, id, display_name, pinned: false, archived: false,
  is_replay: false, recording_id: null, replay_speed: null, parent_run_id: null,
  carried_files: [], review_requested: false, review_submitted: false, ...patch,
});

async function serve(page: Page, initial: PublicRun[]) {
  const runs = new Map(initial.map((run) => [run.id, structuredClone(run)]));
  const projects = new Map<string, Project>();
  const mutations: { method: string; path: string; body: unknown }[] = [];
  const errors: string[] = [];
  const failures = { delete: 0, cancel: 0 };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", (route) => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    const body = request.postData() ? request.postDataJSON() : undefined;
    if (!["GET", "HEAD"].includes(method)) mutations.push({ method, path, body });
    if (path === "/api/runs" && method === "GET") return route.fulfill({ json: [...runs.values()] });
    if (path === "/api/recordings") return route.fulfill({ json: [] });
    if (path === "/api/projects" && method === "GET") return route.fulfill({ json: [...projects.values()] });
    if (path === "/api/projects" && method === "POST") {
      const project = { id: String(projects.size + 1).padStart(32, "0"), name: (body as { name: string }).name, created_at: new Date().toISOString() };
      projects.set(project.id, project);
      return route.fulfill({ status: 201, json: project });
    }
    const projectMatch = /^\/api\/projects\/([a-f0-9]{32})$/.exec(path);
    if (projectMatch && method === "DELETE") {
      projects.delete(projectMatch[1]);
      for (const run of runs.values()) if (run.project_id === projectMatch[1]) run.project_id = null;
      return route.fulfill({ status: 204 });
    }
    if (path === "/api/runs/move" && method === "POST") {
      const { run_ids, project_id } = body as { run_ids: string[]; project_id: string | null };
      const moved = run_ids.map((id) => runs.get(id)).filter((run): run is PublicRun => run !== undefined);
      for (const run of moved) run.project_id = project_id;
      return route.fulfill({ json: moved });
    }
    if (path === "/api/runs/cleanup" && method === "POST") {
      const deleted_ids: string[] = [], skipped: { id: string; reason: string }[] = [];
      for (const id of (body as { run_ids: string[] }).run_ids) {
        const run = runs.get(id);
        if (!run) skipped.push({ id, reason: "not found" });
        else if (run.pinned) skipped.push({ id, reason: "pinned" });
        else if (!terminal(run.status)) skipped.push({ id, reason: "active" });
        else { runs.delete(id); deleted_ids.push(id); }
      }
      return route.fulfill({ json: { deleted_ids, skipped } });
    }
    const match = /^\/api\/runs\/([a-f0-9]{32})(?:\/(.*))?$/.exec(path);
    if (!match) return route.fulfill({ status: 404, json: { detail: "Unmocked API path" } });
    const [, id, action] = match, run = runs.get(id);
    if (!run) return route.fulfill({ status: 404, json: { detail: "Run not found" } });
    if (!action && method === "GET") return route.fulfill({ json: run });
    if (!action && method === "PATCH") {
      Object.assign(run, body as RunMetadata);
      return route.fulfill({ json: run });
    }
    if (!action && method === "DELETE") {
      if (failures.delete-- > 0) return route.fulfill({ status: 503, json: { detail: "Run storage is temporarily unavailable." } });
      if (run.pinned || !terminal(run.status)) return route.fulfill({ status: 409, json: { detail: "This run is protected." } });
      runs.delete(id);
      return route.fulfill({ status: 204 });
    }
    if (action === "cancel" && method === "POST") {
      if (failures.cancel-- > 0) return route.fulfill({ status: 503, json: { detail: "The stop request could not reach the worker." } });
      run.status = "cancel_requested";
      return route.fulfill({ json: run });
    }
    if (action === "files") return route.fulfill({ json: terminal(run.status) ? recording.files : {} });
    if (action === "metrics") return route.fulfill({ json: run.best_run_tag ? recording.metrics : [] });
    if (action === "events") return route.fulfill({ contentType: "text/event-stream", body: "" });
    if (action?.startsWith("layout/")) {
      const tag = decodeURIComponent(action.slice(7, -4)), file = recording.layouts[tag];
      if (file) return route.fulfill({ contentType: "image/png", body: readFileSync(new URL(file, recordingRoot)) });
    }
    return route.fulfill({ status: 404, json: { detail: "Unmocked run endpoint" } });
  });
  return { runs, mutations, failures, errors };
}

const row = (page: Page, id: string) => page.getByTestId(`run-row-${id}`);
async function manage(page: Page, id: string) {
  await page.getByTestId(`run-actions-${id}`).click();
  return page.getByRole("dialog", { name: /^Manage / });
}

test("custom names and pins persist, and archived runs can be restored", async ({ page }) => {
  const api = await serve(page, [saved(A, "Saved UART")]);
  await page.goto(`/runs/${A}`);
  let menu = await manage(page, A);
  await menu.getByLabel("Run name", { exact: true }).fill("Bench UART");
  await menu.getByRole("button", { name: "Save name", exact: true }).click();
  await expect(menu.getByRole("status")).toHaveText("Name saved.");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Bench UART");
  await menu.getByRole("button", { name: "Pin run", exact: true }).click();
  await expect(menu.getByRole("button", { name: "Delete run…", exact: true })).toBeDisabled();
  await expect(menu).toContainText("Pinned runs are protected.");
  await page.keyboard.press("Escape");
  const pinned = page.getByRole("navigation", { name: "Pinned projects", exact: true });
  await expect(pinned.getByRole("link", { name: "Bench UART", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Bench UART");
  await expect(pinned.getByRole("link", { name: "Bench UART", exact: true })).toBeVisible();
  menu = await manage(page, A);
  await expect(menu.getByLabel("Run name", { exact: true })).toHaveValue("Bench UART");
  await expect(menu.getByRole("button", { name: "Unpin run", exact: true })).toBeVisible();
  await menu.getByRole("button", { name: "Archive run", exact: true }).click();
  await expect(menu.getByRole("status")).toHaveText("Run archived.");
  await page.keyboard.press("Escape");
  await page.goto("/runs");
  await expect(row(page, A)).toHaveCount(0);
  await page.getByRole("tab", { name: "Archived", exact: true }).click();
  await expect(row(page, A)).toContainText("Bench UART");
  menu = await manage(page, A);
  await menu.getByRole("button", { name: "Restore to history", exact: true }).click();
  await expect(row(page, A)).toHaveCount(0);
  await page.getByRole("tab", { name: "History", exact: true }).click();
  await expect(row(page, A)).toContainText("Bench UART");
  expect(api.runs.get(A)).toMatchObject({ display_name: "Bench UART", pinned: true, archived: false });
  expect(api.mutations.map((mutation) => mutation.body)).toEqual([
    { display_name: "Bench UART" }, { pinned: true }, { archived: true }, { archived: false },
  ]);
  expect(api.errors).toEqual([]);
});

test("deletion requires confirmation, preserves failures, and redirects after success", async ({ page }) => {
  const api = await serve(page, [saved(A, "Disposable UART")]);
  api.failures.delete = 1;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/runs/${A}`);
  const menu = await manage(page, A);
  await menu.getByRole("button", { name: "Delete run…", exact: true }).click();
  await expect(menu.getByText("Delete this run permanently?", { exact: true })).toBeVisible();
  await expect(menu).toContainText("This cannot be undone.");
  await menu.getByRole("button", { name: "Keep run", exact: true }).click();
  expect(api.mutations).toEqual([]);
  await expect(menu.getByRole("button", { name: "Delete run…", exact: true })).toBeFocused();
  await menu.getByRole("button", { name: "Delete run…", exact: true }).click();
  await menu.getByRole("button", { name: "Delete permanently", exact: true }).click();
  await expect(menu.getByRole("alert").filter({ hasText: "Run storage is temporarily unavailable." })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/runs/${A}$`));
  expect(api.runs.has(A)).toBe(true);
  await expect(menu.getByRole("button", { name: "Delete permanently", exact: true })).toBeEnabled();
  await menu.getByRole("button", { name: "Delete permanently", exact: true }).click();
  await expect(page).toHaveURL(/\/runs$/);
  await expect(row(page, A)).toHaveCount(0);
  expect(api.runs.has(A)).toBe(false);
  expect(api.mutations.map(({ method, path }) => ({ method, path }))).toEqual([
    { method: "DELETE", path: `/api/runs/${A}` }, { method: "DELETE", path: `/api/runs/${A}` },
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(api.errors).toEqual([]);
});

test("clear history freezes explicit eligible IDs and reports newly protected runs", async ({ page }) => {
  const api = await serve(page, [saved(A, "First candidate"), saved(B, "Pinned design", { pinned: true }),
    saved(C, "Active design", { status: "running", stage: "RTL", best_run_tag: null }),
    saved(D, "Archived design", { archived: true }), saved(E, "Second candidate")]);
  await page.goto("/runs");
  await expect(row(page, A)).toBeVisible();
  await page.getByRole("button", { name: "Clear history…", exact: true }).click();
  let dialog = page.getByRole("dialog", { name: "Clear history?", exact: true });
  const selected = dialog.getByRole("list", { name: "Runs selected for deletion" });
  await expect(selected.getByRole("listitem")).toHaveCount(2);
  await expect(selected).toContainText("First candidate");
  await expect(selected).toContainText("Second candidate");
  await expect(selected).not.toContainText("Pinned design");
  await expect(selected).not.toContainText("Active design");
  await expect(selected).not.toContainText("Archived design");
  await dialog.getByRole("button", { name: "Keep runs", exact: true }).click();
  expect(api.mutations).toEqual([]);
  await page.getByRole("button", { name: "Clear history…", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Clear history?", exact: true });
  // A concurrent tab pins one confirmed run and creates another after review.
  // The request must retain its original explicit IDs, and respect API skips.
  api.runs.get(A)!.pinned = true;
  api.runs.set(F, saved(F, "Created after confirmation"));
  await dialog.getByRole("button", { name: "Delete 2 runs permanently", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "1 run deleted. 1 skipped: pinned." })).toBeVisible();
  expect(api.mutations).toEqual([{ method: "POST", path: "/api/runs/cleanup", body: { run_ids: [A, E] } }]);
  expect([...api.runs.keys()]).toEqual([A, B, C, D, F]);
  await expect(row(page, E)).toHaveCount(0);
  await expect(row(page, F)).toBeVisible();
  await page.getByRole("tab", { name: "Archived", exact: true }).click();
  await expect(row(page, D)).toBeVisible();
  expect(api.errors).toEqual([]);
});

for (const replay of [false, true]) {
  test(`${replay ? "replay" : "live run"} stop stays pending until worker confirms teardown`, async ({ page }) => {
    const api = await serve(page, [saved(A, "Work in progress", { status: "running", stage: "RTL", best_run_tag: null,
      is_replay: replay, recording_id: replay ? "uart-repair" : null, replay_speed: replay ? 4 : null })]);
    await page.goto(`/runs/${A}`);
    const dashboard = page.getByTestId("run-dashboard");
    await page.getByRole("button", { name: replay ? "Stop replay" : "Cancel run", exact: true }).click();
    await expect(page.getByRole("button", { name: "Stopping…", exact: true })).toBeDisabled();
    await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "cancel_requested");
    await expect(dashboard.getByRole("status").filter({ hasText: "Stop requested." })).toBeVisible();
    await expect(dashboard).not.toContainText("before this run ended");
    await expect(page.getByRole("button", { name: "Continue design", exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("button", { name: "Stopping…", exact: true })).toBeDisabled();
    expect(api.mutations).toEqual([{ method: "POST", path: `/api/runs/${A}/cancel`, body: undefined }]);
    api.runs.get(A)!.status = "cancelled";
    await page.reload();
    await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "cancelled");
    await expect(dashboard.getByRole("status").filter({ hasText: "Run stopped." })).toBeVisible();
    await expect(page.getByRole("button", { name: "Stopping…", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Continue design", exact: true })).toBeVisible();
    expect(api.errors).toEqual([]);
  });
}

test("a failed stop request is explained and can be retried", async ({ page }) => {
  const api = await serve(page, [saved(A, "Active design", { status: "running", stage: "RTL", best_run_tag: null })]);
  api.failures.cancel = 1;
  await page.goto(`/runs/${A}`);
  await page.getByRole("button", { name: "Cancel run", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The stop request could not reach the worker." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel run", exact: true })).toBeEnabled();
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "running");
  await page.getByRole("button", { name: "Cancel run", exact: true }).click();
  await expect(page.getByRole("button", { name: "Stopping…", exact: true })).toBeDisabled();
  await expect(page.getByRole("alert").filter({ hasText: "The stop request could not reach the worker." })).toHaveCount(0);
  expect(api.mutations).toHaveLength(2);
  expect(api.errors).toEqual([]);
});

test("a 120-character unbroken name fits history, deletion, and run pages at 320px", async ({ page }) => {
  const longName = "Q".repeat(120);
  const api = await serve(page, [saved(A, longName)]);
  await page.setViewportSize({ width: 320, height: 844 });
  const fitsPage = () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
  await page.goto("/runs");
  await expect(row(page, A)).toContainText(longName);
  expect(await fitsPage()).toBe(true);
  const menu = await manage(page, A);
  await menu.getByRole("button", { name: "Delete run…", exact: true }).click();
  await expect(menu.getByText("Delete this run permanently?", { exact: true })).toBeVisible();
  await expect(menu).toContainText(longName);
  expect(await menu.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await fitsPage()).toBe(true);
  await menu.getByRole("button", { name: "Keep run", exact: true }).click();
  await page.keyboard.press("Escape");
  for (const suffix of ["", "/result"]) {
    await page.goto(`/runs/${A}${suffix}`);
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toContainText(longName);
    expect(await heading.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    if (suffix) {
      const layout = page.getByTestId("result-layout-image");
      await expect(layout).toBeVisible();
      await expect.poll(() => layout.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true);
    }
    expect(await fitsPage()).toBe(true);
  }
  expect(api.mutations).toEqual([]);
  expect(api.errors).toEqual([]);
});

test("runs move into a project in bulk or by dragging, and deleting the project keeps them", async ({ page }) => {
  const api = await serve(page, [saved(A, "First UART"), saved(B, "Second UART"), saved(C, "Counter")]);
  const project = "0".repeat(31) + "1";
  await page.goto("/runs");
  await expect(row(page, A)).toBeVisible();
  await page.getByLabel("New project name", { exact: true }).fill("  UART work ");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No runs in UART work yet." })).toBeVisible();
  await page.getByRole("button", { name: "Show all runs", exact: true }).click();

  await row(page, A).getByRole("checkbox", { name: "Select First UART" }).click();
  await row(page, B).getByRole("checkbox", { name: "Select Second UART" }).click();
  await expect(page.getByRole("toolbar", { name: "Selected runs" })).toContainText("2 selected");
  await page.getByLabel("Move selected runs to", { exact: true }).selectOption({ label: "UART work" });
  await page.getByRole("button", { name: "Move", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "moved" })).toHaveText("2 runs moved to UART work.");
  await expect(row(page, A)).toContainText("UART work");
  const recent = page.locator("[data-sidebar=group]").filter({ hasText: "Recent runs" });
  await expect(recent.getByRole("link", { name: "Counter" })).toBeVisible();
  await expect(recent.getByRole("link", { name: "First UART" })).toHaveCount(0);

  await row(page, C).dragTo(page.getByTestId(`project-folder-${project}`));
  await expect(page.getByRole("status").filter({ hasText: "moved" })).toHaveText("1 run moved to UART work.");
  await page.getByTestId(`project-folder-unfiled`).getByRole("button").click();
  await expect(page.getByRole("heading", { name: "Every run is in a project." })).toBeVisible();
  await page.getByTestId(`project-folder-${project}`).getByRole("button", { name: /^UART work/ }).click();
  for (const id of [A, B, C]) await expect(row(page, id)).toBeVisible();
  await page.getByTestId(`sidebar-project-${project}`).getByRole("button").click();
  await expect(page.getByTestId(`sidebar-project-${project}`).getByRole("link")).toHaveCount(3);

  await page.getByRole("button", { name: "Manage project UART work", exact: true }).click();
  await page.getByRole("button", { name: "Delete project…", exact: true }).click();
  await page.getByRole("button", { name: "Delete project", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "deleted" })).toHaveText("Project “UART work” deleted. Its runs are in Unfiled.");
  for (const id of [A, B, C]) await expect(row(page, id)).toBeVisible();
  expect([...api.runs.values()].map((run) => run.project_id)).toEqual([null, null, null]);
  expect(api.mutations.map(({ method, path, body }) => ({ method, path, body }))).toEqual([
    { method: "POST", path: "/api/projects", body: { name: "UART work" } },
    { method: "POST", path: "/api/runs/move", body: { run_ids: [A, B], project_id: project } },
    { method: "POST", path: "/api/runs/move", body: { run_ids: [C], project_id: project } },
    { method: "DELETE", path: `/api/projects/${project}`, body: undefined },
  ]);
  expect(api.errors).toEqual([]);
});
