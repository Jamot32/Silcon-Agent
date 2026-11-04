"use client";

import Link from "next/link";
import { ArrowLeft, CircleAlert, Code2, Download, Info } from "lucide-react";
import { bundleUrl, layoutUrl } from "@/lib/api";
import { isTerminal } from "@/lib/run-state";
import { useRun } from "@/lib/use-run";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RunActions } from "@/components/run-actions";
import { AgentLog } from "./agent-log";
import { ReplayBadge, StatusBadge } from "./badges";
import { RunUnavailable } from "./loading-state";
import { InspectableLayout } from "./layout-region-inspector";
import { ResultMeasurements } from "./result-measurements";
import { RevisionComparison } from "./revision-comparison";
import { FlowSignoffSummary } from "./flow-inspector";
import { ReplaySource, RevisionNotice, StarterNotice } from "./run-origin";
import { ReviseRun } from "./revise-run";
import { number, replayLabel, title, usageLabel } from "./format";

export function RunResult({ id }: { id: string }) {
  const { run, events, files, metrics, loading, error, refresh } = useRun(id);
  if (!run) return <RunUnavailable title={loading ? "Opening the result…" : "Result unavailable."} description={error ?? "Loading the selected physical run and design log."} />;
  const selected = metrics.find((metric) => metric.run_tag === run.best_run_tag);
  const partial = run.best_run_tag ? selected : metrics.at(-1);
  const targets = { ...run.design_spec?.targets, ...run.targets };
  const layout = run.best_run_tag ? { run_tag: run.best_run_tag, image_url: layoutUrl(id, run.best_run_tag) } : null;
  const name = run.display_name || (run.preset_id ? title(run.preset_id) : "Chip design");
  const top = run.design_spec?.top_module;
  return <div className="space-y-4" data-testid="result-dashboard" data-is-replay={run.is_replay}>
    <header className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0 max-w-full space-y-2"><div className="flex flex-wrap items-center gap-3"><h1 className="min-w-0 text-3xl font-semibold tracking-tight wrap-anywhere">{name}{top ? <span className="font-normal text-muted-foreground"> / {top}</span> : null}</h1>{run.is_replay ? <ReplayBadge>{replayLabel(run)}</ReplayBadge> : null}</div><p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground [&>span+span]:before:mr-3 [&>span+span]:before:text-muted-foreground/50 [&>span+span]:before:content-['•']"><span>Run <code className="ml-1 font-mono text-xs">{run.id.slice(0, 8)}</code></span><span>{run.execution_mode === "manual" ? "Manual build" : run.llm_provider === "codex" ? "Codex / ChatGPT" : "Meta / Muse Spark"}</span><span>{run.execution_mode === "manual" ? "No model calls" : <>{run.is_replay ? "Recorded " : ""}{run.cost_usd == null ? "USD unavailable" : `$${number(run.cost_usd, 4)} USD`}</>}</span>{run.is_replay ? <ReplaySource recordingId={run.recording_id} /> : null}{run.is_replay ? <span>{usageLabel(run)}</span> : null}</p><p className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground"><StatusBadge status={run.status} data-testid="run-status" data-status={run.status} />{run.pinned ? <Badge variant="outline">Pinned</Badge> : null}{run.archived ? <Badge variant="outline">Archived</Badge> : null}<span>{metrics.length} {run.is_replay ? "recorded" : "measured"} physical run{metrics.length === 1 ? "" : "s"}</span></p></div><div className="flex w-full flex-wrap gap-2 sm:w-auto"><Button variant="outline" size="lg" className="flex-1 sm:flex-none" asChild><Link href={`/runs/${id}/workspace`}><Code2 data-icon="inline-start" />Code workspace</Link></Button><Button variant="outline" size="lg" className="flex-1 sm:flex-none" asChild><Link href={`/runs/${id}`}><ArrowLeft data-icon="inline-start" />{run.is_replay ? "Back to replay" : "Back to live run"}</Link></Button>{isTerminal(run.status) ? <ReviseRun run={run} files={files} size="lg" /> : null}{run.status === "done" ? <Button size="lg" className="flex-1 sm:flex-none" asChild><a data-testid="bundle-download" href={bundleUrl(id)}><Download data-icon="inline-start" />Download bundle</a></Button> : null}<RunActions run={run} onChanged={refresh} /></div></header>
    <StarterNotice starterId={run.starter_id} />
    <RevisionNotice run={run} events={events} ended={isTerminal(run.status)} />
    {(run.status !== "cancelled" && run.error) || error ? <Alert variant="destructive"><CircleAlert /><AlertDescription>{error || run.error}</AlertDescription></Alert> : null}
    {run.best_run_tag && !selected ? <Alert><Info /><AlertDescription>Measurements for the selected physical run, {run.best_run_tag}, are unavailable. Its timing and signoff cannot be verified from the available records.</AlertDescription></Alert> : null}
    {!run.best_run_tag && partial ? <Alert><Info /><AlertDescription>No final physical run is selected. Measurements below are from the latest recorded flow, {partial.run_tag}.</AlertDescription></Alert> : null}
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(400px,1fr)]"><InspectableLayout key={run.best_run_tag ?? "none"} run={run} files={files} layout={layout} metrics={metrics} runId={id} title={run.best_run_tag ? "Selected layout" : "Physical layout"} variant="result" imageTestId="result-layout-image" emptyMessage="No selected physical layout is available for this run." /><div className="min-w-0 space-y-4"><ResultMeasurements metric={partial} targets={targets} tapeoutReady={run.tapeout_ready} /><FlowSignoffSummary run={run} files={files} /></div></div>
    <RevisionComparison run={run} metrics={metrics} />
    <AgentLog events={events} spec={run.spec_text} title={run.is_replay ? "Recorded design log" : "Design log"} className="h-96" />
  </div>;
}
