import type { JsonObject, JsonValue, Metric, RunEvent } from "./api";

// `agent` is "orchestrator" or the model stage role (SPEC, RTL, VERIFY, OPTIMIZE); `order` is the event id.
export interface StageSpan { stage: string; goal: string | null; start: number; end: number | null; previousOk: boolean | null; calls: number; tokens: number; order: number }
export interface ToolSpan { id: string; tool: string; stage: string; agent: string; start: number; end: number | null; ok: boolean | null; result: JsonObject | null; path: string | null; order: number }
export interface ModelCall { calls: number; total: number; responded: boolean; stage: string; agent: string; start: number; end: number; inputTokens: number; outputTokens: number; order: number }
export interface RunNote { kind: "note" | "error"; text: string; detail: string | null; ts: string; at: number; agent: string; order: number }
export interface RunActivity {
  stages: StageSpan[]; tools: ToolSpan[]; modelCalls: ModelCall[]; notes: RunNote[]; repairs: number;
  latestNote: RunNote | null; designSpec: { spec: JsonObject; at: number; order: number } | null;
  active: string | null; start: number | null; end: number | null;
}
export interface FlowVariant { key: string; span: ToolSpan | null; metric: Metric | null; rendered: boolean; status: "running" | "measured" | "failed" | "unfinished" }

const object = (value: JsonValue | undefined): value is JsonObject => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: JsonValue | undefined): string | null => typeof value === "string" ? value : null;
const counter = (value: JsonValue | undefined): number | null => typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
const terminalStages = new Set(["DONE", "FAIL", "FAILED"]);
// Mirrors _ALLOWED in backend/app/agent/orchestrator.py: the tools the model may propose in each stage role.
export const modelTools: Record<string, ReadonlySet<string>> = {
  SPEC: new Set(), RTL: new Set(["write_file", "read_file", "lint", "record_note"]),
  VERIFY: new Set(["write_file", "read_file", "run_tests", "record_note"]),
  OPTIMIZE: new Set(["write_file", "run_tests", "run_flow", "read_report", "record_note"]),
};
export const agentOf = (stage: string): string => stage in modelTools ? stage : "orchestrator";
// A policy rejection is the orchestrator refusing a proposal (_reject); schema_rejection also covers host-side failures.
export const blocked = (span: ToolSpan): boolean => {
  const evidence = span.result?.tool_evidence;
  return object(evidence) && evidence.event === "policy_rejection";
};

// Replays re-emit recorded events at playback speed; their recorded timestamp keeps durations real.
export function eventTime(event: RunEvent): number {
  const source = Date.parse(text(event.payload.source_event_ts) ?? "");
  return Number.isFinite(source) ? source : Date.parse(event.ts);
}

export function runActivity(events: RunEvent[], now?: number): RunActivity {
  // The replay preamble and terminal events carry playback time only; keep them off the recorded clock.
  const replay = events.some((event) => "source_event_ts" in event.payload);
  const timed = replay ? events.filter((event) => typeof event.payload.source_event_ts === "string") : events;
  const stages: StageSpan[] = [], tools: ToolSpan[] = [], modelCalls: ModelCall[] = [], notes: RunNote[] = [], turns = new Map<ToolSpan, string | null>();
  let last: number | null = null, usage = { calls: 0, input: 0, output: 0 }, designSpec: RunActivity["designSpec"] = null;
  // The model role whose latest response proposed the calls now running; any orchestrator call ends it.
  // `acting` marks the orchestrator working on its own inside the current stage visit.
  let turn: string | null = null, acting = false;
  for (const event of timed) {
    const at = eventTime(event), payload = event.payload, open = stages.at(-1);
    const stage = open?.stage ?? "";
    if (event.type === "stage_changed" && typeof payload.stage === "string") {
      if (open && open.end === null) open.end = at;
      const previousOk = typeof payload.previous_ok === "boolean" ? payload.previous_ok : null;
      stages.push({ stage: payload.stage, goal: text(payload.goal), start: at, end: terminalStages.has(payload.stage) ? at : null, previousOk, calls: 0, tokens: 0, order: event.id });
      if (!designSpec && object(payload.design_spec)) designSpec = { spec: payload.design_spec, at, order: event.id };
      // The optimizer's own run_tests executes inside a VERIFY visit and returns to OPTIMIZE (_optimize_round).
      if (!(turn === "OPTIMIZE" && (payload.stage === "VERIFY" || payload.stage === "OPTIMIZE"))) turn = null;
      acting = false;
    } else if (event.type === "tool_started" && typeof payload.tool === "string") {
      const proposed = turn !== null && modelTools[turn].has(payload.tool);
      const span: ToolSpan = { id: String(payload.tool_call_id ?? event.id), tool: payload.tool, stage, agent: proposed ? turn! : "orchestrator", start: at, end: null, ok: null, result: null, path: null, order: event.id };
      tools.push(span);
      turns.set(span, turn);
      if (!proposed) { turn = null; acting = true; }
    } else if (event.type === "tool_finished" && typeof payload.tool === "string") {
      const id = String(payload.tool_call_id ?? event.id);
      let span = tools.find((value) => value.id === id && value.tool === payload.tool && value.end === null);
      if (!span) tools.push(span = { id, tool: payload.tool, stage, agent: "orchestrator", start: at, end: null, ok: null, result: null, path: null, order: event.id });
      span.end = at;
      span.result = object(payload.result) ? payload.result : null;
      span.ok = typeof span.result?.ok === "boolean" ? span.result.ok : null;
      if (blocked(span) && turns.get(span)) {
        span.agent = turns.get(span)!;
        turn = turns.get(span)!;
        acting = false;
      }
    } else if (event.type === "file_written" && typeof payload.path === "string") {
      const writer = tools.findLast((value) => value.tool === "write_file" && value.end === null);
      if (writer) writer.path = payload.path;
    } else if (event.type === "cost_update") {
      const calls = counter(payload.calls), input = counter(payload.input_tokens), output = counter(payload.output_tokens);
      if (calls !== null && calls > usage.calls) {
        const call: ModelCall = { calls: calls - usage.calls, total: calls, responded: false, stage, agent: agentOf(stage), start: Math.min(last ?? at, at), end: at, inputTokens: Math.max(0, (input ?? usage.input) - usage.input), outputTokens: Math.max(0, (output ?? usage.output) - usage.output), order: event.id };
        // Budget.calls counts attempts before the request; only new tokens prove a response arrived.
        call.responded = call.inputTokens + call.outputTokens > 0;
        modelCalls.push(call);
        if (call.responded) { turn = call.agent === "orchestrator" ? null : call.agent; acting = false; }
        if (open) { open.calls += call.calls; open.tokens += call.inputTokens + call.outputTokens; }
      }
      usage = { calls: Math.max(usage.calls, calls ?? 0), input: Math.max(usage.input, input ?? 0), output: Math.max(usage.output, output ?? 0) };
    } else if (event.type === "note" && typeof payload.text === "string" && stages.length) { // The queue note precedes every stage.
      const writer = tools.findLast((span) => span.tool === "record_note" && span.end === null);
      notes.push({ kind: "note", text: payload.text, detail: null, ts: event.ts, at, agent: writer?.agent ?? ("scope_assessment" in payload ? "SPEC" : "orchestrator"), order: event.id });
    } else if (event.type === "error" && typeof payload.message === "string") {
      notes.push({ kind: "error", text: payload.message, detail: text(payload.suggested_action), ts: event.ts, at, agent: "orchestrator", order: event.id });
    }
    if (Number.isFinite(at)) last = Math.max(last ?? at, at);
  }
  const start = stages[0]?.start ?? tools[0]?.start ?? null;
  const end = last === null ? null : Math.max(last, replay || now === undefined ? last : now);
  const current = stages.at(-1)?.stage;
  return {
    stages, tools, modelCalls, notes, repairs: stages.filter((span) => span.stage === "RTL" && span.previousOk === false).length,
    latestNote: notes.findLast((note) => note.kind === "note") ?? null, designSpec,
    active: turn ?? (current === undefined ? null : acting ? "orchestrator" : agentOf(current)), start, end,
  };
}

