import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { applySnapshot, dashboardLayout, emptyRunState, reduceRunEvent } from "../lib/run-state.ts";

const frontend = fileURLToPath(new URL("../", import.meta.url));
const require = createRequire(new URL("../package.json", import.meta.url));
const React = require("react"), { renderToStaticMarkup } = require("react-dom/server");
const bundle = require("esbuild").buildSync({
  entryPoints: [path.join(frontend, "components/run/layout-viewer.tsx")],
  bundle: true, write: false, platform: "node", format: "cjs", packages: "external",
  alias: { "@": frontend }, jsx: "automatic", logLevel: "silent",
}).outputFiles[0].text;
const viewerModule = { exports: {} };
new Function("require", "module", "exports", bundle)(require, viewerModule, viewerModule.exports);
const { LayoutViewer } = viewerModule.exports;
const run = { id: "a".repeat(32), status: "running", best_run_tag: "selected" };
const metrics = [{ run_tag: "selected", clock_mhz: 75, flow_index: 1 }, { run_tag: "latest", clock_mhz: 50, flow_index: 2 }];
const event = (id, tag) => ({ id, type: "layout_rendered", ts: "2026-10-25T00:00:00Z", payload: { run_tag: tag, image_url: "/host/recorded.png" } });
function history() {
  let state = applySnapshot(emptyRunState(), { run, files: {}, metrics });
  state = reduceRunEvent(state, event(1, "selected"));
  return reduceRunEvent(state, event(2, "latest"));
}

test("DONE selects best even after later comparison events; active runs keep latest", () => {
  const active = history();
  assert.equal(dashboardLayout(active.run, active.latestLayout), active.latestLayout);
  const done = applySnapshot(active, { run: { ...run, status: "done" }, files: {}, metrics });
  assert.equal(done.latestLayout.run_tag, "latest");
  assert.deepEqual(dashboardLayout(done.run, done.latestLayout), { run_tag: "selected", image_url: `/api/runs/${run.id}/layout/selected.png` });
  const delayed = reduceRunEvent(done, event(3, "latest"));
  assert.equal(dashboardLayout(delayed.run, delayed.latestLayout).run_tag, "selected");
});

test("selected image, visible tag and clock render from the same measured flow", () => {
  const state = history();
  const layout = dashboardLayout({ ...run, status: "done" }, state.latestLayout);
  const html = renderToStaticMarkup(React.createElement(LayoutViewer, { layout, metrics, runId: run.id }));
  assert.ok(html.includes(`src="/api/runs/${run.id}/layout/selected.png"`));
  assert.ok(html.includes('title="selected">selected · 75 MHz target</span>'));
  assert.ok(!html.includes("50 MHz target"));
  assert.ok(!html.includes("latest"));
});

test("reload selects before any layout history; missing metric stays unknown", () => {
  const done = { ...run, status: "done", best_run_tag: "selected/encoded" };
  const layout = dashboardLayout(done, null);
  assert.deepEqual(layout, { run_tag: "selected/encoded", image_url: `/api/runs/${run.id}/layout/selected%2Fencoded.png` });
  const html = renderToStaticMarkup(React.createElement(LayoutViewer, { layout, metrics: [], runId: run.id }));
  assert.ok(!html.includes("MHz target"));
});

test("interrupted runs keep actual latest; missing DONE selection never borrows latest", () => {
  const latest = history().latestLayout;
  for (const status of ["pending", "running", "failed", "cancelled"]) {
    assert.equal(dashboardLayout({ ...run, status }, latest), latest);
    assert.equal(dashboardLayout({ ...run, status }, null), null);
  }
  assert.equal(dashboardLayout({ ...run, status: "done", best_run_tag: null }, latest), null);
});
