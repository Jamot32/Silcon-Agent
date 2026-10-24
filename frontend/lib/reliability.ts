/** Public aggregate contract only. No run detail, prompt, solution or file API. */
export type Tier = "1" | "2" | "3" | "4";
export type Check = "rtl_generated" | "lint" | "self_tests" | "hidden" | "synthesis" | "flow" | "drc" | "lvs" | "package";
export type CheckStatus = "pass" | "fail" | "not_run" | "unknown" | "error" | "not_applicable";
export interface Stats { count: number; mean: number | null; median: number | null; min: number | null; max: number | null }
export interface Cost {
  assessable: boolean; known_trials: number; unknown_attempted_trials: number;
  total_usd: number | null; median_usd: number | null; known_subset: Stats & { total_usd: number | null };
}
export interface TierReport {
  cases: number; planned: number; recorded: number; attempted: number; successful: number; success_rate: number;
  repeat_success_rates: Stats; cost: Cost; pipeline_time_seconds: Stats;
}
export interface Conditions {
  corpus_sha256: string; grader_sha256: string; plan_sha256: string; provider: "codex" | "meta"; model: string; cli_version: string | null;
  tool_versions: { eda_image: string; eda_image_id: string; pdk_revision: string; python: string; openai: string; pydantic: string; sqlmodel: string };
  config: { repeats: number; concurrency: number; max_calls: number; max_tokens: number | null; max_usd: number; time_limit_seconds: number };
}
export const FUNNEL_KEYS = ["planned_hardware", "rtl_generated", "lint", "self_tests", "synthesis", "flow", "drc", "lvs", "package", "bound_hidden_pass"] as const;
export const CHECKS: Check[] = ["rtl_generated", "lint", "self_tests", "hidden", "synthesis", "flow", "drc", "lvs", "package"];
export const STATUSES: CheckStatus[] = ["pass", "fail", "not_run", "unknown", "error", "not_applicable"];
export const TIERS: Tier[] = ["1", "2", "3", "4"];
export interface Cohort {
  schema_version: 1; kind: "sealed_dev_reliability"; cohort_id: string;
  binding: { summary_sha256: string; seal_sha256: string; sealer: "base" | "harness"; sealer_sha256: string; base_sealer_sha256: string; verification_stdout_sha256: string };
  report: {
    split: "dev"; complete: true; pipeline_sha256: string; comparison_group_sha256: string; comparison_conditions: Conditions;
    repeats: number; planned: number; successful: number; success_rate: number; tiers: Partial<Record<Tier, TierReport>>;
    hardware_survival_funnel: { check: typeof FUNNEL_KEYS[number]; count: number }[];
    independent_stage_checks: Record<Check, Record<CheckStatus, number>>; failure_counts: Record<string, number>;
    cost: Cost; pipeline_time_seconds: Stats; time_distribution_seconds: (number | null)[];
    known_cost_distribution_usd: number[]; unknown_cost_trials: number;
  };
}
export interface Group {
  comparison_group_sha256: string; cohort_ids: string[];
  tier_trends: Partial<Record<Tier, { cohort_id: string; pipeline_sha256: string; success_rate: number }[]>>;
}
export interface ReliabilityResponse {
  schema_version: 1; state: "ready" | "empty"; cohorts: Cohort[]; comparison_groups: Group[];
  top_original_failure_classes: Record<string, { class: string; count: number }[]>;
}

