import type { Metric } from "@/lib/api";

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

