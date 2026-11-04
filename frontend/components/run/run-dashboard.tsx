"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, CircleAlert, Download, Square } from "lucide-react";
import { bundleUrl } from "@/lib/api";
import { useRun } from "@/lib/use-run";
import { dashboardLayout, isTerminal } from "@/lib/run-state";
import { flowVariants, runActivity } from "@/lib/run-activity";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ReplayBadge, StatusBadge } from "./badges";
import { RunUnavailable } from "./loading-state";
import { StageTimeline } from "./stage-timeline";
import { AgentLog } from "./agent-log";
import { SourcePanel } from "./source-panel";
import { RunInspection } from "./run-inspection";
import { LayoutViewer } from "./layout-viewer";
import { FlowComparison } from "./flow-comparison";
import { AgentActivity } from "./agent-activity";
import { ReplaySource, RevisionNotice, StarterNotice } from "./run-origin";
import { ReviseRun } from "./revise-run";
import { SpecReview } from "./spec-review";
import { elapsed, number, replayLabel, title, usageLabel } from "./format";

export function RunDashboard({ id }: { id: string }) {
  const { run, events, files, metrics, latestLayout, testResults, latestDiffs, loading, error, connection, cancel, refresh } = useRun(id);
  const [now, setNow] = useState(() => Date.now());
  const [cancelError, setCancelError] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const active = run?.status === "running" || run?.status === "pending";
  // cancel_requested is still being torn down by the worker; only a terminal status ends the activity views.
  const ongoing = !!run && !isTerminal(run.status);
  useEffect(() => {
    if (!ongoing) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [ongoing]);
  // Live runs extend open spans to now; replays stay on their recorded clock.
  const live = ongoing && run?.is_replay === false;
  const activity = useMemo(() => runActivity(events, live ? now : undefined), [events, live, now]);
  const variants = useMemo(() => flowVariants(activity, metrics, events, !ongoing), [activity, metrics, events, ongoing]);
  if (!run) return <RunUnavailable title={loading ? "Opening the lab…" : "Run unavailable."} description={error ?? "Loading the recorded state and event stream."} />;
  const ended = events.findLast((event) => event.type === "run_finished")?.ts ?? now;
  const layout = dashboardLayout(run, latestLayout);
  const name = run.preset_id ? title(run.preset_id) : "Chip design";
  const top = typeof run.design_spec?.top_module === "string" ? run.design_spec.top_module : null;
  async function stop() {
    setCancelling(true);
    setCancelError("");
    try { await cancel(); } catch (reason) { setCancelError(reason instanceof Error ? reason.message : "Could not cancel this run."); }
    finally { setCancelling(false); }
  }
  const meta = [
    { label: "Run", value: run.id.slice(0, 8), title: run.id, mono: true },
    { label: run.is_replay ? "Recorded provider" : run.llm_provider === "codex" ? "Plan" : "Model", value: run.llm_provider === "codex" ? "Codex / ChatGPT" : "Meta / Muse Spark" },
    { label: run.is_replay ? "Recorded cost (USD)" : "Cost (USD)", value: run.cost_usd == null ? "unavailable" : `$${number(run.cost_usd, 4)}`, title: run.cost_usd == null ? "ChatGPT plan usage does not provide dollar pricing." : undefined },
    { label: run.is_replay ? "Playback elapsed" : "Elapsed", value: elapsed(run.created_at, active ? now : ended), mono: true },
  ];
  return <div className="space-y-3" data-testid="run-dashboard" data-is-replay={run.is_replay}>
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3"><div className="flex min-w-0 items-center gap-3"><h1 className="text-2xl font-semibold tracking-tight break-words">{name}{top ? <span className="font-normal text-muted-foreground"> / {top}</span> : null}</h1>{run.is_replay ? <ReplayBadge>{replayLabel(run)}</ReplayBadge> : null}</div>
      <dl className="grid w-full grid-cols-2 gap-x-4 gap-y-2 text-sm sm:flex sm:w-auto sm:flex-wrap sm:items-center sm:gap-x-0 sm:divide-x">{meta.map((item) => <div key={item.label} className="sm:px-4 sm:first:pl-0"><dt className="font-mono text-[11px] text-muted-foreground">{item.label}</dt><dd title={item.title} className={cn("font-medium whitespace-nowrap", item.mono && "font-mono")}>{item.value}</dd></div>)}</dl>
      <div className="ml-auto flex flex-wrap gap-2">{isTerminal(run.status) ? <ReviseRun run={run} files={files} /> : null}{active ? <Button variant="outline" onClick={stop} disabled={cancelling}><Square data-icon="inline-start" />{cancelling ? "Stopping…" : run.is_replay ? "Stop replay" : "Cancel run"}</Button> : null}{layout ? <Button variant="outline" asChild><Link href={`/runs/${id}/result`}>View result<ArrowRight data-icon="inline-end" /></Link></Button> : null}{run.status === "done" ? <Button asChild><a href={bundleUrl(id)}><Download data-icon="inline-start" />Download bundle</a></Button> : null}</div>
    </div>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground"><StatusBadge status={run.status} data-testid="run-status" data-status={run.status} /><span>{usageLabel(run)}</span>{run.is_replay ? <ReplaySource recordingId={run.recording_id} /> : null}<span className="inline-flex items-center gap-2 sm:ml-auto"><span className={cn("size-1.5 rounded-full border border-muted-foreground", connection === "open" && "border-primary bg-primary")} aria-hidden="true" />{connection === "open" ? run.is_replay ? "Replay event stream connected" : "Event stream connected" : connection === "reconnecting" ? "Reconnecting to event stream…" : active ? "Connecting to event stream…" : "Recorded event history"}</span></div>
    <StarterNotice starterId={run.starter_id} />
    <RevisionNotice run={run} events={events} ended={!ongoing} />
    <StageTimeline stage={run.stage} status={run.status} spans={activity.stages} end={activity.end} review={run.review_requested} />
    {error || run.error || cancelError ? <Alert variant="destructive"><CircleAlert /><AlertDescription>{cancelError || run.error || error}</AlertDescription></Alert> : null}
    {run.review_requested && run.stage === "REVIEW" && run.status === "running" ? <SpecReview run={run} events={events} since={live ? activity.stages.findLast((span) => span.stage === "REVIEW")?.start ?? null : null} onSubmitted={refresh} /> : null}
    <AgentActivity run={run} activity={activity} variants={variants} ongoing={ongoing} />
    <div className="grid gap-3 lg:grid-cols-2 xl:h-[510px] xl:grid-cols-[minmax(240px,.8fr)_minmax(360px,1.3fr)_minmax(360px,1.1fr)] [&>*]:max-xl:h-[440px] [&>*:last-child]:max-xl:h-auto"><AgentLog events={events} spec={run.spec_text} title={run.is_replay ? "Recorded agent log" : "Agent log"} /><SourcePanel files={files} diffs={latestDiffs} isReplay={run.is_replay} finished={!active} /><RunInspection tests={testResults} metrics={metrics} bestTag={run.best_run_tag} targetClock={run.design_spec?.targets.clock_mhz ?? run.targets.clock_mhz} isReplay={run.is_replay} finished={!active} /></div>
    <LayoutViewer key={layout?.run_tag ?? "waiting"} layout={layout} metrics={metrics} runId={run.id} emptyMessage={!active ? "No layout was produced before this run ended." : run.is_replay ? "The recorded GDS render appears during playback." : undefined} />
    <FlowComparison variants={variants} metrics={metrics} bestTag={run.best_run_tag} runId={run.id} end={live ? activity.end : null} replay={run.is_replay} />
    <p className="text-xs text-muted-foreground">{run.tapeout_ready ? "Block signoff complete." : "Tiny Tapeout wrapper and shuttle integration require separate verification."}</p>
  </div>;
}
