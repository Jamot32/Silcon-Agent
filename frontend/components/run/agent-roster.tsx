"use client";

import type { ReactNode } from "react";
import { Bot, CircleAlert, FileCode, FlaskConical, Image as ImageIcon, Layers, ScrollText, ShieldAlert, StickyNote, Workflow, Wrench, type LucideIcon } from "lucide-react";
import type { JsonValue, PublicRun } from "@/lib/api";
import { agentOf, blocked, modelTools, toolSummary, type FlowVariant, type ModelCall, type RunActivity, type ToolSpan } from "@/lib/run-activity";
import { Spinner } from "@/components/ui/spinner";
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceDescription, TraceIcon, TraceLine, TraceTitle } from "@/components/ui/trace";
import { cn } from "@/lib/utils";
import { compact, duration, number, toolLabel } from "./format";
import { Signoff } from "./run-inspection";

// Roles and boundaries restate backend/app/agent/orchestrator.py and prompts.py; every entry below them comes from run events.
const roles = [
  { id: "orchestrator", name: "Orchestrator", kind: "Host process · deterministic Python, not a model", icon: Workflow, boundary: "Runs the stage pipeline, hands each stage to a model role, enforces tool permissions, and itself runs synthesis, the flows it controls, layout renders, signoff report reads and packaging." },
  { id: "SPEC", name: "Spec writer", kind: "Model role · SPEC stage", icon: Bot, boundary: "No tools. Returns DesignSpec JSON, which the orchestrator validates." },
  { id: "RTL", name: "RTL designer", kind: "Model role · RTL stage", icon: Bot, boundary: "Writes src/ only and may read tests but not edit them. Must record a hypothesis before repairing a failure." },
  { id: "VERIFY", name: "Test author", kind: "Model role · VERIFY stage", icon: Bot, boundary: "Reads and writes test/*.py only. The RTL is hidden from it, so its tests come from the spec." },
  { id: "OPTIMIZE", name: "PPA optimizer", kind: "Model role · OPTIMIZE stage", icon: Bot, boundary: "Proposes up to three LibreLane flows per batch. RTL edits must re-pass the existing tests first." },
];
const roleName = (id: string) => roles.find((role) => role.id === id)?.name ?? id;
const terminalStages = new Set(["DONE", "FAIL", "FAILED"]);
const clock = (ms: number) => duration(Math.max(0, ms) / 1000);
const took = (ms: number) => ms < 10_000 ? `${(Math.max(0, ms) / 1000).toFixed(1)} s` : clock(ms);
const runningLabel = (spans: ToolSpan[]) => [...spans.reduce((counts, span) => counts.set(span.tool, (counts.get(span.tool) ?? 0) + 1), new Map<string, number>())].map(([tool, count]) => `${count > 1 ? `${count} × ` : ""}${toolLabel(tool)}`).join(", ");
const text = (value: JsonValue | undefined): string | null => typeof value === "string" && value ? value : null;
const block = "mt-1 max-h-64 overflow-auto rounded-md bg-muted/40 p-2 font-mono text-[10px] leading-relaxed whitespace-pre";

interface Entry { order: number; at: number; icon: LucideIcon; title: string; status?: "running" | "error" | "pending"; body?: ReactNode }

function Diff({ diff }: { diff: string }) {
  return <pre className={block}>{diff.split("\n").map((line, index) => <span key={index} className={cn("block", /^\+(?!\+\+)/.test(line) && "text-success", /^-(?!--)/.test(line) && "text-destructive", line.startsWith("@@") && "text-chart-2")}>{line || " "}</span>)}</pre>;
}

function Cases({ cases }: { cases: JsonValue[] }) {
  return <ul className="mt-1 space-y-0.5 text-[11px]">{cases.map((item, index) => {
    const value = item !== null && typeof item === "object" && !Array.isArray(item) ? item : {};
    return <li key={index} className={cn(value.ok === false && "text-destructive", value.ok !== false && value.ok !== true && "text-muted-foreground")}>{value.ok === false ? "✗" : value.ok === true ? "✓" : "–"} <span className="font-mono">{text(value.test) ?? `case ${index + 1}`}</span>{text(value.message) ? ` · ${text(value.message)}` : ""}</li>;
  })}</ul>;
}