const SHA = /^[a-f0-9]{64}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
function requireValue(value: unknown): asserts value { if (!value) throw new Error("Unsupported public reliability response"); }
function object(value: unknown): Record<string, unknown> { requireValue(value !== null && typeof value === "object" && !Array.isArray(value)); return value as Record<string, unknown>; }
function exact(value: unknown, keys: readonly string[]) { const obj = object(value); requireValue(Object.keys(obj).length === keys.length && keys.every((key) => key in obj)); return obj; }
function count(value: unknown, max = 1_000_000): asserts value is number { requireValue(Number.isSafeInteger(value) && typeof value === "number" && value >= 0 && value <= max); }
function hash(value: unknown) { requireValue(typeof value === "string" && SHA.test(value)); }
function label(value: unknown, max = 200): asserts value is string { requireValue(typeof value === "string" && value.length > 0 && value.length <= max); }
function stats(value: unknown, bound: number) {
  const item = exact(value, ["count", "mean", "median", "min", "max"]); count(item.count, bound);
  for (const key of ["mean", "median", "min", "max"]) requireValue(item.count === 0 ? item[key] === null : finite(item[key]));
  if (item.count) requireValue((item.min as number) <= (item.median as number) && (item.median as number) <= (item.max as number) && (item.min as number) <= (item.mean as number) && (item.mean as number) <= (item.max as number));
}
function cost(value: unknown, n: number) {
  const item = exact(value, ["assessable", "known_trials", "unknown_attempted_trials", "total_usd", "median_usd", "known_subset"]);
  count(item.known_trials, n); count(item.unknown_attempted_trials, n);
  requireValue(item.known_trials + item.unknown_attempted_trials === n && item.assessable === (item.unknown_attempted_trials === 0));
  for (const key of ["total_usd", "median_usd"]) requireValue(item.assessable ? finite(item[key]) : item[key] === null);
  const known = exact(item.known_subset, ["count", "mean", "median", "min", "max", "total_usd"]);
  stats(Object.fromEntries(["count", "mean", "median", "min", "max"].map((key) => [key, known[key]])), n);
  requireValue(known.count === item.known_trials && (known.count === 0 ? known.total_usd === null : finite(known.total_usd)));
}
function validateCohort(value: unknown): asserts value is Cohort {
  const c = exact(value, ["schema_version", "kind", "cohort_id", "binding", "report"]);
  requireValue(c.schema_version === 1 && c.kind === "sealed_dev_reliability" && typeof c.cohort_id === "string" && ID.test(c.cohort_id));
  const binding = exact(c.binding, ["summary_sha256", "seal_sha256", "sealer", "sealer_sha256", "base_sealer_sha256", "verification_stdout_sha256"]);
  requireValue(binding.sealer === "base" || binding.sealer === "harness");
  for (const key of ["summary_sha256", "seal_sha256", "sealer_sha256", "base_sealer_sha256", "verification_stdout_sha256"]) hash(binding[key]);
  const r = exact(c.report, ["split", "complete", "pipeline_sha256", "comparison_group_sha256", "comparison_conditions", "repeats", "planned", "successful", "success_rate", "tiers", "hardware_survival_funnel", "independent_stage_checks", "failure_counts", "cost", "pipeline_time_seconds", "time_distribution_seconds", "known_cost_distribution_usd", "unknown_cost_trials"]);
  requireValue(r.split === "dev" && r.complete === true); hash(r.pipeline_sha256); hash(r.comparison_group_sha256);
  count(r.planned, 5000); count(r.successful, r.planned); count(r.repeats, 5000);
  requireValue(r.planned > 0 && r.repeats > 0 && finite(r.success_rate) && Math.abs(r.success_rate - r.successful / r.planned) < 1e-12);
  const conditions = exact(r.comparison_conditions, ["corpus_sha256", "grader_sha256", "provider", "model", "cli_version", "tool_versions", "config", "plan_sha256"]);
  for (const key of ["corpus_sha256", "grader_sha256", "plan_sha256"]) hash(conditions[key]);
  requireValue(conditions.provider === "codex" || conditions.provider === "meta"); label(conditions.model, 128);
  requireValue(conditions.cli_version === null || typeof conditions.cli_version === "string");
  const versions = exact(conditions.tool_versions, ["eda_image", "eda_image_id", "pdk_revision", "python", "openai", "pydantic", "sqlmodel"]);
  for (const value of Object.values(versions)) label(value);
  const config = exact(conditions.config, ["repeats", "concurrency", "max_calls", "max_tokens", "max_usd", "time_limit_seconds"]);
  for (const key of ["repeats", "concurrency", "max_calls"]) { count(config[key]); requireValue((config[key] as number) > 0); }
  requireValue(config.repeats === r.repeats && (config.max_tokens === null || (Number.isSafeInteger(config.max_tokens) && (config.max_tokens as number) > 0)) && finite(config.max_usd) && finite(config.time_limit_seconds));
  const tiers = object(r.tiers); requireValue(Object.keys(tiers).length > 0 && Object.keys(tiers).every((key) => TIERS.includes(key as Tier)));
  let planned = 0, successful = 0, hardware = 0;
  for (const [tier, value] of Object.entries(tiers)) {
    const t = exact(value, ["cases", "planned", "recorded", "attempted", "successful", "success_rate", "repeat_success_rates", "cost", "pipeline_time_seconds"]);
    for (const key of ["cases", "planned", "recorded", "attempted", "successful"]) count(t[key], r.planned);
    requireValue(t.planned === (t.cases as number) * r.repeats && t.planned === t.recorded && t.planned === t.attempted && (t.planned as number) > 0 && (t.successful as number) <= (t.planned as number));
    requireValue(finite(t.success_rate) && Math.abs(t.success_rate - (t.successful as number) / (t.planned as number)) < 1e-12);
    stats(t.repeat_success_rates, r.repeats); requireValue(object(t.repeat_success_rates).count === r.repeats && (object(t.repeat_success_rates).max as number) <= 1);
    stats(t.pipeline_time_seconds, t.planned as number); cost(t.cost, t.planned as number);
    planned += t.planned as number; successful += t.successful as number; if (tier !== "4") hardware += t.planned as number;
  }
  requireValue(planned === r.planned && successful === r.successful);
  requireValue(Array.isArray(r.hardware_survival_funnel) && r.hardware_survival_funnel.length === FUNNEL_KEYS.length);
  let previous = hardware;
  r.hardware_survival_funnel.forEach((value, index) => { const row = exact(value, ["check", "count"]); count(row.count, previous); requireValue(row.check === FUNNEL_KEYS[index] && (index > 0 || row.count === hardware)); previous = row.count; });
  const checks = exact(r.independent_stage_checks, CHECKS);
  for (const check of CHECKS) { const row = exact(checks[check], STATUSES); let n = 0; for (const status of STATUSES) { count(row[status], r.planned); n += row[status] as number; } requireValue(n === r.planned); }
  const failures = object(r.failure_counts); requireValue(Object.keys(failures).length <= 64); let failureCount = 0; for (const [key, n] of Object.entries(failures)) { requireValue(/^[a-z][a-z_]{0,63}$/.test(key)); count(n, r.planned); failureCount += n; } requireValue(failureCount <= r.planned);
  cost(r.cost, r.planned); stats(r.pipeline_time_seconds, r.planned); count(r.unknown_cost_trials, r.planned);
  requireValue(Array.isArray(r.time_distribution_seconds) && r.time_distribution_seconds.length === r.planned && r.time_distribution_seconds.every((n) => n === null || finite(n)));
  requireValue(Array.isArray(r.known_cost_distribution_usd) && r.known_cost_distribution_usd.every(finite) && r.known_cost_distribution_usd.length + r.unknown_cost_trials === r.planned && object(r.cost).unknown_attempted_trials === r.unknown_cost_trials);
}

