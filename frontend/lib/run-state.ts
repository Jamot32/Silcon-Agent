import type { FileDiff, JsonObject, Layout, Metric, PublicRun, RunEvent, RunEventType, TestCase, TestFailure, TestResults } from "./api";

export interface RunState {
  run: PublicRun | null; events: RunEvent[]; files: Record<string, string>;
  metrics: Metric[]; latestLayout: Layout | null; testResults: TestResults | null;
  latestDiffs: Record<string, FileDiff>; lastEventId: number;
}
export const emptyRunState = (): RunState => ({ run: null, events: [], files: {}, metrics: [], latestLayout: null, testResults: null, latestDiffs: {}, lastEventId: 0 });
export const isTerminal = (status: string): boolean => ["done", "failed", "cancelled"].includes(status);
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const count = (value: unknown): value is number => finite(value) && Number.isInteger(value) && value >= 0;
const status = (value: unknown): value is boolean | null => value === null || typeof value === "boolean";
const eventTypes = new Set(["stage_changed", "tool_started", "tool_finished", "file_written", "test_result", "metric_recorded", "layout_rendered", "note", "cost_update", "run_finished", "error"]);

export function parseRunEvent(data: string): RunEvent {
  const value: unknown = JSON.parse(data);
  if (!object(value) || !count(value.id) || value.id === 0 || typeof value.ts !== "string" || !Number.isFinite(Date.parse(value.ts)) || typeof value.type !== "string" || !eventTypes.has(value.type) || !object(value.payload)) throw new Error("The live stream returned an invalid event.");
  return { id: value.id, ts: value.ts, type: value.type as RunEventType, payload: value.payload as JsonObject };
}

export function mergeMetrics(current: Metric[], incoming: Metric[]): Metric[] {
  const byTag = new Map(current.map((metric) => [metric.run_tag, metric]));
  for (const metric of incoming) byTag.set(metric.run_tag, { ...byTag.get(metric.run_tag), ...metric });
  return [...byTag.values()].sort((a, b) => a.flow_index - b.flow_index);
}

function metricEvent(event: RunEvent): Metric | null {
  const raw = event.payload.metrics;
  const tag = event.payload.run_tag;
  if (!object(raw) || typeof tag !== "string") return null;
  const index = event.payload.flow_index ?? raw.flow_index;
  if (!count(index) || !finite(raw.clock_mhz) || raw.clock_mhz <= 0 || !finite(raw.area_um2) || raw.area_um2 < 0 || !finite(raw.wns_ns) || !finite(raw.tns_ns) || !finite(raw.power_mw) || raw.power_mw < 0 || !count(raw.cell_count) || !status(raw.drc_ok) || !status(raw.lvs_ok)) return null;
  return { run_tag: tag, flow_index: index, clock_mhz: raw.clock_mhz, area_um2: raw.area_um2, wns_ns: raw.wns_ns, tns_ns: raw.tns_ns, power_mw: raw.power_mw, cell_count: raw.cell_count, drc_ok: raw.drc_ok, lvs_ok: raw.lvs_ok };
}

function testEvent(event: RunEvent): TestResults | null {
  const payload = event.payload;
  if (typeof payload.ok !== "boolean") return null;
  const result: TestResults = { ok: payload.ok, event_id: event.id, ts: event.ts };
  if (count(payload.passed)) result.passed = payload.passed;
  if (count(payload.failed)) result.failed = payload.failed;
  if (count(payload.skipped)) result.skipped = payload.skipped;
  if (typeof payload.error === "string") result.error = payload.error;
  if (typeof payload.first_error === "string") result.first_error = payload.first_error;
  if (Array.isArray(payload.failures)) result.failures = payload.failures.flatMap((failure) => {
    if (!object(failure) || typeof failure.test !== "string" || typeof failure.message !== "string") return [];
    const parsed: TestFailure = { test: failure.test, message: failure.message };
    if (typeof failure.log_tail === "string") parsed.log_tail = failure.log_tail;
    return [parsed];
  });
  if (Array.isArray(payload.cases)) result.cases = payload.cases.flatMap((test) => {
    if (!object(test) || typeof test.test !== "string" || !status(test.ok)) return [];
    const parsed: TestCase = { test: test.test, ok: test.ok };
    if (typeof test.message === "string") parsed.message = test.message;
    return [parsed];
  });
  return result;
}