const flowName = (variant: FlowVariant | undefined) => variant?.metric ? `Flow ${variant.metric.flow_index}` : variant?.status === "running" ? "Flow running" : variant?.status === "failed" ? "Flow failed" : variant?.status === "unavailable" ? "Flow measurements unavailable" : "Flow unfinished";
const callId = (span: ToolSpan) => span.agent === "orchestrator" ? "" : ` · call id ${span.id}`;

function toolEntry(span: ToolSpan, variants: FlowVariant[], ongoing: boolean, replay: boolean, end: number, runId: string): Entry {
  const result = span.result ?? {}, summary = toolSummary(span);
  const base = { order: span.order, at: span.start };
  if (span.end === null) return { ...base, icon: Wrench, title: `${ongoing ? "Running" : "No finish recorded for"} ${toolLabel(span.tool)}${span.tool === "run_flow" ? callId(span) : ""}${ongoing && !replay ? ` · ${clock(end - span.start)}` : ""}`, status: ongoing ? "running" : "pending" };
  if (blocked(span)) return { ...base, icon: ShieldAlert, status: "error", title: `Blocked by the orchestrator's policy: ${toolLabel(span.tool)} · ${text(result.error) ?? "no reason recorded"}` };
  const failed = span.ok === false ? "error" as const : undefined;
  const time = ` · ${took(span.end - span.start)}`;
  if (span.tool === "write_file") {
    const diff = text(result.diff);
    const lines = diff?.split("\n") ?? [];
    const added = lines.filter((line) => /^\+(?!\+\+)/.test(line)).length, removed = lines.filter((line) => /^-(?!--)/.test(line)).length;
    return { ...base, icon: FileCode, status: failed, title: `Wrote ${span.path ?? "a file"}${diff ? ` · +${added} −${removed}` : ""}${failed ? ` · ${summary ?? "failed"}` : ""}`, body: diff ? <Diff diff={diff} /> : undefined };
  }
  if (span.tool === "run_tests") return { ...base, icon: FlaskConical, status: failed, title: `${toolLabel(span.tool)} · ${summary ?? "no result"}${time}`, body: Array.isArray(result.cases) && result.cases.length ? <Cases cases={result.cases} /> : undefined };
  if (span.tool === "run_flow") {
    const variant = variants.find((item) => item.span === span);
    return { ...base, icon: Layers, status: failed, title: `${span.agent === "orchestrator" ? "Ran" : "Launched"} LibreLane ${variant ? flowName(variant) : "flow"}${callId(span)}${time}${failed ? ` · ${summary ?? "failed"}` : ""}` };
  }
  if (span.tool === "render_layout") {
    // Replays keep the source run's image_url in tool results; serve the tag from this run like FlowComparison does.
    const tag = text(result.image_url)?.split("/").at(-1)?.replace(/\.png$/, "") ?? null;
    return { ...base, icon: ImageIcon, status: failed, title: `Rendered GDS layout${tag ? ` · ${tag}` : ""}${failed ? ` · ${summary ?? "failed"}` : ""}`, body: tag && !failed ? <img src={`/api/runs/${encodeURIComponent(runId)}/layout/${encodeURIComponent(tag)}.png`} alt={`Real sky130 GDS layout for ${tag}`} loading="lazy" className="mt-1 h-32 rounded-md bg-black/40 object-contain" /> : undefined };
  }
  const log = text(result.text) ?? text(result.log_tail);
  const errors = Array.isArray(result.errors) && result.errors.length ? result.errors.map((item) => typeof item === "string" ? item : JSON.stringify(item)).join("\n") : null;
  const label = span.tool === "read_report" && text(result.path) ? `Read report ${text(result.path)!.split("/").at(-1)}` : toolLabel(span.tool);
  return { ...base, icon: span.tool === "read_report" ? ScrollText : Wrench, status: failed, title: `${label}${summary && span.tool !== "read_report" ? ` · ${summary}` : ""}${time}`, body: errors ?? log ? <pre className={block}>{errors ?? log}</pre> : undefined };
}

