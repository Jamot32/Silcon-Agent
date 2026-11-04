"use client";

import type { ReactNode } from "react";
import { Check, CircleAlert, Square } from "lucide-react";
import type { PublicRun } from "@/lib/api";
import { toolSummary, type FlowVariant, type RunActivity, type ToolSpan } from "@/lib/run-activity";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { compact, duration, number, toolLabel } from "./format";
import { AgentRoster } from "./agent-roster";
import { Panel } from "./panel";

const stageTitles: Record<string, string> = {
  SPEC: "Drafting the design spec", REVIEW: "Waiting for your spec review", RTL: "Writing RTL", VERIFY: "Writing and running independent tests", SYNTH: "Synthesizing gates",
  FLOW: "Running physical design", OPTIMIZE: "Optimizing power, performance and area", SIGNOFF: "Reading signoff reports",
  PACKAGE: "Packaging the GDS bundle", DONE: "Build complete", FAIL: "Build stopped", FAILED: "Build stopped",
};
const stageOrder = ["SPEC", "RTL", "VERIFY", "SYNTH", "FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE"];
const stageTones = ["bg-chart-1", "bg-chart-2", "bg-chart-3", "bg-chart-4", "bg-chart-5"];
const terminal = new Set(["DONE", "FAIL", "FAILED"]);
const clock = (ms: number) => duration(Math.max(0, ms) / 1000);
const barText = "truncate px-1 font-mono text-[10px] font-medium text-white [text-shadow:0_1px_1px_rgb(0_0_0/0.6)]";
const unfinished = "bg-muted-foreground/30";

function heading(run: PublicRun, activity: RunActivity, stage: string, ongoing: boolean): string {
  if (run.status === "cancel_requested") return "Cancelling…";
  if (ongoing) return activity.stages.length ? stageTitles[stage] ?? stage : "Queued: waiting for the worker to claim this run";
  if (run.status === "done") return "Build complete";
  if (run.status === "cancelled") return "Build cancelled";
  return `Stopped during ${activity.stages.findLast((span) => !terminal.has(span.stage))?.stage ?? "the run"}`;
}

