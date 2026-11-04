import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { build } from "esbuild";

// Bundle the real module so Node can resolve the frontend's extensionless imports.
const compiled = await build({ entryPoints: [new URL("../lib/workspace.ts", import.meta.url).pathname], bundle: true, write: false, platform: "node", format: "esm" });
const { validateWorkspace, workspaceBuildProblems, workspaceFingerprint, workspaceFlows, readWorkspaceRecovery, saveWorkspaceRecovery, clearWorkspaceRecovery, saveWorkspace, getFlowSources } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);
const recording = JSON.parse(readFileSync(new URL("../../demo_recordings/uart-repair/recording.json", import.meta.url), "utf8"));
const rtl = { "src/counter.v": "module counter; endmodule\n" };
const files = { ...rtl, "test/test_counter.py": "import cocotb\n" };
const working = { kind: "working", run_tag: null, event_id: null };
const recovery = { version: 1, revision: 3, files, base_source: working };

function storage(context) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage"), values = new Map();
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) } });
  context.after(() => previous ? Object.defineProperty(globalThis, "localStorage", previous) : delete globalThis.localStorage);
  return values;
}

test("workspace paths and UTF-8 byte limits match the editable source boundary", () => {
  assert.deepEqual(validateWorkspace(files), []);
  for (const path of ["../secret", "src/../test.py", "src/a.b.v", "src/with-dash.v", "src/test.py", "test/chip.v", "test/nested/file.py"]) assert.ok(validateWorkspace({ [path]: "x" }).length, path);
  assert.deepEqual(validateWorkspace({ "src/chip.v": "é".repeat(65536) }), []);
  assert.match(validateWorkspace({ "src/chip.v": "é".repeat(65537) }).join(" "), /128 KiB/);
  assert.match(validateWorkspace({ "src/chip.v": "a\0b" }).join(" "), /null character/);
  assert.match(validateWorkspace(Object.fromEntries(Array.from({ length: 65 }, (_, i) => [`src/f${i}.v`, ""]))).join(" "), /64 files/);
  assert.match(validateWorkspace(Object.fromEntries(Array.from({ length: 17 }, (_, i) => [`src/f${i}.v`, "a".repeat(128 * 1024)]))).join(" "), /2 MiB/);
});

test("agent builds allow fresh tests while manual builds require exactly one edited test module", () => {
  const run = { ...recording.run, status: "done", review_requested: false };
  assert.deepEqual(workspaceBuildProblems(run, rtl, "agent"), []);
  assert.match(workspaceBuildProblems(run, rtl, "manual").join(" "), /one nonempty Python test/);
  assert.deepEqual(workspaceBuildProblems(run, files, "manual"), []);
  const multiple = { ...files, "test/test_second.py": "import cocotb\n" };
  assert.deepEqual(workspaceBuildProblems(run, multiple, "agent"), []);
  assert.match(workspaceBuildProblems(run, multiple, "manual").join(" "), /exactly one test/);
  assert.match(workspaceBuildProblems({ ...run, status: "cancel_requested" }, files, "manual").join(" "), /finish or stop/);
  assert.match(workspaceBuildProblems({ ...run, design_spec: null }, files, "agent").join(" "), /accepted design specification/);
  assert.match(workspaceBuildProblems({ ...run, review_requested: true, review_submitted: false }, files, "agent").join(" "), /review was not accepted/);
});

test("dirty fingerprints ignore file order but retain file edits and source provenance", () => {
  assert.equal(workspaceFingerprint(files, working), workspaceFingerprint(Object.fromEntries(Object.entries(files).reverse()), working));
  assert.notEqual(workspaceFingerprint(files, working), workspaceFingerprint({ ...files, "src/counter.v": "changed" }, working));
  assert.notEqual(workspaceFingerprint(files, working), workspaceFingerprint(files, { kind: "flow", run_tag: "selected", event_id: null }));
});

test("unsaved recovery survives navigation and clearing cannot erase another tab's edits", (context) => {
  storage(context);
  assert.equal(saveWorkspaceRecovery("run", recovery), true);
  assert.deepEqual(readWorkspaceRecovery("run"), { recovery, available: true });
  const other = { ...recovery, files: { ...files, "src/counter.v": "another tab" } };
  saveWorkspaceRecovery("run", other);
  assert.equal(clearWorkspaceRecovery("run", recovery), true);
  assert.deepEqual(readWorkspaceRecovery("run").recovery, other);
  clearWorkspaceRecovery("run", other);
  assert.equal(readWorkspaceRecovery("run").recovery, null);
});

test("corrupt recovery is rejected and storage failure is explicit", (context) => {
  const values = storage(context), key = "silicon-agent.workspace.run";
  for (const value of ["{bad", JSON.stringify({ ...recovery, version: 7 }), JSON.stringify({ ...recovery, revision: -1 }), JSON.stringify({ ...recovery, files: { "src/chip.v": 9 } })]) {
    values.set(key, value); assert.equal(readWorkspaceRecovery("run").recovery, null);
  }
  assert.equal(saveWorkspaceRecovery("run", { ...recovery, files: { "../bad": "data" } }), false);
  localStorage.setItem = () => { throw new Error("Full"); };
  assert.equal(saveWorkspaceRecovery("run", recovery), false);
  localStorage.getItem = () => { throw new Error("Blocked"); };
  assert.deepEqual(readWorkspaceRecovery("run"), { recovery: null, available: false });
});

test("oversized edits cannot claim successful recovery and preserve the previous recovery copy", (context) => {
  storage(context);
  assert.equal(saveWorkspaceRecovery("run", recovery), true);
  const oversized = { ...recovery, files: { ...files, "src/counter.v": "x".repeat(128 * 1024 + 1) } };
  assert.equal(saveWorkspaceRecovery("run", oversized), false);
  assert.deepEqual(readWorkspaceRecovery("run").recovery, recovery);
});

test("draft saves use revision preconditions and preserve conflict responses", async (context) => {
  let request;
  context.mock.method(globalThis, "fetch", async (path, options) => { request = { path, options }; return new Response(JSON.stringify({ detail: "A newer draft was saved." }), { status: 409 }); });
  await assert.rejects(saveWorkspace("a/b", files, 3, working), (error) => error.status === 409 && error.message === "A newer draft was saved.");
  assert.equal(request.path, "/api/runs/a%2Fb/workspace");
  assert.equal(request.options.headers["X-Silicon-Request"], "1");
  assert.deepEqual(JSON.parse(request.options.body), { files, expected_revision: 3, base_source: working });
});

test("source lookups retain their exact run and flow selectors", async (context) => {
  const paths = [];
  context.mock.method(globalThis, "fetch", async (path) => { paths.push(path); return new Response(JSON.stringify({ available: false, files: {}, reason: "Unavailable", provenance: "unavailable", run_tag: null, event_id: null })); });
  await getFlowSources("run/a", { runTag: "flow/b" });
  await getFlowSources("run/a", { eventId: 42 });
  assert.deepEqual(paths, ["/api/runs/run%2Fa/sources?run_tag=flow%2Fb", "/api/runs/run%2Fa/sources?event_id=42"]);
});

test("flow choices preserve the actual selected tag from measured recording evidence", () => {
  const choices = workspaceFlows(recording.run, recording.events, recording.metrics);
  assert.equal(choices.filter((choice) => choice.selected).length, 1);
  assert.equal(choices.find((choice) => choice.selected).tag, recording.run.best_run_tag);
  const tags = choices.flatMap((choice) => choice.tag ? [choice.tag] : []);
  assert.equal(new Set(tags).size, tags.length);
});
