import type { JsonValue, Metric } from "@/lib/api";
import { toolSummary, type FlowVariant } from "@/lib/run-activity";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { duration, number } from "./format";
import { Panel } from "./panel";
import { Signoff } from "./run-inspection";

const setting = (value: JsonValue): string => Array.isArray(value) ? value.map(setting).join(" × ") : typeof value === "number" ? number(value) : String(value);

function Variant({ variant, runId, selected, baseline, end, replay }: { variant: FlowVariant; runId: string; selected: boolean; baseline: Metric | undefined; end: number | null; replay: boolean }) {
  const { metric, span } = variant;
  const config = span?.result?.planned_config_overrides;
  const tag = metric?.run_tag ?? (typeof span?.result?.run_tag === "string" ? span.result.run_tag : null);
  const delta = metric && baseline && baseline !== metric && baseline.area_um2 > 0 ? (metric.area_um2 - baseline.area_um2) / baseline.area_um2 * 100 : null;
  return <article className={cn("flex min-w-0 flex-col overflow-hidden rounded-lg border bg-card", selected && "border-primary ring-1 ring-primary/40")} data-status={variant.status} aria-label={metric ? `Flow ${metric.flow_index}` : "Flow attempt"}>
    <div className="relative grid aspect-[4/3] place-items-center bg-black/40">
      {variant.rendered && tag ? <img src={`/api/runs/${encodeURIComponent(runId)}/layout/${encodeURIComponent(tag)}.png`} alt={`Real sky130 GDS layout for ${tag}`} loading="lazy" draggable={false} className="size-full object-contain" />
        : variant.status === "running" ? <span className="flex flex-col items-center gap-2 text-xs text-muted-foreground"><Spinner className="size-5 text-primary" />{replay ? "Recorded LibreLane run in progress at this point" : `LibreLane placing and routing${span && end !== null ? ` · ${duration((end - span.start) / 1000)}` : ""}`}</span>
        : <span className="px-4 text-center text-xs text-muted-foreground">{variant.status === "failed" ? "No layout: this flow attempt failed." : variant.status === "unfinished" ? "The run ended before this flow finished." : "No layout render was recorded."}</span>}
      {selected ? <Badge className="absolute top-2 left-2">Selected</Badge> : null}
    </div>
    <div className="flex flex-1 flex-col gap-2 p-3 text-xs">
      <div className="flex min-w-0 items-baseline justify-between gap-2"><h3 className="text-sm font-medium">{metric ? `Flow ${metric.flow_index}` : variant.status === "running" ? "Flow running" : "Flow attempt"}</h3>{tag ? <span className="truncate font-mono text-[10px] text-muted-foreground" title={tag}>{tag}</span> : null}</div>
      {config && typeof config === "object" && !Array.isArray(config) && Object.keys(config).length ? <ul className="flex flex-wrap gap-1" aria-label="Planned flow configuration">{Object.entries(config).map(([key, value]) => <li key={key} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{key} {setting(value)}</li>)}</ul> : null}
      {metric ? <>
        <dl className="grid grid-cols-3 gap-2">
          <div><dt className="text-[10px] text-muted-foreground">Area (µm²)</dt><dd className="tabular-nums">{number(metric.area_um2)}{delta !== null ? <span className={cn("block text-[10px]", delta < 0 ? "text-success" : "text-muted-foreground")}>{delta > 0 ? "+" : ""}{number(delta, 1)}% vs <span className="whitespace-nowrap">Flow {baseline!.flow_index}</span></span> : null}</dd></div>
          <div><dt className="text-[10px] text-muted-foreground">WNS (ns)</dt><dd className={cn("tabular-nums", metric.wns_ns < 0 && "text-destructive")}>{number(metric.wns_ns, 3)}</dd></div>
          <div><dt className="text-[10px] text-muted-foreground">Power (mW)</dt><dd className="tabular-nums">{number(metric.power_mw, 4)}</dd></div>
        </dl>
        <p className="mt-auto flex gap-3 text-muted-foreground"><span>{number(metric.cell_count, 0)} cells</span><span>DRC <Signoff value={metric.drc_ok} /></span><span>LVS <Signoff value={metric.lvs_ok} /></span></p>
      </> : variant.status === "failed" && span ? <p className="line-clamp-3 text-destructive">{toolSummary(span) ?? "The flow reported failure."}</p> : null}
    </div>
  </article>;
}

export function FlowComparison({ variants, metrics, bestTag, runId, end, replay = false }: { variants: FlowVariant[]; metrics: Metric[]; bestTag: string | null; runId: string; end: number | null; replay?: boolean }) {
  if (variants.length === 0) return null;
  const baseline = metrics.toSorted((a, b) => a.flow_index - b.flow_index)[0];
  const running = variants.filter((variant) => variant.status === "running").length;
  return <Panel id="flow-comparison-title" title={replay ? "Recorded chip variants" : "Chip variants"} aside={<span className="text-xs text-muted-foreground">{metrics.length} measured{running ? ` · ${running} ${replay ? "in progress in the recording" : "running"}` : ""}</span>} data-testid="flow-comparison" data-point-count={metrics.length}>
    <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">{variants.map((variant) => <Variant key={variant.key} variant={variant} runId={runId} selected={!!bestTag && variant.metric?.run_tag === bestTag} baseline={baseline} end={end} replay={replay} />)}</div>
    <p className="px-4 pb-3 text-xs text-muted-foreground">Each card is one real sky130 LibreLane run. Power is the flow-reported total from its last reported corner.</p>
  </Panel>;
}