function Now({ run, activity, variants, ongoing }: { run: PublicRun; activity: RunActivity; variants: FlowVariant[]; ongoing: boolean }) {
  const current = activity.stages.at(-1);
  const stage = current?.stage ?? run.stage;
  const end = activity.end ?? 0;
  const running = new Map<string, ToolSpan[]>();
  for (const span of activity.tools) if (span.end === null) running.set(span.tool, [...running.get(span.tool) ?? [], span]);
  const last = activity.tools.reduce<ToolSpan | null>((latest, span) => span.end !== null && (latest === null || span.end >= latest.end!) ? span : latest, null);
  const calls = activity.modelCalls.reduce((sum, call) => sum + call.calls, 0);
  const tokens = activity.modelCalls.reduce((sum, call) => sum + call.inputTokens + call.outputTokens, 0);
  const stats = [
    ["Model calls", number(calls, 0)], ["Tokens", compact(tokens)], ["Tool calls", number(activity.tools.length, 0)],
    ["Flows", number(variants.length, 0)], ["Repair loops", number(activity.repairs, 0)],
  ];
  const Icon = ongoing ? Spinner : run.status === "done" ? Check : run.status === "cancelled" ? Square : CircleAlert;
  return <section className="flex min-w-0 flex-col gap-3 p-4" aria-label="Current orchestrator activity" data-testid="agent-now" data-stage={current ? stage : "QUEUED"}>
    <div className="flex items-start gap-2.5">
      <span className={cn("mt-0.5 grid size-5 shrink-0 place-items-center [&_svg]:size-4", ongoing ? "text-primary" : run.status === "done" ? "text-success" : "text-muted-foreground")} aria-hidden="true"><Icon /></span>
      <div className="min-w-0">
        {current ? <p className="font-mono text-[11px] text-muted-foreground">{stage}{!terminal.has(stage) ? ` · ${clock((current.end ?? end) - current.start)} in stage${run.is_replay ? " (recorded)" : ""}` : ""}</p> : null}
        <h3 className="text-base font-semibold leading-snug">{heading(run, activity, stage, ongoing)}</h3>
        {ongoing && current?.goal ? <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-muted-foreground" title={current.goal}><span className="font-medium text-foreground/80">Orchestrator goal: </span>{current.goal}</p> : null}
      </div>
    </div>
    {ongoing && current ? <ul className="space-y-1.5 rounded-md border bg-muted/30 px-3 py-2 text-xs" aria-label="Running tools">
      {running.size ? [...running].map(([tool, spans]) => <li key={tool} className="flex items-center gap-2"><Spinner className="size-3.5 text-primary" /><span className="font-medium">{spans.length > 1 ? `${spans.length} × ` : ""}{toolLabel(tool)}{run.is_replay ? " (recorded)" : ""}</span>{run.is_replay ? null : <span className="ml-auto font-mono tabular-nums text-muted-foreground" aria-hidden="true">{clock(end - Math.min(...spans.map((span) => span.start)))}</span>}</li>)
        : <li className="text-muted-foreground">{run.is_replay ? "No tool was running at this point in the recording." : stage === "REVIEW" ? "No model or tool is running. The orchestrator is waiting for you to approve the spec below." : "No tool running. The orchestrator is awaiting the model or preparing the next step."}</li>}
      {last ? <li className="truncate text-muted-foreground" title={toolSummary(last) ?? undefined}>Last: {toolLabel(last.tool)}{last.ok === false ? " failed" : ""}{toolSummary(last) ? ` · ${toolSummary(last)}` : ""}</li> : null}
    </ul> : null}
    {activity.latestNote ? <figure className="border-l-2 border-primary/50 pl-3"><figcaption className="text-[11px] text-muted-foreground">Latest agent note</figcaption><blockquote className="line-clamp-4 text-xs leading-relaxed" title={activity.latestNote.text}>{activity.latestNote.text}</blockquote></figure> : null}
    <dl className="mt-auto grid grid-cols-3 gap-x-3 gap-y-2 sm:grid-cols-5">{stats.map(([label, value]) => <div key={label}><dt className="text-[10px] text-muted-foreground">{label}</dt><dd className="font-mono text-sm tabular-nums">{value}</dd></div>)}</dl>
  </section>;
}

function Bar({ start, end, from, total, className, label, children }: { start: number; end: number; from: number; total: number; className: string; label: string; children?: ReactNode }) {
  return <span className={cn("absolute inset-y-1 flex min-w-0.5 items-center overflow-hidden rounded-sm", className)} style={{ left: `${(start - from) / total * 100}%`, width: `${Math.max(0, end - start) / total * 100}%` }} title={label}>{children}</span>;
}

function Row({ label, children, detail }: { label: string; children: ReactNode; detail?: string }) {
  return <li className="flex items-center gap-2"><span className="w-24 shrink-0 truncate text-[11px] text-muted-foreground" title={detail ?? label}>{label}</span><span className="relative h-6 min-w-0 flex-1 rounded-sm bg-muted/40">{children}</span></li>;
}

function BuildTrace({ activity, variants, replay, ongoing }: { activity: RunActivity; variants: FlowVariant[]; replay: boolean; ongoing: boolean }) {
  const { start, end } = activity;
  if (start === null || end === null || end <= start) return <p className="p-4 text-sm text-muted-foreground">The build trace starts with the first orchestrator stage.</p>;
  const total = end - start, at = (span: { end: number | null }) => span.end ?? end;
  // A span without a finish event is running only while the run is; afterwards it is unfinished evidence.
  const open = (span: { end: number | null }) => span.end === null ? ongoing ? "running" : "unfinished" : null;
  const flows = variants.filter((variant) => variant.span);
  const flowSpans = new Set(flows.map((variant) => variant.span));
  const tools = activity.tools.filter((span) => !flowSpans.has(span));
  const toolTone = (span: ToolSpan) => open(span) === "running" ? "bg-primary animate-pulse" : open(span) ? unfinished : span.ok === false ? "bg-destructive" : "bg-muted-foreground/60";
  const flowTone = (variant: FlowVariant) => variant.status === "running" ? "bg-primary animate-pulse" : variant.status === "unfinished" ? unfinished : variant.status === "failed" ? "bg-destructive" : variant.metric?.drc_ok === true && variant.metric.lvs_ok === true ? "bg-success" : "bg-chart-4";
  return <figure className="flex min-w-0 flex-col gap-2 p-4" aria-label={`Build trace: ${activity.stages.length} stage visits, ${activity.modelCalls.length} model calls, ${activity.tools.length} tool calls over ${clock(total)}${replay ? " of recorded time" : ""}`} data-testid="build-trace" data-flow-rows={flows.length}>
    <figcaption className="flex items-center justify-between text-xs"><span className="font-medium">Build trace</span><span className="text-muted-foreground">{replay ? "Recorded timing" : "Wall-clock timing"} · {clock(total)}</span></figcaption>
    <ol className="space-y-1">
      <Row label="Orchestrator" detail="Stage the host orchestrator is running">{activity.stages.filter((span) => span.end !== span.start).map((span, index) => <Bar key={index} start={span.start} end={at(span)} from={start} total={total} className={cn(open(span) === "unfinished" ? unfinished : stageTones[Math.max(0, stageOrder.indexOf(span.stage)) % stageTones.length], open(span) === "running" && "animate-pulse")} label={`${span.stage} · ${clock(at(span) - span.start)}${span.calls ? ` · ${span.calls} model calls` : ""}${span.previousOk === false ? " · entered after a failed check" : ""}${open(span) === "unfinished" ? " · no later stage was recorded" : ""}`}><span className={barText}>{span.stage}</span></Bar>)}</Row>
      <Row label="Model" detail="Model calls; each bar runs from the previous event to the recorded usage update">{activity.modelCalls.map((call, index) => <Bar key={index} start={call.start} end={call.end} from={start} total={total} className={call.responded ? "bg-chart-2/80" : "bg-destructive/50"} label={`Model call ${call.total}${call.calls > 1 ? ` (${call.calls} attempts)` : ""} · ${call.stage} · ${call.responded ? `${compact(call.inputTokens)} in / ${compact(call.outputTokens)} out tokens` : "no response recorded"} · ${clock(call.end - call.start)} since previous event`} />)}</Row>
      <Row label="Tools" detail="Lint, simulation, synthesis, reports, file edits and rejected calls">{tools.map((span, index) => <Bar key={index} start={span.start} end={at(span)} from={start} total={total} className={toolTone(span)} label={`${toolLabel(span.tool)}${span.ok === false ? " failed" : ""}${toolSummary(span) ? ` · ${toolSummary(span)}` : ""} · ${clock(at(span) - span.start)}${open(span) === "unfinished" ? " · no finish event recorded" : ""}`} />)}</Row>
      {flows.map((variant) => { const span = variant.span!; return <Row key={variant.key} label={variant.metric ? `Flow ${variant.metric.flow_index}` : variant.status === "running" ? "Flow running" : variant.status === "failed" ? "Flow failed" : "Flow unfinished"} detail={variant.metric?.run_tag ?? (typeof span.result?.run_tag === "string" ? span.result.run_tag : undefined)}><Bar start={span.start} end={at(span)} from={start} total={total} className={flowTone(variant)} label={`LibreLane ${variant.status} · ${clock(at(span) - span.start)}${variant.metric ? ` · ${number(variant.metric.area_um2)} µm² · WNS ${number(variant.metric.wns_ns, 3)} ns` : ""}`}><span className={barText}>{variant.status === "running" ? replay ? "recorded" : "running" : clock(at(span) - span.start)}</span></Bar></Row>; })}
    </ol>
    <div className="ml-26 flex justify-between font-mono text-[10px] text-muted-foreground" aria-hidden="true">{[0, 0.25, 0.5, 0.75, 1].map((fraction) => <span key={fraction}>{clock(total * fraction)}</span>)}</div>
  </figure>;
}

export function AgentActivity({ run, activity, variants, ongoing }: { run: PublicRun; activity: RunActivity; variants: FlowVariant[]; ongoing: boolean }) {
  return <Tabs defaultValue="compact" className="gap-0">
    <Panel id="agent-activity-title" title={run.is_replay ? "Recorded agent activity" : "Agent activity"} aside={<TabsList aria-label="Agent activity view"><TabsTrigger value="compact" className="text-xs">Compact</TabsTrigger><TabsTrigger value="detailed" className="text-xs">Each agent</TabsTrigger></TabsList>}>
      <TabsContent value="compact" className="grid min-w-0 xl:grid-cols-[minmax(320px,.8fr)_minmax(0,2fr)] xl:divide-x max-xl:divide-y">
        <Now run={run} activity={activity} variants={variants} ongoing={ongoing} />
        <BuildTrace activity={activity} variants={variants} replay={run.is_replay} ongoing={ongoing} />
      </TabsContent>
      <TabsContent value="detailed" className="min-w-0"><AgentRoster run={run} activity={activity} variants={variants} ongoing={ongoing} /></TabsContent>
    </Panel>
  </Tabs>;
}
