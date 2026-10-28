import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
const require = createRequire(import.meta.url);
const __dirname = dirname(fileURLToPath(import.meta.url));
/* Pure UI/contract checks only. No server, browser, provider, EDA or private data. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const frontend = createRequire(path.join(__dirname, "../package.json"));
// Installed TS7 CLI exposes no transpile API; this existing dependency supplies
// the TS5.8 transpile API solely for these pure component checks.
const ts = frontend("@ts-morph/common/dist/typescript.js");
const React = frontend("react");
const { renderToStaticMarkup } = frontend("react-dom/server");
const root = path.join(__dirname, "..");
const loaded = new Map();
function load(relative) {
  if (loaded.has(relative)) return loaded.get(relative);
  const filename = path.join(root, relative);
  const result = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2021, esModuleInterop: true },
    fileName: filename,
  });
  const module = { exports: {} };
  const localRequire = (id) => id.endsWith(".css") ? { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) }
    : id === "../lib/reliability" ? load("lib/reliability.ts")
    : id.startsWith("@/") ? load(["tsx", "ts"].map((ext) => `${id.slice(2)}.${ext}`).find((file) => fs.existsSync(path.join(root, file)))) : frontend(id);
  new Function("require", "module", "exports", result.outputText)(localRequire, module, module.exports);
  loaded.set(relative, module.exports);
  return module.exports;
}
const lib = load("lib/reliability.ts");
const ui = load("components/reliability-dashboard.tsx");
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/reliability.actual.json"), "utf8"));
const fresh = () => structuredClone(fixture);
const selected = fixture.cohorts.find((cohort) => cohort.report.successful === 86);
assert.ok(selected, "Approved actual fixture must contain the 86/90 aggregate");
const render = (data = fixture, id = selected.cohort_id) => renderToStaticMarkup(React.createElement(ui.ReliabilityView, { data, selectedId: id, onSelect() {}, onReload() {} }));
const state = (kind) => renderToStaticMarkup(React.createElement(ui.ReliabilityState, { kind, onRetry() {} }));
const rejects = (mutate) => { const data = fresh(); mutate(data); assert.throws(() => lib.parseReliabilityResponse(data), /Unsupported public/); };
function regroup(data) {
  const groups = new Map();
  for (const cohort of [...data.cohorts].sort((a, b) => a.cohort_id < b.cohort_id ? -1 : 1)) {
    const key = cohort.report.comparison_group_sha256;
    if (!groups.has(key)) groups.set(key, { comparison_group_sha256: key, cohort_ids: [], tier_trends: {} });
    const group = groups.get(key); group.cohort_ids.push(cohort.cohort_id);
    for (const [tier, report] of Object.entries(cohort.report.tiers)) (group.tier_trends[tier] ??= []).push({ cohort_id: cohort.cohort_id, pipeline_sha256: cohort.report.pipeline_sha256, success_rate: report.success_rate });
  }
  data.comparison_groups = [...groups.values()];
}

test("approved three-cohort public fixture matches the exact response contract", () => {
  assert.equal(lib.parseReliabilityResponse(fixture), fixture);
  assert.equal(fixture.cohorts.length, 3);
  assert.equal(fixture.comparison_groups.length, 1);
  assert.equal(selected.report.planned, 90);
  assert.equal(selected.report.hardware_survival_funnel[0].count, 72);
});
test("selector includes all published cohorts and selects the requested aggregate", () => {
  const html = render();
  assert.equal((html.match(/<option /g) ?? []).length, 3);
  assert.ok(html.includes(`value="${selected.cohort_id}" selected=""`));
  assert.ok(html.includes("86/90 successful trials"));
  for (const cohort of fixture.cohorts) assert.ok(render(fixture, cohort.cohort_id).includes(`${cohort.report.successful}/90 successful trials`));
});
test("hardware funnel excludes scope and preserves independently different hidden counts", () => {
  const html = render();
  assert.ok(html.includes("CUMULATIVE · 72 TRIALS"));
  assert.ok(html.includes("T4 scope cases are excluded"));
  const bound = selected.report.hardware_survival_funnel.at(-1).count;
  const hidden = selected.report.independent_stage_checks.hidden.pass;
  assert.equal(bound, 68); assert.equal(hidden, 69);
  assert.match(html, /Bound hidden pass<\/span>.*?<strong[^>]*>68<small[^>]*>\/72<\/small>/);
  assert.match(html, /<th[^>]*scope="row"[^>]*>Hidden checks<\/th><td[^>]*>69<\/td>/);
});
test("tier ranges are labeled observed min–max without invented tier meanings", () => {
  const html = render();
  assert.ok(html.includes("Tier 3"));
  assert.ok(html.includes("66.7%–83.3% across 3 repeats"));
  assert.ok(html.includes("empirical ranges"));
  assert.ok(!html.includes("confidence interval"));
  assert.ok(!html.includes("Foundations"));
});
test("all-unknown USD stays unknown and is not plotted as zero", () => {
  const html = render();
  assert.ok(html.includes("90/90 trials unpriced"));
  assert.ok(html.includes("0 known · 90 unknown"));
  assert.ok(html.includes("No known USD measurements"));
  assert.match(html, /Total USD<\/span><strong data-unknown="true"[^>]*>Unknown/);
  assert.equal(lib.money(null), "Unknown");
  assert.equal(lib.money(0), "$0.00");
  assert.equal(lib.money(0.00001), "<$0.0001");
});
test("partial known USD is labeled as a subset while the full total stays unknown", () => {
  const data = fresh(), cohort = data.cohorts.find((c) => c.cohort_id === selected.cohort_id), r = cohort.report;
  function mixedCost(n) { return { assessable: false, known_trials: 2, unknown_attempted_trials: n - 2, total_usd: null, median_usd: null, known_subset: { count: 2, mean: 0.5, median: 0.5, min: 0, max: 1, total_usd: 1 } }; }
  r.cost = mixedCost(r.planned); r.tiers["1"].cost = mixedCost(r.tiers["1"].planned);
  r.known_cost_distribution_usd = [0, 1]; r.unknown_cost_trials = 88;
  lib.parseReliabilityResponse(data);
  const html = render(data, cohort.cohort_id);
  assert.match(html, /Total USD<\/span><strong data-unknown="true"[^>]*>Unknown/);
  assert.ok(html.includes("Known subset $1.00 · 2 trials"));
  assert.ok(html.includes("2 known · 88 unknown"));
  assert.ok(html.includes("88/90 trials unpriced"));
});
test("histograms retain genuine zero measurements and count missing values separately", () => {
  assert.deepEqual(lib.histogram([null, 0, 0]), { bins: [{ from: 0, to: 0, count: 2 }], known: 2, unknown: 1 });
  assert.deepEqual(lib.histogram([null, null]), { bins: [], known: 0, unknown: 2 });
  const spread = lib.histogram([0, 1, 2, 3, null], 2);
  assert.equal(spread.bins.reduce((n, bin) => n + bin.count, 0), 4);
  assert.equal(spread.bins.at(-1).to, 3);
});
test("comparison excludes a synthetic unlike group and selected singleton shows no trend", () => {
  const data = fresh();
  data.cohorts[0].report.comparison_group_sha256 = "f".repeat(64);
  regroup(data);
  lib.parseReliabilityResponse(data);
  const chosen = data.cohorts[0];
  assert.deepEqual(lib.peers(data, chosen).map((c) => c.cohort_id), [chosen.cohort_id]);
  assert.ok(render(data, chosen.cohort_id).includes("One cohort is published in this comparison group"));
  const other = data.cohorts[1];
  assert.equal(lib.peers(data, other).length, 2);
  assert.ok(!lib.peers(data, other).some((c) => c.cohort_id === chosen.cohort_id));
});
test("response rejects extra private-looking keys and unsupported versions", () => {
  rejects((d) => d.raw_eval_path = "/private/should-never-render");
  rejects((d) => d.schema_version = 2);
  rejects((d) => d.cohorts[0].report.split = "hidden");
});
test("response rejects silently imputed zero USD and broken observed ranges", () => {
  rejects((d) => d.cohorts[0].report.cost.total_usd = 0);
  rejects((d) => d.cohorts[0].report.tiers["1"].repeat_success_rates.max = 2);
  rejects((d) => d.cohorts[0].report.pipeline_time_seconds.mean = Number.MAX_VALUE);
});
test("response rejects broken stage denominators and noncumulative hardware counts", () => {
  rejects((d) => d.cohorts[0].report.independent_stage_checks.hidden.pass += 1);
  rejects((d) => d.cohorts[0].report.hardware_survival_funnel[2].count = 73);
});
test("response rejects incomplete, duplicate or mixed comparison membership", () => {
  rejects((d) => d.comparison_groups[0].cohort_ids.pop());
  rejects((d) => d.comparison_groups[0].tier_trends["1"].pop());
  rejects((d) => d.comparison_groups[0].tier_trends["1"][1] = d.comparison_groups[0].tier_trends["1"][0]);
  rejects((d) => d.cohorts[0].report.comparison_group_sha256 = "a".repeat(64));
});
test("published original failure classes must match the exact sorted aggregate", () => {
  rejects((d) => d.top_original_failure_classes[d.cohorts[0].cohort_id] = []);
  rejects((d) => d.top_original_failure_classes[d.cohorts[0].cohort_id][0].count += 1);
});
test("enabled empty response shows empty copy without invented data", () => {
  const empty = lib.parseReliabilityResponse({ schema_version: 1, state: "empty", cohorts: [], comparison_groups: [], top_original_failure_classes: {} });
  assert.ok(render(empty, "").includes("No sealed DEV cohorts published"));
  rejects((d) => d.state = "empty");
});
test("loading, error and disabled/not-found copy remain generic", () => {
  assert.ok(state("loading").includes("aria-busy=\"true\""));
  assert.ok(state("error").includes("role=\"alert\""));
  assert.ok(state("error").includes("No cohort data is shown"));
  assert.ok(state("not-found").includes("Reliability view not found"));
  for (const kind of ["loading", "empty", "error", "not-found"]) assert.ok(!state(kind).includes("eval/results"));
});
test("scope-only synthetic response has no divide-by-zero or fabricated tier values", () => {
  const data = fresh(); data.cohorts = [data.cohorts[0]];
  const cohort = data.cohorts[0], r = cohort.report, t = r.tiers["4"];
  r.tiers = { "4": t }; r.planned = t.planned; r.successful = t.successful; r.success_rate = t.success_rate;
  r.cost = structuredClone(t.cost); r.pipeline_time_seconds = structuredClone(t.pipeline_time_seconds);
  r.time_distribution_seconds = r.time_distribution_seconds.slice(0, r.planned); r.unknown_cost_trials = r.planned;
  r.hardware_survival_funnel.forEach((row) => row.count = 0);
  for (const row of Object.values(r.independent_stage_checks)) for (const status of lib.STATUSES) row[status] = status === "not_applicable" ? r.planned : 0;
  r.failure_counts = {}; data.top_original_failure_classes = { [cohort.cohort_id]: [] }; regroup(data);
  lib.parseReliabilityResponse(data);
  const html = render(data, cohort.cohort_id);
  assert.ok(html.includes("No hardware trials were included"));
  assert.equal((html.match(/Not included in this cohort/g) ?? []).length, 3);
  assert.ok(!html.includes("NaN")); assert.ok(!html.includes("Infinity"));
});
test("fixed public endpoint, no-store and caller AbortSignal are preserved", async () => {
  const original = global.fetch, controller = new AbortController();
  try {
    global.fetch = async (url, options) => {
      assert.equal(url, "/api/admin/reliability"); assert.equal(options.cache, "no-store"); assert.equal(options.signal, controller.signal);
      return { ok: true, json: async () => fresh() };
    };
    assert.equal((await lib.fetchReliability(controller.signal)).cohorts.length, 3);
  } finally { global.fetch = original; }
});
test("404 and corrupt-export 503 remain distinct status errors with no raw body", async () => {
  const original = global.fetch;
  try {
    for (const status of [404, 503]) {
      global.fetch = async () => ({ ok: false, status, json: async () => { throw new Error("private path should not be read"); } });
      await assert.rejects(lib.fetchReliability(new AbortController().signal), (error) => error instanceof lib.ReliabilityApiError && error.status === status && !error.message.includes("private"));
    }
  } finally { global.fetch = original; }
});
test("invalid public JSON and cancelled requests propagate without fallback data", async () => {
  const original = global.fetch;
  try {
    global.fetch = async () => ({ ok: true, json: async () => ({ state: "ready", private: "not rendered" }) });
    await assert.rejects(lib.fetchReliability(new AbortController().signal), /Unsupported public/);
    const cancelled = new DOMException("cancelled", "AbortError");
    global.fetch = async () => { throw cancelled; };
    await assert.rejects(lib.fetchReliability(new AbortController().signal), (error) => error === cancelled);
  } finally { global.fetch = original; }
});
