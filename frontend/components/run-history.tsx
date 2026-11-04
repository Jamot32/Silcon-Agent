"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, ChevronRight } from "lucide-react";
import { getJson, getRunMetrics, listRuns, type Metric, type Recording, type Run } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Item, ItemActions, ItemContent, ItemDescription, ItemFooter, ItemGroup, ItemTitle } from "@/components/ui/item";
import { ReplayBadge, StatusBadge } from "@/components/run/badges";
import { bestMeasured, number, replayLabel, runName, usageLabel } from "@/components/run/format";

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
  return <section aria-label="Your runs">
    {runs && runs.length > 0 ? <ItemGroup className="gap-2">{runs.map((run) => {
      const source = recordings.find((recording) => recording.id === run.recording_id)?.source_run_id;
      const best = bestMeasured(metrics[run.id] ?? [], run.best_run_tag, run.design_spec?.targets.clock_mhz ?? run.targets.clock_mhz);
      return <Item key={run.id} variant="outline" asChild><Link href={`/runs/${run.id}`}>
        <ItemContent className="min-w-0 basis-80">
          <ItemTitle className="flex-wrap">{runName(run)}{run.is_replay ? <ReplayBadge>{replayLabel(run)}</ReplayBadge> : null}{run.starter_id ? <Badge variant="outline">Supplied faulty starter</Badge> : null}{run.parent_run_id ? <Badge variant="outline">Follow-up</Badge> : null}</ItemTitle>
          <ItemDescription className="max-w-3xl">{run.spec_text}</ItemDescription>
        </ItemContent>
        <ItemActions className="text-sm text-muted-foreground tabular-nums">{best ? <><span>{number(best.area_um2)} µm²</span><span>{number(best.wns_ns)} ns WNS</span></> : null}<StatusBadge status={run.status} /><ChevronRight className="size-4" aria-hidden="true" /></ItemActions>
        <ItemFooter className="justify-start gap-x-3 text-xs text-muted-foreground"><span className="font-mono">{run.id.slice(0, 8)}</span><span>{new Date(run.created_at).toLocaleString()}</span><span>{run.stage}</span><span>{run.is_replay ? "Recorded " : ""}{run.cost_usd == null ? "cost unavailable" : `$${number(run.cost_usd, 4)}`}</span>{run.is_replay ? <span title={source ?? run.recording_id ?? undefined}>{source ? `Source run ${source.slice(0, 8)}` : `Recording ${run.recording_id ?? "unavailable"}`}</span> : null}{run.is_replay ? <span>{usageLabel(run)}</span> : null}</ItemFooter>
      </Link></Item>;
    })}</ItemGroup> : <Empty className="min-h-64 border border-dashed" aria-live="polite"><EmptyHeader><EmptyTitle role="heading" aria-level={3}>{error ? "Run history could not be loaded." : runs ? "No chip designs yet." : "Checking run history…"}</EmptyTitle><EmptyDescription>{error ? "Check the API connection and reload this page." : "Your real tool runs will appear here."}</EmptyDescription></EmptyHeader><EmptyContent><Button asChild variant="outline"><Link href="/">Start a new design <ArrowRight data-icon="inline-end" /></Link></Button></EmptyContent></Empty>}
  </section>;
}