function modelEntry(call: ModelCall, next: number, activity: RunActivity): Entry {
  const proposed = activity.tools.filter((span) => span.agent === call.agent && span.order > call.order && span.order < next).length;
  const usage = call.responded ? `${compact(call.inputTokens)} in / ${compact(call.outputTokens)} out tokens` : "no response recorded";
  const followed = call.agent === "orchestrator" ? ` · no tools are allowed in ${call.stage}` : call.responded ? ` · ${proposed ? `${proposed} tool ${proposed === 1 ? "call" : "calls"} followed` : "no tool calls followed"}` : "";
  return { order: call.order, at: call.end, icon: Bot, status: call.responded ? undefined : "error", title: `${call.responded ? "Model response" : "Model call"} in ${call.stage}${call.calls > 1 ? ` (${call.calls} attempts)` : ""} · ${usage}${followed}` };
}

function entries(id: string, activity: RunActivity, variants: FlowVariant[], ongoing: boolean, replay: boolean, runId: string): Entry[] {
  const end = activity.end ?? 0, list: Entry[] = [];
  if (id === "orchestrator") for (const span of activity.stages) list.push({
    order: span.order, at: span.start, icon: Workflow, status: span.previousOk === false || span.stage.startsWith("FAIL") ? "error" : undefined,
    title: span.stage === "DONE" ? "Finished the run" : terminalStages.has(span.stage) ? "Stopped the run" : `Started ${span.stage}${span.previousOk === false ? " after a failed check" : ""}`,
    body: span.goal && !terminalStages.has(span.stage) ? <p className="mt-1 text-[11px] leading-relaxed">Goal: {span.goal}</p> : undefined,
  });
  const calls = activity.modelCalls;
  calls.forEach((call, index) => { if (call.agent === id) list.push(modelEntry(call, calls[index + 1]?.order ?? Infinity, activity)); });
  for (const span of activity.tools) if (span.agent === id && span.tool !== "record_note") list.push(toolEntry(span, variants, ongoing, replay, end, runId));
  for (const note of activity.notes) if (note.agent === id) list.push({
    order: note.order, at: note.at, icon: note.kind === "error" ? CircleAlert : StickyNote, status: note.kind === "error" ? "error" : undefined,
    title: note.kind === "error" ? "Stopped with an error" : "Recorded a note", body: <p className="mt-1 text-[11px] leading-relaxed whitespace-pre-wrap">{note.text}{note.detail ? `\nNext: ${note.detail}` : ""}</p>,
  });
  const spec = activity.designSpec?.spec;
  if (id === "SPEC" && spec) {
    const count = (key: string) => Array.isArray(spec[key]) ? spec[key].length : 0;
    list.push({
      order: activity.designSpec!.order, at: activity.designSpec!.at, icon: FileCode,
      title: `Produced DesignSpec · ${text(spec.top_module) ?? "design"} · ${count("ports")} ports · ${count("test_plan")} planned tests`,
      body: <div className="mt-1 space-y-1 text-[11px] leading-relaxed">{text(spec.summary) ? <p>{text(spec.summary)}</p> : null}{Array.isArray(spec.test_plan) ? <ol className="list-decimal pl-4">{spec.test_plan.map((item, index) => <li key={index}>{String(item)}</li>)}</ol> : null}</div>,
    });
  }
  return list.sort((a, b) => a.order - b.order);
}

function Feed({ list, start }: { list: Entry[]; start: number }) {
  if (!list.length) return <p className="p-3 text-xs text-muted-foreground">No recorded actions yet.</p>;
  return <Trace className="max-h-80 overflow-y-auto border-t p-3">{list.map((entry) => {
    const line = <TraceLine status={entry.status}>
      <TraceIcon>{entry.status === "running" ? <Spinner /> : <entry.icon />}</TraceIcon>
      <TraceTitle className="text-xs whitespace-normal">{entry.title}</TraceTitle>
      <TraceDescription className="font-mono text-[10px]">{clock(entry.at - start)}</TraceDescription>
    </TraceLine>;
    return entry.body ? <TraceCollapsible key={entry.order}><TraceCollapsibleTrigger aria-label={`Details: ${entry.title}`}>{line}</TraceCollapsibleTrigger><TraceCollapsibleContent>{entry.body}</TraceCollapsibleContent></TraceCollapsible> : <div key={entry.order}>{line}</div>;
  })}</Trace>;
}

