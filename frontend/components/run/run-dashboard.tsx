"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Download } from "lucide-react";
import { bundleUrl } from "@/lib/api";
import { useRun } from "@/lib/use-run";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StageTimeline } from "./stage-timeline";
import { AgentLog } from "./agent-log";
import { SourcePanel } from "./source-panel";
import { RunInspection } from "./run-inspection";
import { LayoutViewer } from "./layout-viewer";
import { FlowComparison } from "./flow-comparison";
import { elapsed, number, title } from "./format";

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
  const name = run.preset_id ? title(run.preset_id) : "Chip design";
  const top = typeof run.design_spec?.top_module === "string" ? run.design_spec.top_module : null;
  async function stop() {
    setCancelling(true);
    setCancelError("");
    try { await cancel(); } catch (reason) { setCancelError(reason instanceof Error ? reason.message : "Could not cancel this run."); }
    finally { setCancelling(false); }
  }
  return <div className="run-dashboard" data-testid="run-dashboard">
    <div className="run-heading-row"><div className="run-identity"><h1>{name}{top ? <span> / {top}</span> : null}</h1>{run.is_replay ? <Badge variant="outline" className="replay-badge">REPLAY</Badge> : null}</div>
      <dl className="run-meta"><div><dt>Run</dt><dd title={run.id}>{run.id.slice(0, 8)}</dd></div><div><dt>{run.llm_provider === "codex" ? "Plan" : "Model"}</dt><dd>{run.llm_provider === "codex" ? "Codex / ChatGPT" : "Meta / Muse Spark"}</dd></div><div><dt>Cost (USD)</dt><dd title={run.cost_usd == null ? "ChatGPT plan usage does not provide dollar pricing." : undefined}>{run.cost_usd == null ? "unavailable" : `$${number(run.cost_usd, 4)}`}</dd></div><div><dt>Elapsed</dt><dd>{elapsed(run.created_at, active ? now : ended)}</dd></div></dl>
      <div className="run-actions">{active ? <Button variant="outline" onClick={stop} disabled={cancelling}>{cancelling ? "Cancelling…" : "Cancel run"}</Button> : null}{latestLayout ? <Button variant="outline" asChild><a href="#final-layout">View result</a></Button> : null}{run.status === "done" ? <Button asChild><a href={bundleUrl(id)}><Download data-icon="inline-start" />Download bundle</a></Button> : null}</div>
    </div>
    <div className="run-state-row"><span data-testid="run-status" data-status={run.status} className={run.status === "failed" ? "fail-text" : run.status === "done" ? "pass-text" : "muted"}>{title(run.status)}</span><span>{run.input_tokens + run.output_tokens > 0 ? `${number(run.input_tokens + run.output_tokens, 0)} tokens · ${run.call_count} calls` : "Waiting for model usage"}</span><span className={connection === "open" ? "connection open" : "connection"}>{connection === "open" ? "Event stream connected" : connection === "reconnecting" ? "Reconnecting to event stream…" : active ? "Connecting to event stream…" : "Recorded event history"}</span></div>
    <StageTimeline stage={run.stage} status={run.status} />
    {error || run.error || cancelError ? <div className="run-error" role="alert">{cancelError || run.error || error}</div> : null}
    <div className="dashboard-grid"><AgentLog events={events} /><SourcePanel files={files} diffs={latestDiffs} /><RunInspection tests={testResults} metrics={metrics} bestTag={run.best_run_tag} targetClock={run.design_spec?.targets.clock_mhz ?? run.targets.clock_mhz} /></div>
    <LayoutViewer key={latestLayout?.run_tag ?? "waiting"} layout={latestLayout} metrics={metrics} runId={run.id} />
    <FlowComparison metrics={metrics} bestTag={run.best_run_tag} />
    <p className="integration-note">{run.tapeout_ready ? "Block signoff complete." : "Tiny Tapeout wrapper and shuttle integration require separate verification."}</p>
  </div>;
}