const lines = (text: string) => text.match(/[^\n]*\n|[^\n]+$/g) ?? [];

export function reverseUnifiedDiff(diff: string, after: string): string | null {
  // A bounded tail is not enough to reconstruct source; never guess missing code.
  const patch = lines(diff);
  if (!patch[0]?.startsWith("--- ") || !patch[1]?.startsWith("+++ ")) return null;
  const modified = lines(after);
  const original: string[] = [];
  let cursor = 0;
  let position = 2;
  let hunks = 0;
  while (position < patch.length) {
    const header = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(patch[position++]);
    if (!header) return null;
    const oldCount = header[2] === undefined ? 1 : Number(header[2]);
    const newCount = header[4] === undefined ? 1 : Number(header[4]);
    const oldStart = Math.max(0, Number(header[1]) - (oldCount === 0 ? 0 : 1));
    const newStart = Math.max(0, Number(header[3]) - (newCount === 0 ? 0 : 1));
    if (newStart < cursor || newStart > modified.length) return null;
    original.push(...modified.slice(cursor, newStart));
    cursor = newStart;
    if (original.length !== oldStart) return null;
    let oldSeen = 0;
    let newSeen = 0;
    while (position < patch.length && !patch[position].startsWith("@@ ")) {
      const line = patch[position++];
      const prefix = line[0];
      if (prefix === " " || prefix === "+") {
        if (modified[cursor] !== line.slice(1)) return null;
        cursor += 1;
        newSeen += 1;
      }
      if (prefix === " " || prefix === "-") {
        original.push(line.slice(1));
        oldSeen += 1;
      } else if (prefix !== "+") return null;
    }
    if (oldSeen !== oldCount || newSeen !== newCount) return null;
    hunks += 1;
  }
  return hunks ? [...original, ...modified.slice(cursor)].join("") : null;
}

export function applySnapshot(state: RunState, snapshot: { run: PublicRun; files: Record<string, string>; metrics: Metric[] }): RunState {
  // SSE history is evidence, not a reason to rewind the authoritative current run.
  return { ...state, run: snapshot.run, files: snapshot.files, metrics: mergeMetrics(state.metrics, snapshot.metrics) };
}

export function reduceRunEvent(state: RunState, event: RunEvent): RunState {
  if (event.id <= state.lastEventId) return state;
  let next: RunState = { ...state, events: [...state.events, event], lastEventId: event.id };
  if (event.type === "metric_recorded") {
    const metric = metricEvent(event);
    if (metric) next.metrics = mergeMetrics(state.metrics, [metric]);
  } else if (event.type === "test_result") {
    next.testResults = testEvent(event) ?? state.testResults;
  } else if (event.type === "file_written") {
    const { path, diff, content } = event.payload;
    if (typeof path === "string" && typeof diff === "string") {
      const after = typeof content === "string" ? content : null;
      const fileDiff: FileDiff = { path, diff, after, before: after === null ? null : reverseUnifiedDiff(diff, after), event_id: event.id, ts: event.ts };
      next.latestDiffs = { ...state.latestDiffs, [path]: fileDiff };
    }
  } else if (event.type === "layout_rendered") {
    const tag = event.payload.run_tag;
    if (typeof tag === "string" && typeof event.payload.image_url === "string") {
      const metric = next.metrics.find((value) => value.run_tag === tag);
      const id = state.run?.id;
      const layout: Layout = { run_tag: tag, image_url: id ? `/api/runs/${encodeURIComponent(id)}/layout/${encodeURIComponent(tag)}.png` : event.payload.image_url, event_id: event.id };
      if (metric) layout.clock_mhz = metric.clock_mhz;
      if (count(event.payload.width) && event.payload.width > 0) layout.width = event.payload.width;
      if (count(event.payload.height) && event.payload.height > 0) layout.height = event.payload.height;
      next.latestLayout = layout;
    }
  }
  return next;
}
