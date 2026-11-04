import type { BuildConfig } from "./api";

export const synthesisStrategies = ["AREA 0", "AREA 1", "AREA 2", "AREA 3", "DELAY 0", "DELAY 1", "DELAY 2", "DELAY 3", "DELAY 4"];
export interface BuildSettingsDraft {
  optimize: boolean; attempts: string; repairs: string; strategy: string; utilization: string; density: string;
}

export function buildSettingsDraft(config?: BuildConfig | null): BuildSettingsDraft {
  return {
    optimize: config?.optimize ?? true, attempts: String(config?.max_flow_runs ?? 6), repairs: String(config?.max_repair_loops ?? 5),
    strategy: config?.initial_flow.SYNTH_STRATEGY ?? "", utilization: config?.initial_flow.FP_CORE_UTIL == null ? "" : String(config.initial_flow.FP_CORE_UTIL),
    density: config?.initial_flow.PL_TARGET_DENSITY_PCT == null ? "" : String(config.initial_flow.PL_TARGET_DENSITY_PCT),
  };
}

export function buildSettingsError(value: BuildSettingsDraft): string | null {
  const attempts = Number(value.attempts), repairs = Number(value.repairs);
  if (!value.attempts.trim() || !Number.isInteger(attempts) || attempts < 1 || attempts > 6) return "Flow attempts must be a whole number from 1 to 6.";
  if (!value.repairs.trim() || !Number.isInteger(repairs) || repairs < 0 || repairs > 5) return "RTL repair loops must be a whole number from 0 to 5.";
  if (value.strategy && !synthesisStrategies.includes(value.strategy)) return "Choose a supported synthesis strategy or the planner default.";
  for (const [label, raw] of [["Core utilization", value.utilization], ["Placement density", value.density]]) {
    if (raw.trim() && (!Number.isFinite(Number(raw)) || Number(raw) < 1 || Number(raw) > 90)) return `${label} must be between 1 and 90%, or blank for the planner default.`;
  }
  return null;
}

export function buildSettingsConfig(value: BuildSettingsDraft): BuildConfig | null {
  if (buildSettingsError(value)) return null;
  return {
    optimize: value.optimize, max_flow_runs: Number(value.attempts), max_repair_loops: Number(value.repairs), initial_flow: {
      ...(value.strategy ? { SYNTH_STRATEGY: value.strategy } : {}),
      ...(value.utilization.trim() ? { FP_CORE_UTIL: Number(value.utilization) } : {}),
      ...(value.density.trim() ? { PL_TARGET_DENSITY_PCT: Number(value.density) } : {}),
    },
  };
}
