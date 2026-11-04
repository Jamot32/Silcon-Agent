import type { Metric, PublicRun } from "./api";

export type ResultSelection = { metric?: Metric; unavailable?: string };

// A partial or later optimization flow is not evidence for the delivered result.
export function selectedResult(run: Pick<PublicRun, "status" | "best_run_tag">, metrics: Metric[]): ResultSelection {
  if (run.status !== "done") return { unavailable: `Run ${run.status}; no completed result to compare.` };
  if (!run.best_run_tag) return { unavailable: "No final physical run was selected." };
  const metric = metrics.find((entry) => entry.run_tag === run.best_run_tag);
  return metric ? { metric } : { unavailable: `Measurements for selected flow ${run.best_run_tag} are unavailable.` };
}

export function finiteMeasurement(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function measurementDelta(parent: unknown, revision: unknown): { absolute: number; percent: number | null } | null {
  if (!finiteMeasurement(parent) || !finiteMeasurement(revision)) return null;
  const absolute = revision - parent;
  if (!Number.isFinite(absolute)) return null;
  const percent = parent > 0 ? absolute / parent * 100 : null;
  return { absolute, percent: finiteMeasurement(percent) ? percent : null };
}
