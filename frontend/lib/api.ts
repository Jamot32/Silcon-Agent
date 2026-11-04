export interface Check { status: string; detail: string }
export interface Health {
  status: "ok" | "degraded";
  checks: { database: Check; eda: Check; llm: Check };
  milestone: string;
  llm_provider: string;
}
export interface Preset { id: string; name: string; spec_text: string }
export interface Recording {
  id: string; name: string; description: string; source_run_id: string;
  duration_seconds: number; event_count: number; flow_count: number;
}

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };
export interface Targets { clock_mhz?: number | null; max_area_um2?: number | null; fit?: "tt_1x1_tile" | null }
export interface Port { name: string; direction: "input" | "output"; width: number; description: string }
export interface DesignSpec {
  top_module: string; summary: string; ports: Port[]; behavior: string[];
  targets: Targets; test_plan: string[]; purely_combinational: boolean;
}
export interface PublicRun {
  id: string; spec_text: string; design_spec: DesignSpec | null; targets: Targets;
  preset_id: string | null; status: string; stage: string; created_at: string;
  cost_usd: number | null; input_tokens: number; output_tokens: number; call_count: number;
  llm_provider: string; is_replay: boolean; summary: string | null; error: string | null;
  best_run_tag: string | null; tapeout_ready: boolean;
  recording_id: string | null; replay_speed: number | null; starter_id: string | null;
  parent_run_id: string | null; carried_files: string[];
  review_requested: boolean; review_submitted: boolean;
}
export type FlowKnob = "SYNTH_STRATEGY" | "FP_CORE_UTIL" | "PL_TARGET_DENSITY_PCT";
// Mirrors BuildConfig in backend/app/schemas.py; the orchestrator sends its defaults with each review request.
export interface BuildConfig {
  optimize: boolean; max_flow_runs: number; max_repair_loops: number;
  initial_flow: { SYNTH_STRATEGY?: string; FP_CORE_UTIL?: number; PL_TARGET_DENSITY_PCT?: number };
}
export interface ReviewRequest { design_spec: DesignSpec; build: BuildConfig; locked: string[] }
export type Run = PublicRun;
export interface Metric {
  id?: string; run_id?: string; iteration_id?: string;
  run_tag: string; flow_index: number; clock_mhz: number; area_um2: number;
  wns_ns: number; tns_ns: number; power_mw: number; cell_count: number;
  drc_ok: boolean | null; lvs_ok: boolean | null;
}
export const RUN_EVENT_TYPES = [
  "stage_changed", "tool_started", "tool_finished", "file_written", "test_result",
  "metric_recorded", "layout_rendered", "note", "cost_update", "run_finished", "error",
] as const;
export type RunEventType = typeof RUN_EVENT_TYPES[number];
export interface RunEvent { id: number; ts: string; type: RunEventType; payload: JsonObject }
export interface TestFailure { test: string; message: string; log_tail?: string }
export interface TestCase { test: string; ok: boolean | null; message?: string }
export interface TestResults {
  ok: boolean; passed?: number; failed?: number; skipped?: number;
  failures?: TestFailure[]; cases?: TestCase[]; error?: string; first_error?: string;
  event_id?: number; ts?: string;
}
export interface Layout { run_tag: string; image_url: string; clock_mhz?: number; width?: number; height?: number; event_id?: number }
export interface FileDiff { path: string; diff: string; before: string | null; after: string | null; event_id: number; ts: string }
export interface CreateRunInput {
  spec_text: string; preset_id?: string; targets?: Targets; starter_id?: "uart_off_by_one";
  parent_run_id?: string; reuse_design?: boolean; review?: boolean;
}
export interface CreateReplayInput { recording_id: string; speed: 1 | 4 }
export interface ServerSettings {
  provider: string; model: string; reasoning_effort: string | null;
  max_calls: number; max_tokens: number | null; budget_usd: number;
}
export type SubscriptionStatus = "connected" | "signed_out" | "api_key" | "unavailable" | "unknown";
export interface ProviderConnection {
  provider: string; source: "saved" | "environment" | "none";
  configured: boolean; build_supported: boolean;
}
export interface Connections {
  keys: ProviderConnection[];
  subscriptions: { codex: SubscriptionStatus; claude: SubscriptionStatus; checked_at: number };
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function errorDetail(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail.flatMap((entry: unknown) => {
        if (!entry || typeof entry !== "object" || !("msg" in entry) || typeof entry.msg !== "string") return [];
        // Name the failing field (without FastAPI's "body" root) so a long form says where to look.
        const where = "loc" in entry && Array.isArray(entry.loc) ? entry.loc.filter((part) => part !== "body").join(".") : "";
        const message = entry.msg.replace(/^Value error, /, "");
        return [where ? `${where}: ${message}` : message];
      });
      if (messages.length) return messages.join("; ");
    }
  }
  return `Request failed (${status})`;
}