export function parseReliabilityResponse(value: unknown): ReliabilityResponse {
  const response = exact(value, ["schema_version", "state", "cohorts", "comparison_groups", "top_original_failure_classes"]);
  requireValue(response.schema_version === 1 && (response.state === "ready" || response.state === "empty") && Array.isArray(response.cohorts) && response.cohorts.length <= 128);
  response.cohorts.forEach(validateCohort);
  const cohorts = response.cohorts as Cohort[], ids = new Set(cohorts.map((c) => c.cohort_id));
  requireValue(ids.size === cohorts.length && (response.state === "empty") === (cohorts.length === 0));
  requireValue(Array.isArray(response.comparison_groups)); const groups = new Set<string>();
  for (const group of response.comparison_groups) {
    const g = exact(group, ["comparison_group_sha256", "cohort_ids", "tier_trends"]); hash(g.comparison_group_sha256);
    requireValue(!groups.has(g.comparison_group_sha256 as string)); groups.add(g.comparison_group_sha256 as string);
    requireValue(Array.isArray(g.cohort_ids) && g.cohort_ids.length > 0 && new Set(g.cohort_ids).size === g.cohort_ids.length && g.cohort_ids.every((id) => typeof id === "string" && cohorts.some((c) => c.cohort_id === id && c.report.comparison_group_sha256 === g.comparison_group_sha256)));
    requireValue(g.cohort_ids.length === cohorts.filter((c) => c.report.comparison_group_sha256 === g.comparison_group_sha256).length);
    const groupIds = g.cohort_ids as string[];
    const trends = object(g.tier_trends);
    const expectedTiers = TIERS.filter((tier) => cohorts.some((c) => groupIds.includes(c.cohort_id) && c.report.tiers[tier]));
    requireValue(Object.keys(trends).length === expectedTiers.length && expectedTiers.every((tier) => tier in trends));
    for (const [tier, values] of Object.entries(trends)) {
      requireValue(TIERS.includes(tier as Tier) && Array.isArray(values));
      requireValue(values.length === cohorts.filter((c) => groupIds.includes(c.cohort_id) && c.report.tiers[tier as Tier]).length && new Set(values.map((value) => object(value).cohort_id)).size === values.length);
      for (const value of values) { const point = exact(value, ["cohort_id", "pipeline_sha256", "success_rate"]); requireValue(typeof point.cohort_id === "string" && groupIds.includes(point.cohort_id) && cohorts.some((c) => c.cohort_id === point.cohort_id && c.report.pipeline_sha256 === point.pipeline_sha256 && c.report.tiers[tier as Tier]?.success_rate === point.success_rate)); }
    }
  }
  requireValue(cohorts.every((c) => groups.has(c.report.comparison_group_sha256)));
  const failures = exact(response.top_original_failure_classes, [...ids]);
  for (const cohort of cohorts) {
    const rows = failures[cohort.cohort_id]; requireValue(Array.isArray(rows) && rows.length <= 10);
    const expected = Object.entries(cohort.report.failure_counts).sort(([a, x], [b, y]) => y - x || (a < b ? -1 : a > b ? 1 : 0)).slice(0, 10);
    requireValue(rows.length === expected.length);
    rows.forEach((row, index) => { const item = exact(row, ["class", "count"]); requireValue(item.class === expected[index][0] && item.count === expected[index][1]); count(item.count, cohort.report.planned); });
  }
  return response as unknown as ReliabilityResponse;
}

