import { getJson, type BuildConfig, type Metric } from "./api";

export interface FlowConfig {
  CLOCK_PERIOD?: number; SYNTH_STRATEGY?: string; FP_CORE_UTIL?: number;
  PL_TARGET_DENSITY_PCT?: number; DIE_AREA?: number[];
}
export interface FlowChecks {
  setup_wns_ns: number | null; hold_wns_ns: number | null;
  setup_violations: number | null; hold_violations: number | null;
  max_slew_violations: number | null; max_cap_violations: number | null;
  max_fanout_violations: number | null; antenna_violating_nets: number | null;
  antenna_violating_pins: number | null; violating_corners: Record<string, string[]>;
}
export interface FlowReport { available: boolean; excerpt: string | null; truncated: boolean }
export interface FlowDetail {
  event_id: number | null; tool_call_id: string | null; run_tag: string | null;
  status: "running" | "passed" | "failed" | "interrupted" | "unknown";
  selected: boolean; is_replay: boolean; physical_flow_started: boolean | null;
  requested_config: FlowConfig | null; planned_config: FlowConfig | null;
  applied_config: FlowConfig | null; resolved_config: FlowConfig | null;
  metrics: (Omit<Metric, "id" | "run_id" | "iteration_id" | "flow_index"> & { tns_ns: number }) | null;
  diagnostic: { kind: string; message: string } | null;
  signoff: { drc_ok: boolean | null; lvs_ok: boolean | null; drv_ok: boolean | null; gls_ok: boolean | null; checks: FlowChecks };
  provenance: {
    evidence_status: "verified" | "unavailable" | "invalid";
    execution_id: string | null; image_id: string | null; source_sha256: string | null;
    input_sha256: string | null; duration_seconds: number | null; snapshot_available: boolean;
  };
  reports: Record<"log" | "timing" | "area" | "power" | "drc", FlowReport>;
  warnings: string[];
}

export type FlowSelector = { eventId: number } | { runTag: string };
export async function getFlowDetail(runId: string, selector: FlowSelector, signal?: AbortSignal) {
  const query = "eventId" in selector ? `event_id=${selector.eventId}` : `run_tag=${encodeURIComponent(selector.runTag)}`;
  const detail = await getJson<FlowDetail>(`/api/runs/${encodeURIComponent(runId)}/flow?${query}`, signal);
  if (!detail || !detail.signoff?.checks?.violating_corners || !detail.provenance || !detail.reports || !Array.isArray(detail.warnings)) {
    throw new Error("The server did not return a complete flow evidence record.");
  }
  return detail;
}

export function reusableFlowSettings(detail: FlowDetail): { source: string; settings: BuildConfig["initial_flow"] } | null {
  if (detail.provenance.evidence_status === "invalid") return null;
  const source = detail.resolved_config !== null ? "resolved" : detail.applied_config !== null ? "applied" : "planned";
  const config = detail.resolved_config ?? detail.applied_config ?? detail.planned_config;
  if (!config) return null;
  const settings: BuildConfig["initial_flow"] = {};
  if (typeof config.SYNTH_STRATEGY === "string" && /^(AREA [0-3]|DELAY [0-4])$/.test(config.SYNTH_STRATEGY)) settings.SYNTH_STRATEGY = config.SYNTH_STRATEGY;
  for (const key of ["FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT"] as const) {
    const value = config[key];
    if (typeof value === "number" && Number.isFinite(value) && value >= 1 && value <= 90) settings[key] = value;
  }
  return Object.keys(settings).length ? { source, settings } : null;
}
