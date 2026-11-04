import { ApiError, getJson, type Metric, type PublicRun, type RunEvent } from "./api";
import { flowVariants, runActivity } from "./run-activity";
import { isTerminal } from "./run-state";
import type { FlowSelector } from "./flow-inspection";

export type WorkspaceFiles = Record<string, string>;
export interface WorkspaceSource { kind: "working" | "flow"; run_tag: string | null; event_id: number | null }
export interface WorkspaceDraft { files: WorkspaceFiles | null; updated_at: string | null; revision: number; base_source: WorkspaceSource | null }
export interface FlowSources { available: boolean; files: WorkspaceFiles; run_tag: string | null; event_id: number | null; provenance: "flow_snapshot" | "selected_bundle" | "unavailable"; reason: string | null }
export interface WorkspaceFlow { key: string; label: string; tag: string | null; selector: FlowSelector; selected: boolean }
export interface WorkspaceRecovery { version: 1; revision: number; files: WorkspaceFiles; base_source: WorkspaceSource | null }

const workspacePath = (id: string) => `/api/runs/${encodeURIComponent(id)}/workspace`;
export const getWorkspace = (id: string, signal?: AbortSignal) => getJson<WorkspaceDraft>(workspacePath(id), signal);
export async function saveWorkspace(id: string, files: WorkspaceFiles, expectedRevision: number, source: WorkspaceSource | null) {
  const response = await fetch(workspacePath(id), {
    method: "PUT", cache: "no-store", headers: { "Content-Type": "application/json", "X-Silicon-Request": "1" },
    body: JSON.stringify({ files, expected_revision: expectedRevision, base_source: source }),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, typeof body?.detail === "string" ? body.detail : `Workspace could not be saved (${response.status}).`);
  return body as WorkspaceDraft;
}
export const getFlowSources = (id: string, selector: FlowSelector, signal?: AbortSignal) => getJson<FlowSources>(
  `/api/runs/${encodeURIComponent(id)}/sources?${"eventId" in selector ? `event_id=${selector.eventId}` : `run_tag=${encodeURIComponent(selector.runTag)}`}`, signal,
);

export const workspaceFilePattern = /^(src\/[A-Za-z_][A-Za-z0-9_]{0,127}\.v|test\/[A-Za-z_][A-Za-z0-9_]{0,127}\.py)$/;
export function validateWorkspace(files: WorkspaceFiles): string[] {
  const entries = Object.entries(files), errors: string[] = [];
  if (entries.length > 64) errors.push("Keep the workspace within 64 files.");
  let size = 0;
  for (const [path, content] of entries) {
    if (!workspaceFilePattern.test(path)) errors.push(`${path}: use src/name.v or test/name.py, with letters, numbers, and underscores.`);
    const bytes = new TextEncoder().encode(content).length;
    size += bytes;
    if (bytes > 128 * 1024) errors.push(`${path} exceeds 128 KiB.`);
    if (content.includes("\0")) errors.push(`${path} contains a null character.`);
  }
  if (size > 2 * 1024 * 1024) errors.push("Keep the workspace within 2 MiB in total.");
  return errors;
}
export function workspaceBuildProblems(run: PublicRun, files: WorkspaceFiles, mode: "agent" | "manual"): string[] {
  const errors = validateWorkspace(files);
  if (!isTerminal(run.status)) errors.push("Wait for the parent run to finish or stop before building edited files.");
  if (!run.design_spec) errors.push("This run has no accepted design specification to build against.");
  if (run.review_requested && !run.review_submitted) errors.push("The previous design review was not accepted. Complete an accepted design before building edited files.");
  if (!Object.keys(files).some((path) => path.startsWith("src/") && files[path].trim())) errors.push("Add at least one nonempty Verilog file in src/.");
  if (mode === "manual" && !Object.keys(files).some((path) => path.startsWith("test/") && files[path].trim())) errors.push("Add one nonempty Python test file in test/ for verification without AI changes.");
  if (mode === "manual" && Object.keys(files).filter((path) => path.startsWith("test/")).length > 1) errors.push("Verification without AI changes currently requires exactly one test module. Drafts may contain more files.");
  return errors;
}
export function workspaceFingerprint(files: WorkspaceFiles, source: WorkspaceSource | null): string {
  return JSON.stringify({ files: Object.entries(files).sort(([a], [b]) => a.localeCompare(b)), source });
}
const recoveryKey = (id: string) => `silicon-agent.workspace.${id}`;
export function readWorkspaceRecovery(id: string): { recovery: WorkspaceRecovery | null; available: boolean } {
  try {
    const raw = localStorage.getItem(recoveryKey(id));
    if (!raw || raw.length > 12 * 1024 * 1024) return { recovery: null, available: true };
    const value = JSON.parse(raw) as WorkspaceRecovery;
    if (value.version !== 1 || !Number.isInteger(value.revision) || value.revision < 0 || !value.files || typeof value.files !== "object" || Array.isArray(value.files) || Object.values(value.files).some((content) => typeof content !== "string") || validateWorkspace(value.files).length) return { recovery: null, available: true };
    const source = value.base_source;
    if (source !== null && (!source || !["working", "flow"].includes(source.kind) || (source.run_tag !== null && typeof source.run_tag !== "string") || (source.event_id !== null && !Number.isInteger(source.event_id)))) return { recovery: null, available: true };
    return { recovery: value, available: true };
  } catch { return { recovery: null, available: false }; }
}
export function saveWorkspaceRecovery(id: string, value: WorkspaceRecovery): boolean {
  if (validateWorkspace(value.files).length) return false;
  try { localStorage.setItem(recoveryKey(id), JSON.stringify(value)); return true; } catch { return false; }
}
export function clearWorkspaceRecovery(id: string, expected: WorkspaceRecovery | null): boolean {
  try {
    if (expected && localStorage.getItem(recoveryKey(id)) === JSON.stringify(expected)) localStorage.removeItem(recoveryKey(id));
    return true;
  } catch { return false; }
}
export function workspaceFlows(run: PublicRun, events: RunEvent[], metrics: Metric[]): WorkspaceFlow[] {
  const variants = flowVariants(runActivity(events), metrics, events, isTerminal(run.status));
  const result: WorkspaceFlow[] = [];
  const tags = new Set<string>();
  for (const variant of variants) {
    const event = variant.span?.finishedOrder ?? variant.span?.order;
    const tag = variant.metric?.run_tag ?? (typeof variant.span?.result?.run_tag === "string" ? variant.span.result.run_tag : null);
    if (!tag && event === undefined) continue;
    if (tag && tags.has(tag)) continue;
    if (tag) tags.add(tag);
    const selected = !!tag && tag === run.best_run_tag;
    result.push({ key: tag ? `tag:${tag}` : `event:${event}`, tag, selected,
      label: `${variant.metric ? `Flow ${variant.metric.flow_index}` : `Attempt ${event}`}${selected ? " · selected" : ""}${tag ? ` · ${tag}` : ""}`,
      selector: event !== undefined ? { eventId: event } : { runTag: tag! },
    });
  }
  if (run.best_run_tag && !tags.has(run.best_run_tag)) result.unshift({ key: `tag:${run.best_run_tag}`, tag: run.best_run_tag, selected: true, label: `Selected flow · ${run.best_run_tag}`, selector: { runTag: run.best_run_tag } });
  return result;
}
