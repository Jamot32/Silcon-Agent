"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Download } from "lucide-react";
import { bundleUrl } from "@/lib/api";
import { useRun } from "@/lib/use-run";
import { dashboardLayout } from "@/lib/run-state";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StageTimeline } from "./stage-timeline";
import { AgentLog } from "./agent-log";
import { SourcePanel } from "./source-panel";
import { RunInspection } from "./run-inspection";
import { LayoutViewer } from "./layout-viewer";
import { FlowComparison } from "./flow-comparison";
import { ReplaySource, StarterNotice } from "./run-origin";
import { elapsed, number, replayLabel, title, usageLabel } from "./format";

export function RunDashboard({ id }: { id: string }) {
  const { run, events, files, metrics, latestLayout, testResults, latestDiffs, loading, error, connection, cancel } = useRun(id);
  const [now, setNow] = useState(() => Date.now());
  const [cancelError, setCancelError] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const active = run?.status === "running" || run?.status === "pending";
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  if (!run) return <div className="dashboard-loading" role="status"><h1>{loading ? "Opening the lab…" : "Run unavailable."}</h1><p>{error ?? "Loading the recorded state and event stream."}</p><Link href="/runs" className="text-link">Return to run history →</Link></div>;
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
  return <div className="run-dashboard" data-testid="run-dashboard" data-is-replay={run.is_replay}>
    <div className="run-heading-row"><div className="run-identity"><h1>{name}{top ? <span> / {top}</span> : null}</h1>{run.is_replay ? <Badge variant="outline" className="replay-badge">{replayLabel(run)}</Badge> : null}</div>
      <dl className="run-meta"><div><dt>Run</dt><dd title={run.id}>{run.id.slice(0, 8)}</dd></div><div><dt>{run.is_replay ? "Recorded provider" : run.llm_provider === "codex" ? "Plan" : "Model"}</dt><dd>{run.llm_provider === "codex" ? "Codex / ChatGPT" : "Meta / Muse Spark"}</dd></div><div><dt>{run.is_replay ? "Recorded cost (USD)" : "Cost (USD)"}</dt><dd title={run.cost_usd == null ? "ChatGPT plan usage does not provide dollar pricing." : undefined}>{run.cost_usd == null ? "unavailable" : `$${number(run.cost_usd, 4)}`}</dd></div><div><dt>{run.is_replay ? "Playback elapsed" : "Elapsed"}</dt><dd>{elapsed(run.created_at, active ? now : ended)}</dd></div></dl>
      <div className="run-actions">{active ? <Button variant="outline" onClick={stop} disabled={cancelling}>{cancelling ? "Stopping…" : run.is_replay ? "Stop replay" : "Cancel run"}</Button> : null}{layout ? <Button variant="outline" asChild><Link href={`/runs/${id}/result`}>View result</Link></Button> : null}{run.status === "done" ? <Button asChild><a href={bundleUrl(id)}><Download data-icon="inline-start" />Download bundle</a></Button> : null}</div>
    </div>
    <div className="run-state-row"><span data-testid="run-status" data-status={run.status} className={run.status === "failed" ? "fail-text" : run.status === "done" ? "pass-text" : "muted"}>{title(run.status)}</span><span>{usageLabel(run)}</span>{run.is_replay ? <ReplaySource recordingId={run.recording_id} /> : null}<span className={connection === "open" ? "connection open" : "connection"}>{connection === "open" ? run.is_replay ? "Replay event stream connected" : "Event stream connected" : connection === "reconnecting" ? "Reconnecting to event stream…" : active ? "Connecting to event stream…" : "Recorded event history"}</span></div>
    <StarterNotice starterId={run.starter_id} />
    <StageTimeline stage={run.stage} status={run.status} />
    {error || run.error || cancelError ? <div className="run-error" role="alert">{cancelError || run.error || error}</div> : null}
    <div className="dashboard-grid"><AgentLog events={events} title={run.is_replay ? "Recorded agent log" : "Agent log"} /><SourcePanel files={files} diffs={latestDiffs} isReplay={run.is_replay} finished={!active} /><RunInspection tests={testResults} metrics={metrics} bestTag={run.best_run_tag} targetClock={run.design_spec?.targets.clock_mhz ?? run.targets.clock_mhz} isReplay={run.is_replay} finished={!active} /></div>
    <LayoutViewer key={layout?.run_tag ?? "waiting"} layout={layout} metrics={metrics} runId={run.id} emptyMessage={!active ? "No layout was produced before this run ended." : run.is_replay ? "The recorded GDS render appears during playback." : undefined} />
    <FlowComparison metrics={metrics} bestTag={run.best_run_tag} />
    <p className="integration-note">{run.tapeout_ready ? "Block signoff complete." : "Tiny Tapeout wrapper and shuttle integration require separate verification."}</p>
  </div>;
}
