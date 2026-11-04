import type { BuildSettingsDraft } from "./build-settings";

export interface DesignDraft {
  spec: string; clock: string; fit: boolean; review: boolean; selectedPreset?: string; build?: BuildSettingsDraft;
}

const storageKey = "silicon-agent.design-draft";
export const maxSpecLength = 12000;

function parseBuildSettingsDraft(value: unknown): BuildSettingsDraft | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (typeof v.optimize !== "boolean" || ["attempts", "repairs", "strategy", "utilization", "density"].some((key) => typeof v[key] !== "string" || v[key].length > 32)) return null;
  return { optimize: v.optimize, attempts: v.attempts as string, repairs: v.repairs as string, strategy: v.strategy as string, utilization: v.utilization as string, density: v.density as string };
}

export function parseDesignDraft(raw: string | null): DesignDraft | null {
  try {
    const value: unknown = raw ? JSON.parse(raw) : null;
    if (!value || typeof value !== "object" || !("version" in value) || value.version !== 1) return null;
    const stored = value as Partial<Record<keyof DesignDraft, unknown>>;
    if (typeof stored.spec !== "string" || stored.spec.length > maxSpecLength || typeof stored.clock !== "string" || stored.clock.length > 32
      || typeof stored.fit !== "boolean" || typeof stored.review !== "boolean"
      || (stored.selectedPreset !== undefined && (typeof stored.selectedPreset !== "string" || !/^[a-z0-9_-]{1,64}$/.test(stored.selectedPreset)))) return null;
    const build = stored.build === undefined ? undefined : parseBuildSettingsDraft(stored.build);
    if (build === null) return null;
    return { spec: stored.spec, clock: stored.clock, fit: stored.fit, review: stored.review, selectedPreset: stored.selectedPreset, ...(build ? { build } : {}) };
  } catch { return null; }
}

export function loadDesignDraft(): { draft: DesignDraft | null; available: boolean } {
  try { return { draft: parseDesignDraft(window.localStorage.getItem(storageKey)), available: true }; }
  catch { return { draft: null, available: false }; }
}

export function saveDesignDraft({ spec, clock, fit, review, selectedPreset, build }: DesignDraft): boolean {
  try {
    const cleanBuild = build === undefined ? undefined : parseBuildSettingsDraft(build);
    if (cleanBuild === null) return false;
    window.localStorage.setItem(storageKey, JSON.stringify({ version: 1, spec, clock, fit, review, selectedPreset, ...(cleanBuild ? { build: cleanBuild } : {}) })); return true;
  }
  catch { return false; }
}

export function clearDesignDraft(expected: DesignDraft | null): "cleared" | "changed" | "unavailable" {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw === null) return "cleared";
    const current = parseDesignDraft(raw);
    // Another tab may have saved since this tab loaded or last edited its draft.
    if (!current || !expected || current.spec !== expected.spec || current.clock !== expected.clock
      || current.fit !== expected.fit || current.review !== expected.review || current.selectedPreset !== expected.selectedPreset) return "changed";
    if (Boolean(current.build) !== Boolean(expected.build) || current.build && expected.build && (Object.keys(current.build) as (keyof BuildSettingsDraft)[]).some((key) => current.build![key] !== expected.build![key])) return "changed";
    window.localStorage.removeItem(storageKey);
    return "cleared";
  } catch { return "unavailable"; }
}