async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, cache: "no-store" });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, errorDetail(body, response.status));
  }
  return response.json() as Promise<T>;
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, { signal });
}

const runPath = (id: string) => `/api/runs/${encodeURIComponent(id)}`;
// The API rejects state-changing and credential requests without this header; a cross-site page cannot send it.
const appHeaders = { "X-Silicon-Request": "1" };
const jsonHeaders = { ...appHeaders, "Content-Type": "application/json" };
export const getRun = (id: string, signal?: AbortSignal) => getJson<PublicRun>(runPath(id), signal);
export const listRuns = (signal?: AbortSignal) => getJson<PublicRun[]>("/api/runs", signal);
export const getSettings = (signal?: AbortSignal) => getJson<ServerSettings>("/api/settings", signal);
export const getConnections = (signal?: AbortSignal) => requestJson<Connections>("/api/settings/connections", { signal, headers: jsonHeaders });
export const saveProviderKey = (provider: string, apiKey: string) => requestJson<ProviderConnection>(`/api/settings/connections/${encodeURIComponent(provider)}`, {
  method: "PUT", headers: jsonHeaders, body: JSON.stringify({ api_key: apiKey }),
});
export const removeProviderKey = (provider: string) => requestJson<ProviderConnection>(`/api/settings/connections/${encodeURIComponent(provider)}`, {
  method: "DELETE", headers: jsonHeaders,
});
export const getRunFiles = (id: string, signal?: AbortSignal) => getJson<Record<string, string>>(`${runPath(id)}/files`, signal);
export const getRunMetrics = (id: string, signal?: AbortSignal) => getJson<Metric[]>(`${runPath(id)}/metrics`, signal);
export const layoutUrl = (id: string, tag: string) => `${runPath(id)}/layout/${encodeURIComponent(tag)}.png`;
export const bundleUrl = (id: string) => `${runPath(id)}/bundle.zip`;
export const eventsUrl = (id: string, after = 0) => `${runPath(id)}/events?after=${after}`;
export const createRun = (body: CreateRunInput, signal?: AbortSignal) => requestJson<{ run_id: string }>("/api/runs", {
  method: "POST", headers: jsonHeaders, body: JSON.stringify(body), signal,
});
export const cancelRun = (id: string, signal?: AbortSignal) => requestJson<PublicRun>(`${runPath(id)}/cancel`, { method: "POST", headers: appHeaders, signal });
export const submitReview = (id: string, body: { design_spec: DesignSpec; build: BuildConfig }, signal?: AbortSignal) => requestJson<PublicRun>(`${runPath(id)}/review`, {
  method: "POST", headers: jsonHeaders, body: JSON.stringify(body), signal,
});

export const createReplay = (body: CreateReplayInput, signal?: AbortSignal) => requestJson<{ run_id: string }>("/api/replays", {
  method: "POST", headers: jsonHeaders, body: JSON.stringify(body), signal,
});
