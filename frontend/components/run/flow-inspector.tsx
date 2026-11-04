"use client";

import { useEffect, useState } from "react";
import { CircleAlert, RefreshCw, Search } from "lucide-react";
import type { PublicRun } from "@/lib/api";
import { getFlowDetail, reusableFlowSettings, type FlowConfig, type FlowDetail, type FlowSelector } from "@/lib/flow-inspection";
import type { FlowVariant } from "@/lib/run-activity";
import { isTerminal } from "@/lib/run-state";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { number } from "./format";
import { ReviseRun } from "./revise-run";
import { Signoff } from "./run-inspection";

function useFlowDetail(runId: string, selector: FlowSelector, enabled: boolean) {
  const eventId = "eventId" in selector ? selector.eventId : null;
  const runTag = "runTag" in selector ? selector.runTag : null;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ detail: FlowDetail | null; error: string | null; loading: boolean }>({ detail: null, error: null, loading: true });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setState({ detail: null, error: null, loading: true });
    getFlowDetail(runId, eventId !== null ? { eventId } : { runTag: runTag! }, controller.signal).then(
      (detail) => { if (!controller.signal.aborted) setState({ detail, error: null, loading: false }); },
      (reason) => { if (!controller.signal.aborted) setState({ detail: null, error: reason instanceof Error ? reason.message : "Flow evidence could not be loaded.", loading: false }); },
    );
    return () => controller.abort();
  }, [runId, eventId, runTag, enabled, attempt]);
  return { ...state, retry: () => setAttempt((value) => value + 1) };
}

