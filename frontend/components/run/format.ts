import type { Metric, PublicRun } from "@/lib/api";

export function number(value: number | null | undefined, digits = 2): string {
  return value == null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function elapsed(start: string, end: string | number): string {
  const seconds = Math.max(0, Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function title(value: string): string {
  if (value === "uart" || value === "uart_tx") return "UART TX";
  return value.replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

export function bestMeasured(metrics: Metric[], bestTag?: string | null, targetClock?: number | null): Metric | undefined {
  const selected = metrics.find((metric) => metric.run_tag === bestTag);
  if (selected) return selected;
  return metrics.toSorted((a, b) => {
    const timingA = a.wns_ns != null && a.wns_ns >= 0 && (targetClock == null || a.clock_mhz >= targetClock) ? 0 : 1;
    const timingB = b.wns_ns != null && b.wns_ns >= 0 && (targetClock == null || b.clock_mhz >= targetClock) ? 0 : 1;
    return timingA - timingB || (a.area_um2 ?? Infinity) - (b.area_um2 ?? Infinity) || (a.power_mw ?? Infinity) - (b.power_mw ?? Infinity);
  })[0];
}


export function replayLabel(run: Pick<PublicRun, "replay_speed">): string {
  return `REPLAY${run.replay_speed == null ? "" : ` ${number(run.replay_speed)}×`}`;
}

export function usageLabel(run: Pick<PublicRun, "is_replay" | "input_tokens" | "output_tokens" | "call_count">): string {
  const tokens = run.input_tokens + run.output_tokens;
  if (tokens === 0) return run.is_replay ? "Recorded usage appears during playback" : "Waiting for model usage";
  return `${run.is_replay ? "Recorded: " : ""}${number(tokens, 0)} tokens · ${run.call_count} ${run.call_count === 1 ? "call" : "calls"}`;
}

export function duration(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

export function runName(run: Pick<PublicRun, "design_spec" | "preset_id">): string {
  return typeof run.design_spec?.top_module === "string" ? run.design_spec.top_module : run.preset_id ? title(run.preset_id) : "Chip design";
}