export function flowVariants(activity: RunActivity, metrics: Metric[], events: RunEvent[], terminal: boolean): FlowVariant[] {
  const rendered = new Set(events.flatMap((event) => event.type === "layout_rendered" && typeof event.payload.run_tag === "string" ? [event.payload.run_tag] : []));
  const byTag = new Map(metrics.map((metric) => [metric.run_tag, metric]));
  // Only an open call or a returned run_tag evidences a LibreLane run; rejected and preflight-failed calls stay tool calls.
  const variants: FlowVariant[] = activity.tools.flatMap((span, index) => span.tool === "run_flow" && (span.end === null || text(span.result?.run_tag)) ? [{ span, index }] : []).map(({ span, index }) => {
    const tag = text(span.result?.run_tag);
    const metric = tag ? byTag.get(tag) ?? null : null;
    if (tag) byTag.delete(tag);
    const status = span.end === null ? terminal ? "unfinished" : "running" : metric ? "measured" : "failed";
    return { key: `flow-${index}`, span, metric, rendered: tag !== null && rendered.has(tag), status };
  });
  // A metric whose flow events are missing is still a real measurement; never drop it.
  for (const metric of byTag.values()) variants.push({ key: metric.run_tag, span: null, metric, rendered: rendered.has(metric.run_tag), status: "measured" });
  // Concurrent flows finish in any order; measured ones read best in the backend's flow_index order.
  return variants.toSorted((a, b) => (a.metric?.flow_index ?? Number.MAX_SAFE_INTEGER) - (b.metric?.flow_index ?? Number.MAX_SAFE_INTEGER));
}

export function toolSummary(span: ToolSpan): string | null {
  const result = span.result;
  // Tool output is often tail-truncated; skip the truncation marker and banner rules to the first readable line.
  const error = (text(result?.first_error) ?? text(result?.error))?.split("\n").find((line) => /\w/.test(line) && !line.startsWith("[truncated"))?.trim().slice(0, 160);
  const passed = counter(result?.passed), failed = counter(result?.failed), skipped = counter(result?.skipped) ?? 0;
  // A run can fail with no failing case (stale source, harness proof, bad XML); then the reason matters more than the counts.
  if (span.tool === "run_tests" && passed !== null && failed !== null) return `${passed}/${passed + failed + skipped} passed${skipped ? ` · ${skipped} skipped` : ""}${span.ok === false && failed === 0 && error ? ` · ${error}` : ""}`;
  if (span.ok === false && error) return error;
  if (span.tool === "write_file" || span.tool === "read_file") return span.path;
  if (!result) return null;
  if (span.tool === "lint" && Array.isArray(result.errors)) return result.errors.length ? `${result.errors.length} errors` : Array.isArray(result.warnings) && result.warnings.length ? `clean · ${result.warnings.length} warnings` : "clean";
  if (span.tool === "synth_stats" && counter(result.cell_count) !== null) return `${result.cell_count} cells`;
  if (span.tool === "run_flow") return text(result.run_tag);
  return null;
}