function status(id: string, list: Entry[], run: PublicRun, activity: RunActivity, ongoing: boolean): { label: string; live: boolean } {
  if (id === "orchestrator") {
    if (!ongoing) return { label: run.status === "done" ? "Finished" : run.status === "cancelled" ? "Cancelled" : "Stopped", live: false };
    if (run.stage === "REVIEW") return { label: run.review_submitted ? "Applying your review" : "Waiting for your review", live: true };
    return { label: activity.active && activity.active !== "orchestrator" ? `Handed off to ${roleName(activity.active)}` : activity.stages.length ? "Running its own step" : "Queued", live: true };
  }
  if (ongoing && activity.active === id) return { label: "Active", live: true };
  const last = activity.stages.findLast((span) => !terminalStages.has(span.stage))?.stage;
  const stopped = !ongoing && run.status !== "done" && last !== undefined && agentOf(last) === id;
  return { label: stopped ? "Stopped here" : list.length ? ongoing ? "Idle" : "Finished" : ongoing ? "Waiting" : "Not used in this run", live: false };
}

function AgentCard({ role, run, activity, variants, ongoing }: { role: typeof roles[number]; run: PublicRun; activity: RunActivity; variants: FlowVariant[]; ongoing: boolean }) {
  const list = entries(role.id, activity, variants, ongoing, run.is_replay, run.id);
  const state = status(role.id, list, run, activity, ongoing);
  const calls = activity.modelCalls.filter((call) => call.agent === role.id);
  const tools = activity.tools.filter((span) => span.agent === role.id);
  const running = ongoing ? tools.filter((span) => span.end === null) : [];
  const now = running.length ? `Running ${runningLabel(running)}`
    : state.live && role.id !== "orchestrator" ? `Its stage is active; no tool is running${run.is_replay ? " at this point in the recording" : ""}.`
    : list.at(-1)?.title ?? "Nothing yet.";
  const allowed = modelTools[role.id];
  const Icon = role.icon;
  return <article id={`agent-${role.id}`} className={cn("flex min-w-0 scroll-mt-4 flex-col rounded-lg border bg-card", state.live && role.id !== "orchestrator" && "border-primary ring-1 ring-primary/40")} data-testid="agent-card" data-agent={role.id} data-status={state.label}>
    <header className="flex items-start gap-2.5 p-3">
      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md bg-muted [&_svg]:size-4" aria-hidden="true"><Icon /></span>
      <div className="min-w-0 flex-1"><h3 className="text-sm font-semibold">{role.name}</h3><p className="text-[11px] text-muted-foreground">{role.kind}</p></div>
      <span className={cn("flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]", state.live ? "border-primary/50 text-primary" : "text-muted-foreground")}>{state.live ? <Spinner className="size-3" aria-hidden="true" role={undefined} /> : null}{state.label}</span>
    </header>
    <div className="space-y-2 px-3 pb-3 text-xs">
      <p className="line-clamp-2" title={now}><span className="text-muted-foreground">Now: </span>{now}</p>
      <dl className="flex gap-4">{[[role.id === "orchestrator" ? "Model calls" : "Model calls in stage", number(calls.reduce((sum, call) => sum + call.calls, 0), 0)], ["Tokens", compact(calls.reduce((sum, call) => sum + call.inputTokens + call.outputTokens, 0))], ["Tool calls", number(tools.length, 0)]].map(([label, value]) => <div key={label}><dt className="text-[10px] text-muted-foreground">{label}</dt><dd className="font-mono tabular-nums">{value}</dd></div>)}</dl>
      <p className="text-[11px] leading-relaxed text-muted-foreground">{role.boundary}</p>
      {allowed?.size ? <ul className="flex flex-wrap gap-1" aria-label={`Tools the ${role.name} may propose`}>{[...allowed].map((tool) => <li key={tool} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{tool}</li>)}</ul> : null}
    </div>
    <Feed list={list} start={activity.start ?? 0} />
  </article>;
}

