"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getJson, getRunMetrics, listRuns, type Metric, type Recording, type Run } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { bestMeasured, number, replayLabel, title, usageLabel } from "@/components/run/format";

export function RunHistory() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [metrics, setMetrics] = useState<Record<string, Metric[]>>({});
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const [runsResult, recordingsResult] = await Promise.allSettled([listRuns(controller.signal), getJson<Recording[]>("/api/recordings", controller.signal)]);
        if (runsResult.status === "rejected") throw runsResult.reason;
        const rows = runsResult.value;
        if (recordingsResult.status === "fulfilled") setRecordings(recordingsResult.value);
        if (controller.signal.aborted) return;
        setRuns(rows);
        const results = await Promise.allSettled(rows.slice(0, 20).map(async (run) => [run.id, await getRunMetrics(run.id, controller.signal)] as const));
        if (controller.signal.aborted) return;
        setMetrics(Object.fromEntries(results.flatMap((result) => result.status === "fulfilled" ? [result.value] : [])));
      } catch { if (!controller.signal.aborted) setError(true); }
    }
    void load();
    return () => controller.abort();
  }, []);
  return <section className="panel history-panel" aria-labelledby="history-title"><h2 id="history-title">Your runs</h2>
    {runs && runs.length > 0 ? <ul className="run-list">{runs.map((run) => {
      const source = recordings.find((recording) => recording.id === run.recording_id)?.source_run_id;
      const best = bestMeasured(metrics[run.id] ?? [], run.best_run_tag, run.design_spec?.targets.clock_mhz ?? run.targets.clock_mhz);
      return <li key={run.id}><Link href={`/runs/${run.id}`} className="history-row"><div><strong className="history-name">{typeof run.design_spec?.top_module === "string" ? run.design_spec.top_module : run.preset_id ? title(run.preset_id) : "Chip design"}{run.is_replay ? <Badge variant="outline" className="replay-badge">{replayLabel(run)}</Badge> : null}{run.starter_id ? <Badge variant="outline">Supplied faulty starter</Badge> : null}</strong><span className="history-description">{run.spec_text}</span><span className="history-meta"><span>{run.id.slice(0, 8)}</span><span>{new Date(run.created_at).toLocaleString()}</span><span>{run.stage}</span><span>{run.is_replay ? "Recorded " : ""}{run.cost_usd == null ? "cost unavailable" : `$${number(run.cost_usd, 4)}`}</span>{run.is_replay ? <span title={source ?? run.recording_id ?? undefined}>{source ? `Source run ${source.slice(0, 8)}` : `Recording ${run.recording_id ?? "unavailable"}`}</span> : null}{run.is_replay ? <span>{usageLabel(run)}</span> : null}</span></div><div className="history-metrics">{best ? <><span>{number(best.area_um2)} µm²</span><span>{number(best.wns_ns)} ns WNS</span></> : null}<span className={run.status === "done" ? "history-status pass-text" : run.status === "failed" ? "history-status fail-text" : "history-status"}>{title(run.status)}</span><span aria-hidden="true">→</span></div></Link></li>;
    })}</ul> : <div className="empty-state" aria-live="polite"><h3>{error ? "Run history could not be loaded." : runs ? "No chip designs yet." : "Checking run history…"}</h3><p>{error ? "Check the API connection and reload this page." : "Your real tool runs will appear here."}</p><Link className="text-link" href="/">Start a new design <span aria-hidden="true">→</span></Link></div>}
  </section>;
}
