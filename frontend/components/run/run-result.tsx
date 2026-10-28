"use client";

import Link from "next/link";
import { ArrowLeft, CircleAlert, Download, Info } from "lucide-react";
import { bundleUrl, layoutUrl } from "@/lib/api";
import { useRun } from "@/lib/use-run";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { AgentLog } from "./agent-log";
import { ReplayBadge, StatusBadge } from "./badges";
import { RunUnavailable } from "./loading-state";
import { LayoutViewer } from "./layout-viewer";
import { ResultMeasurements } from "./result-measurements";
import { ReplaySource, StarterNotice } from "./run-origin";
import { number, replayLabel, title, usageLabel } from "./format";

export function RunResult({ id }: { id: string }) {
  const { run, events, metrics, loading, error } = useRun(id);
  if (!run) return <RunUnavailable title={loading ? "Opening the result…" : "Result unavailable."} description={error ?? "Loading the selected physical run and design log."} />;
  const selected = metrics.find((metric) => metric.run_tag === run.best_run_tag);
  const partial = selected ?? metrics.at(-1);
  const targets = { ...run.design_spec?.targets, ...run.targets };
  const layout = run.best_run_tag ? { run_tag: run.best_run_tag, image_url: layoutUrl(id, run.best_run_tag) } : null;
  const name = run.preset_id ? title(run.preset_id) : "Chip design";
  const top = run.design_spec?.top_module;
  return <div className="space-y-4" data-testid="result-dashboard" data-is-replay={run.is_replay}>
    <header className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0 space-y-2"><div className="flex flex-wrap items-center gap-3"><h1 className="text-3xl font-semibold tracking-tight break-words">{name}{top ? <span className="font-normal text-muted-foreground"> / {top}</span> : null}</h1>{run.is_replay ? <ReplayBadge>{replayLabel(run)}</ReplayBadge> : null}</div><p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground [&>span+span]:before:mr-3 [&>span+span]:before:text-muted-foreground/50 [&>span+span]:before:content-['•']"><span>Run <code className="ml-1 font-mono text-xs">{run.id.slice(0, 8)}</code></span><span>{run.llm_provider === "codex" ? "Codex / ChatGPT" : "Meta / Muse Spark"}</span><span>{run.is_replay ? "Recorded " : ""}{run.cost_usd == null ? "USD unavailable" : `$${number(run.cost_usd, 4)} USD`}</span>{run.is_replay ? <ReplaySource recordingId={run.recording_id} /> : null}{run.is_replay ? <span>{usageLabel(run)}</span> : null}</p><p className="flex items-center gap-3 text-sm text-muted-foreground"><StatusBadge status={run.status} data-testid="run-status" data-status={run.status} /><span>{metrics.length} {run.is_replay ? "recorded" : "measured"} physical run{metrics.length === 1 ? "" : "s"}</span></p></div><div className="flex w-full gap-2 sm:w-auto"><Button variant="outline" size="lg" className="flex-1 sm:flex-none" asChild><Link href={`/runs/${id}`}><ArrowLeft data-icon="inline-start" />{run.is_replay ? "Back to replay" : "Back to live run"}</Link></Button>{run.status === "done" ? <Button size="lg" className="flex-1 sm:flex-none" asChild><a data-testid="bundle-download" href={bundleUrl(id)}><Download data-icon="inline-start" />Download bundle</a></Button> : null}</div></header>
    <StarterNotice starterId={run.starter_id} />
    {run.error || error ? <Alert variant="destructive"><CircleAlert /><AlertDescription>{run.error || error}</AlertDescription></Alert> : null}
    {!selected && partial ? <Alert><Info /><AlertDescription>No final physical run is selected. Measurements below are from the latest recorded flow, {partial.run_tag}.</AlertDescription></Alert> : null}
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(400px,1fr)]"><LayoutViewer key={run.best_run_tag ?? "none"} layout={layout} metrics={metrics} runId={id} title={run.best_run_tag ? "Selected layout" : "Physical layout"} variant="result" imageTestId="result-layout-image" emptyMessage="No selected physical layout is available for this run." /><ResultMeasurements metric={partial} targets={targets} tapeoutReady={run.tapeout_ready} /></div>
    <AgentLog events={events} spec={run.spec_text} title={run.is_replay ? "Recorded design log" : "Design log"} className="h-96" />
  </div>;
}