const checks = [
  ["setup_violations", "Setup violations"], ["hold_violations", "Hold violations"],
  ["max_slew_violations", "Slew violations"], ["max_cap_violations", "Capacitance violations"],
  ["max_fanout_violations", "Fanout violations"], ["antenna_violating_nets", "Antenna nets"],
  ["antenna_violating_pins", "Antenna pins"],
] as const;
const known = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function ExtendedSignoff({ detail }: { detail: FlowDetail }) {
  const signoff = detail.signoff;
  const slacks = [signoff.checks.setup_wns_ns, signoff.checks.hold_wns_ns];
  const failed = [signoff.drc_ok, signoff.lvs_ok, signoff.drv_ok, signoff.gls_ok].includes(false) || checks.some(([key]) => known(signoff.checks[key]) && signoff.checks[key]! > 0) || slacks.some((value) => known(value) && value < 0);
  const incomplete = [signoff.drc_ok, signoff.lvs_ok, signoff.drv_ok, signoff.gls_ok].some((value) => value == null) || checks.some(([key]) => !known(signoff.checks[key])) || slacks.some((value) => !known(value));
  const corners = Object.entries(signoff.checks.violating_corners).filter(([, names]) => names.length > 0);
  return <section className="space-y-3" aria-label="Extended signoff checks" data-testid="extended-signoff">
    {detail.provenance.evidence_status === "invalid" ? <Alert variant="destructive"><CircleAlert /><AlertDescription>Recorded evidence failed its integrity check. These values cannot establish signoff.</AlertDescription></Alert> : failed ? <Alert variant="destructive"><CircleAlert /><AlertDescription>Recorded signoff checks failed. DRC and LVS alone do not establish complete signoff.</AlertDescription></Alert> : incomplete ? <p className="text-sm text-muted-foreground">Some signoff checks were not recorded. Unknown checks are not passes.</p> : <p className="text-sm">All listed signoff checks passed in this record.</p>}
    {detail.provenance.evidence_status === "invalid" && incomplete ? <p className="text-sm text-muted-foreground">Unknown checks are not passes.</p> : null}
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
      {([["DRC", signoff.drc_ok], ["LVS", signoff.lvs_ok], ["Electrical checks", signoff.drv_ok], ["Routed netlist simulation", signoff.gls_ok]] as const).map(([label, value]) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1"><Signoff value={value} /></dd></div>)}
      {checks.map(([key, label]) => <div key={key}><dt className="text-xs text-muted-foreground">{label}</dt><dd className={cn("mt-1 tabular-nums", known(signoff.checks[key]) && signoff.checks[key]! > 0 && "text-destructive")}>{known(signoff.checks[key]) ? number(signoff.checks[key], 0) : "Unknown"}</dd></div>)}
      {([["Setup WNS", signoff.checks.setup_wns_ns], ["Hold WNS", signoff.checks.hold_wns_ns]] as const).map(([label, value]) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className={cn("mt-1 tabular-nums", known(value) && value < 0 && "text-destructive")}>{known(value) ? `${number(value, 3)} ns` : "Unknown"}</dd></div>)}
    </dl>
    <p className="text-xs leading-relaxed text-muted-foreground">Setup and hold counts sum across corners; slew, capacitance and fanout counts use the worst corner. WNS = 0 means no negative slack was reported; it does not show positive timing margin or maximum frequency.</p>
    {corners.length ? <details><summary className="cursor-pointer rounded-sm text-sm focus-visible:outline-2 focus-visible:outline-ring">Violating corners</summary><dl className="mt-2 space-y-2 text-xs">{corners.map(([name, names]) => <div key={name}><dt className="font-medium wrap-anywhere">{name}</dt><dd className="mt-1 font-mono wrap-anywhere text-muted-foreground">{names.join(", ")}</dd></div>)}</dl></details> : null}
  </section>;
}

function ConfigSection({ title, description, config }: { title: string; description: string; config: FlowConfig | null }) {
  return <details className="rounded-lg border p-3">
    <summary className="cursor-pointer rounded-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">{title}<span className="ml-2 text-xs font-normal text-muted-foreground">{config === null ? "Unavailable" : `${Object.keys(config).length} settings`}</span></summary>
    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{description}</p>
    {config !== null && Object.keys(config).length ? <dl className="mt-3 divide-y text-xs">{Object.entries(config).map(([key, value]) => <div key={key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3 py-2"><dt className="font-mono wrap-anywhere text-muted-foreground">{key}</dt><dd className="font-mono wrap-anywhere">{Array.isArray(value) ? value.join(" × ") : String(value)}</dd></div>)}</dl> : <p className="mt-2 text-sm text-muted-foreground">{config === null ? "This configuration was not recorded." : "No overrides were recorded."}</p>}
  </details>;
}

function EvidenceError({ error, retry }: { error: string; retry: () => void }) {
  return <Alert variant="destructive"><CircleAlert /><AlertDescription><p>{error}</p><Button className="mt-2 justify-self-start" variant="outline" size="sm" onClick={retry}><RefreshCw data-icon="inline-start" />Retry evidence</Button></AlertDescription></Alert>;
}

export function FlowInspector({ run, files, variant, runTag, triggerLabel = "Inspect flow" }: { run: PublicRun; files: Record<string, string>; variant?: FlowVariant; runTag?: string; triggerLabel?: string }) {
  const [open, setOpen] = useState(false);
  const eventId = variant?.span?.finishedOrder ?? variant?.span?.order;
  const tag = runTag ?? variant?.metric?.run_tag ?? (typeof variant?.span?.result?.run_tag === "string" ? variant.span.result.run_tag : null);
  const selector: FlowSelector = eventId !== undefined ? { eventId } : { runTag: tag ?? "" };
  const { detail, error, loading, retry } = useFlowDetail(run.id, selector, open && (eventId !== undefined || !!tag));
  const reusable = detail ? reusableFlowSettings(detail) : null;
  return <Sheet open={open} onOpenChange={setOpen}>
    <SheetTrigger asChild><Button type="button" variant="outline" size="sm" disabled={eventId === undefined && !tag}><Search data-icon="inline-start" />{triggerLabel}</Button></SheetTrigger>
    <SheetContent className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl" data-testid="flow-inspector">
      <SheetHeader className="shrink-0 border-b pr-12"><SheetTitle>Flow inspection</SheetTitle><SheetDescription>{run.is_replay ? "Historical evidence from the recording." : "Recorded configuration, measurements, and diagnostics."} Missing evidence stays unknown.</SheetDescription></SheetHeader>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        {loading ? <p role="status" className="flex items-center gap-2 text-sm"><Spinner />Loading flow evidence…</p> : error ? <EvidenceError error={error} retry={retry} /> : detail ? <>
          <div className="space-y-2"><div className="flex flex-wrap items-center gap-2"><Badge variant={detail.status === "failed" ? "destructive" : "secondary"}>{detail.status === "passed" ? "Tool completed" : detail.status === "unknown" ? "Outcome unknown" : detail.status}</Badge>{detail.selected ? <Badge variant="outline">Selected result</Badge> : null}<Button size="icon-sm" variant="ghost" aria-label="Refresh flow evidence" onClick={retry}><RefreshCw /></Button></div><p className="font-mono text-xs wrap-anywhere text-muted-foreground">{detail.run_tag ?? "No physical run tag recorded"}</p><p className="text-xs text-muted-foreground">{detail.physical_flow_started === true ? "Physical design started." : detail.physical_flow_started === false ? "Stopped before physical design started." : "Physical launch evidence is unavailable."}{detail.provenance.duration_seconds !== null ? ` Duration: ${number(detail.provenance.duration_seconds, 1)} seconds.` : ""}</p></div>
          {detail.provenance.evidence_status === "invalid" ? <Alert variant="destructive"><CircleAlert /><AlertDescription>Recorded evidence failed its integrity check. Treat displayed values as unverified.</AlertDescription></Alert> : null}
          {detail.diagnostic ? <Alert variant={detail.status === "failed" ? "destructive" : "default"}><CircleAlert /><AlertDescription><p className="font-medium">Recorded diagnosis · {detail.diagnostic.kind}</p><p className="wrap-anywhere whitespace-pre-wrap">{detail.diagnostic.message}</p></AlertDescription></Alert> : <p className="text-sm text-muted-foreground">No diagnostic was recorded for this attempt.</p>}
          <section className="space-y-3" aria-label="Physical measurements"><h3 className="font-medium">Physical measurements</h3>{detail.metrics ? <dl className="grid grid-cols-2 gap-3 text-sm">{[["Configured clock", `${number(detail.metrics.clock_mhz)} MHz`], ["Area", `${number(detail.metrics.area_um2)} µm²`], ["Setup WNS", `${number(detail.metrics.wns_ns, 3)} ns`], ["TNS", `${number(detail.metrics.tns_ns, 3)} ns`], ["Reported power", `${number(detail.metrics.power_mw, 6)} mW`], ["Cells", number(detail.metrics.cell_count, 0)]].map(([label, value]) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 tabular-nums">{value}</dd></div>)}</dl> : <p className="text-sm text-muted-foreground">No measured PPA is available for this attempt.</p>}<p className="text-xs leading-relaxed text-muted-foreground">Clock is a configured target, not a measured maximum frequency. Power is the reported total from the last reported corner.</p></section>
          <ExtendedSignoff detail={detail} />
          <section className="space-y-2" aria-label="Flow configuration"><h3 className="font-medium">Flow configuration</h3><ConfigSection title="Requested overrides" description="The proposal submitted to the tool before physical planning." config={detail.requested_config} /><ConfigSection title="Planned settings" description="The host planner's settings after mapping and die sizing." config={detail.planned_config} /><ConfigSection title="Applied configuration" description="Recorded input configuration sent to LibreLane. Host signoff policy applies separately." config={detail.applied_config} /><ConfigSection title="Resolved configuration" description="Recorded LibreLane configuration after preprocessing. Only supported engineering knobs are shown." config={detail.resolved_config} /></section>
          {isTerminal(run.status) ? <section className="space-y-3 rounded-lg border p-3" aria-label="Use flow settings"><h3 className="font-medium">Prepare a follow-up</h3>{reusable ? <><p className="text-xs leading-relaxed text-muted-foreground">Copies {Object.keys(reusable.settings).join(", ")} from the {reusable.source} configuration into an editable draft. Clock targets stay separate and the planner sizes the die again. RTL reuse follows this run&apos;s selected design, not this candidate&apos;s source.</p><ReviseRun run={run} files={files} initialFlow={reusable.settings} sourceFlow={detail.run_tag ?? `attempt event ${detail.event_id}`} triggerLabel="Use settings in follow-up" /></> : <p className="text-sm text-muted-foreground">No reusable, valid engineering settings are available in this record.</p>}</section> : null}
          <section className="space-y-2" aria-label="Recorded reports"><h3 className="font-medium">Recorded reports</h3>{Object.entries(detail.reports).map(([name, report]) => <details key={name} className="rounded-lg border p-3"><summary className="cursor-pointer rounded-sm capitalize focus-visible:outline-2 focus-visible:outline-ring">{name} report <span className="text-xs normal-case text-muted-foreground">{report.available ? report.truncated ? "· excerpt" : "" : "· unavailable"}</span></summary><div className="mt-2">{report.available && report.excerpt ? <pre className="max-h-72 overflow-auto font-mono text-xs wrap-anywhere whitespace-pre-wrap">{report.excerpt}</pre> : <p className="text-xs text-muted-foreground">No report content was recorded.</p>}{report.truncated ? <p className="mt-2 text-xs text-muted-foreground">This is a bounded excerpt; the full report is not shown.</p> : null}</div></details>)}</section>
          <details className="rounded-lg border p-3"><summary className="cursor-pointer rounded-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">Evidence provenance · {detail.provenance.evidence_status}</summary><dl className="mt-3 space-y-2 text-xs">{[["Execution", detail.provenance.execution_id], ["Tool image", detail.provenance.image_id], ["Source SHA256", detail.provenance.source_sha256], ["Input SHA256", detail.provenance.input_sha256]].map(([label, value]) => <div key={label}><dt className="text-muted-foreground">{label}</dt><dd className="mt-1 font-mono wrap-anywhere">{value ?? "Unavailable"}</dd></div>)}</dl><p className="mt-3 text-xs text-muted-foreground">Frozen snapshot {detail.provenance.snapshot_available ? "available" : "unavailable"}. Configuration reuse does not reproduce an identical physical result.</p></details>
          {detail.warnings.length ? <ul className="list-disc space-y-1 pl-4 text-xs wrap-anywhere text-muted-foreground" aria-label="Evidence limitations">{detail.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul> : null}
        </> : null}
      </div>
    </SheetContent>
  </Sheet>;
}

export function FlowSignoffSummary({ run, files }: { run: PublicRun; files: Record<string, string> }) {
  const { detail, error, loading, retry } = useFlowDetail(run.id, { runTag: run.best_run_tag ?? "" }, !!run.best_run_tag);
  if (!run.best_run_tag) return null;
  return <section className="space-y-3 rounded-xl border bg-card p-4" aria-labelledby="selected-flow-checks-title" data-testid="selected-flow-checks"><div className="flex flex-wrap items-center justify-between gap-3"><h2 id="selected-flow-checks-title" className="font-medium">Selected flow checks</h2><FlowInspector run={run} files={files} runTag={run.best_run_tag} triggerLabel="Inspect selected flow" /></div><p className="text-xs text-muted-foreground">{run.is_replay ? "Historical checks from the recording's selected flow." : "Checks recorded for the exact selected physical flow."}</p>{loading ? <p role="status" className="text-sm text-muted-foreground">Loading extended signoff evidence…</p> : error ? <EvidenceError error={error} retry={retry} /> : detail ? <ExtendedSignoff detail={detail} /> : null}</section>;
}
