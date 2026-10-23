"use client";

import Link from "next/link";
import { bundleUrl, layoutUrl } from "@/lib/api";
import { useRun } from "@/lib/use-run";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AgentLog } from "./agent-log";
import { LayoutViewer } from "./layout-viewer";
import { ResultMeasurements } from "./result-measurements";
import { number, title } from "./format";

export function RunResult({ id }: { id: string }) {
  const { run, events, metrics, loading, error } = useRun(id);
  if (!run) return <div className="dashboard-loading" role="status"><h1>{loading ? "Opening the result…" : "Result unavailable."}</h1><p>{error ?? "Loading the selected physical run and design log."}</p><Link href="/runs" className="text-link">Return to run history →</Link></div>;
  const selected = metrics.find((metric) => metric.run_tag === run.best_run_tag);
  const partial = selected ?? metrics.at(-1);
  const targets = { ...run.design_spec?.targets, ...run.targets };
  const layout = run.best_run_tag ? { run_tag: run.best_run_tag, image_url: layoutUrl(id, run.best_run_tag) } : null;
  const name = run.preset_id ? title(run.preset_id) : "Chip design";
  const top = run.design_spec?.top_module;
  return <div className="result-dashboard" data-testid="result-dashboard">
    <header className="result-intro"><div><div className="result-identity"><h1>{name}{top ? <span> / {top}</span> : null}</h1>{run.is_replay ? <Badge variant="outline" className="replay-badge">REPLAY</Badge> : null}</div><p className="result-run-meta"><span>Run <code>{run.id.slice(0, 8)}</code></span><span>{run.llm_provider === "codex" ? "Codex / ChatGPT" : "Meta / Muse Spark"}</span><span>{run.cost_usd == null ? "USD unavailable" : `$${number(run.cost_usd, 4)} USD`}</span></p><p className="result-status"><strong className={run.status === "done" ? "pass-text" : run.status === "failed" ? "fail-text" : "muted"} data-testid="run-status" data-status={run.status}>{title(run.status)}</strong><span>{metrics.length} measured physical run{metrics.length === 1 ? "" : "s"}</span></p></div><div className="run-actions"><Button variant="outline" asChild><Link href={`/runs/${id}`}>Back to live run</Link></Button>{run.status === "done" ? <Button asChild><a data-testid="bundle-download" href={bundleUrl(id)}>Download bundle</a></Button> : null}</div></header>
    {run.error || error ? <div className="run-error" role="alert">{run.error || error}</div> : null}
    {!selected && partial ? <p className="result-partial-note">No final physical run is selected. Measurements below are from the latest recorded flow, {partial.run_tag}.</p> : null}
    <div className="result-grid"><LayoutViewer key={run.best_run_tag ?? "none"} layout={layout} metrics={metrics} runId={id} title={run.best_run_tag ? "Selected layout" : "Physical layout"} className="result-layout" imageTestId="result-layout-image" emptyMessage="No selected physical layout is available for this run." /><ResultMeasurements metric={partial} targets={targets} tapeoutReady={run.tapeout_ready} /></div>
    <AgentLog events={events} title="Design log" className="result-design-log" />
  </div>;
}