export class ReliabilityApiError extends Error { constructor(readonly status: number) { super("Reliability reports unavailable"); } }
export async function fetchReliability(signal: AbortSignal): Promise<ReliabilityResponse> {
  const response = await fetch("/api/admin/reliability", { signal, cache: "no-store" });
  if (!response.ok) throw new ReliabilityApiError(response.status);
  return parseReliabilityResponse(await response.json());
}
export const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
export const shortHash = (value: string) => value.slice(0, 10);
export const money = (value: number | null) => value === null ? "Unknown" : value > 0 && value < 0.0001 ? "<$0.0001" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value);
export const seconds = (value: number | null) => value === null ? "Unknown" : value < 60 ? `${value.toFixed(1)}s` : `${Math.floor(value / 60)}m ${(value % 60).toFixed(1)}s`;
export function peers(data: ReliabilityResponse, selected: Cohort): Cohort[] {
  const group = data.comparison_groups.find((g) => g.comparison_group_sha256 === selected.report.comparison_group_sha256);
  return (group?.cohort_ids ?? []).flatMap((id) => data.cohorts.filter((c) => c.cohort_id === id && c.report.comparison_group_sha256 === group?.comparison_group_sha256)).sort((a, b) => a.cohort_id.localeCompare(b.cohort_id));
}
export interface Bin { from: number; to: number; count: number }
export function histogram(values: (number | null)[], buckets = 6): { bins: Bin[]; known: number; unknown: number } {
  const known = values.filter((value): value is number => value !== null && finite(value));
  if (!known.length) return { bins: [], known: 0, unknown: values.length };
  const min = Math.min(...known), max = Math.max(...known);
  if (min === max) return { bins: [{ from: min, to: max, count: known.length }], known: known.length, unknown: values.length - known.length };
  const n = Math.max(1, Math.min(buckets, known.length)), width = (max - min) / n;
  const bins = Array.from({ length: n }, (_, index) => ({ from: min + index * width, to: index === n - 1 ? max : min + (index + 1) * width, count: 0 }));
  for (const value of known) bins[Math.min(n - 1, Math.floor((value - min) / width))].count += 1;
  return { bins, known: known.length, unknown: values.length - known.length };
}