function FlowWorker({ variant, end, ongoing, replay }: { variant: FlowVariant; end: number; ongoing: boolean; replay: boolean }) {
  const span = variant.span!, metric = variant.metric, result = span.result ?? {};
  const log = text(result.log_tail);
  const label = variant.status === "running" ? replay ? "In progress in the recording" : `Running · ${clock(end - span.start)}` : variant.status === "measured" ? `Measured · ${clock(span.end! - span.start)}` : variant.status === "failed" ? `Failed${metric ? " · measurements available" : ""}` : variant.status === "unavailable" ? "Measurements unavailable" : "No finish recorded";
  return <article className="flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3 text-xs" data-testid="flow-worker" data-status={variant.status}>
    <div>
      <h4 className="text-sm font-medium">{flowName(variant)}</h4>
      <p className="text-[11px] [overflow-wrap:anywhere] text-muted-foreground">Requested by the {roleName(span.agent)} in {span.stage}{callId(span)}</p>
      <p className={cn("mt-1 flex items-center gap-1.5 text-[11px]", variant.status === "failed" ? "text-destructive" : variant.status === "running" ? "text-primary" : "text-muted-foreground")}>{variant.status === "running" && ongoing ? <Spinner className="size-3" aria-hidden="true" role={undefined} /> : null}{label}</p>
    </div>
    {variant.status === "failed" ? <p className="text-destructive">{toolSummary(span) ?? "The flow reported failure."}</p> : null}
    {metric ? <p className="flex flex-wrap gap-x-3 gap-y-1 tabular-nums"><span>{number(metric.area_um2)} µm²</span><span>WNS {number(metric.wns_ns, 3)} ns</span><span>{number(metric.power_mw, 4)} mW</span><span>{number(metric.cell_count, 0)} cells</span><span>DRC <Signoff value={metric.drc_ok} /></span><span>LVS <Signoff value={metric.lvs_ok} /></span></p>
      : variant.status === "unfinished" ? <p className="text-muted-foreground">The run ended before this flow reported a result.</p>
      : variant.status === "running" ? <p className="text-muted-foreground">Placement, routing and signoff run in a sandboxed LibreLane container; its log arrives when it finishes.</p> : <p className="text-muted-foreground">No measured PPA is available for this attempt.</p>}
    {log ? <details><summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">LibreLane log tail</summary><pre className={block}>{log}</pre></details> : null}
  </article>;
}

function Chip({ href, live, children }: { href: string; live: boolean; children: ReactNode }) {
  return <a href={href} className={cn("rounded-full border px-2 py-0.5 hover:bg-muted", live ? "border-primary text-primary" : "text-muted-foreground")}>{live ? <span className="sr-only">Active: </span> : null}{children}</a>;
}

export function AgentRoster({ run, activity, variants, ongoing }: { run: PublicRun; activity: RunActivity; variants: FlowVariant[]; ongoing: boolean }) {
  const workers = variants.filter((variant) => variant.span);
  const end = activity.end ?? 0;
  return <div className="space-y-4 p-4" data-testid="agent-roster">
    <nav aria-label="Agents" className="flex flex-wrap items-center gap-1.5 text-[11px]">
      {roles.map((role) => <Chip key={role.id} href={`#agent-${role.id}`} live={ongoing && activity.active === role.id}>{role.name}</Chip>)}
      {workers.map((variant) => <Chip key={variant.key} href="#agent-flow-workers" live={ongoing && variant.status === "running"}>{flowName(variant)}</Chip>)}
    </nav>
    <p className="text-[11px] text-muted-foreground">Model calls are listed under the stage they happened in; the events do not record what each call was for.</p>
    <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">{roles.map((role) => <AgentCard key={role.id} role={role} run={run} activity={activity} variants={variants} ongoing={ongoing} />)}</div>
    {workers.length ? <section id="agent-flow-workers" className="scroll-mt-4 space-y-2" aria-labelledby="flow-workers-title">
      <div><h3 id="flow-workers-title" className="text-sm font-semibold">Sub-agents: LibreLane flow workers</h3><p className="text-[11px] text-muted-foreground">Physical flows run as separate sandboxed place-and-route jobs. Rejected calls may stop before launch. Batches from the optimizer run in parallel.</p></div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{workers.map((variant) => <FlowWorker key={variant.key} variant={variant} end={end} ongoing={ongoing} replay={run.is_replay} />)}</div>
    </section> : null}
  </div>;
}
