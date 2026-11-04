"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getRun, getRunMetrics, type Metric, type PublicRun, type Targets } from "@/lib/api";
import { finiteMeasurement, measurementDelta, selectedResult } from "@/lib/revision-comparison";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { number } from "./format";
import { Signoff } from "./run-inspection";

type ParentState = { id: string; run: PublicRun; metrics: Metric[]; error?: never } | { id: string; error: string; run?: never; metrics?: never };
const rows = [
  { field: "clock_mhz", label: "Clock", unit: "MHz", digits: 3 },
  { field: "wns_ns", label: "WNS", unit: "ns", digits: 3 },
  { field: "area_um2", label: "Area", unit: "µm²", digits: 3 },
] as const;
type Field = typeof rows[number]["field"];
const signed = (value: number, digits = 3) => `${value > 0 ? "+" : ""}${number(value, digits)}`;
const targetsFor = (run: PublicRun): Targets => ({ ...run.design_spec?.targets, ...run.targets });

function targetLabel(field: Field, metric: Metric | undefined, targets: Targets) {
  const value = metric?.[field];
  const target = field === "clock_mhz" ? targets.clock_mhz : field === "area_um2" ? targets.max_area_um2 : 0;
  if (target == null) return "No target";
  const unit = field === "clock_mhz" ? "MHz" : field === "area_um2" ? "µm²" : "ns";
  const known = finiteMeasurement(value) && (field !== "clock_mhz" || finiteMeasurement(metric?.wns_ns));
  const met = known && (field === "area_um2" ? value <= target : value >= target && (field !== "clock_mhz" || metric!.wns_ns >= 0));
  return `Target ${field === "area_um2" ? "≤" : "≥"} ${number(target)} ${unit} · ${known ? met ? "Met" : "Missed" : "Unknown"}`;
}

export function RevisionComparison({ run, metrics }: { run: PublicRun; metrics: Metric[] }) {
  const parentId = run.parent_run_id;
  const [state, setState] = useState<ParentState | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!parentId) return;
    const controller = new AbortController();
    setState(null);
    Promise.all([getRun(parentId, controller.signal), getRunMetrics(parentId, controller.signal)])
      .then(([parent, parentMetrics]) => { if (!controller.signal.aborted) setState({ id: parentId, run: parent, metrics: parentMetrics }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setState({ id: parentId, error: error instanceof Error ? error.message : "Could not load the parent result." }); });
    return () => controller.abort();
  }, [parentId, attempt]);
  if (!parentId) return null;
  const loaded = state?.id === parentId ? state : null;
  const parent = loaded?.run;
  const parentSelection = parent ? selectedResult(parent, loaded.metrics!) : null;
  const revisionSelection = selectedResult(run, metrics);
  const before = parentSelection?.metric, after = revisionSelection.metric;
  return <Card role="region" aria-labelledby="revision-comparison-title" className="min-w-0" data-testid="revision-comparison">
    <CardHeader className="gap-2"><CardTitle id="revision-comparison-title" role="heading" aria-level={2}>Compared with parent</CardTitle><p className="text-sm text-muted-foreground"><Link className="underline underline-offset-4" href={`/runs/${parentId}/result`}>Parent run {parentId.slice(0, 8)}</Link>{parent ? ` · ${parent.status}` : ""}. Change = revision − parent.</p></CardHeader>
    <CardContent className="min-w-0 space-y-4">
      {!loaded ? <p role="status" className="text-sm text-muted-foreground">Loading the parent’s selected result…</p> : loaded.error ? <div role="alert" className="space-y-2"><p className="text-sm">Parent comparison unavailable: {loaded.error}</p><Button variant="outline" size="sm" onClick={() => setAttempt((value) => value + 1)}>Retry comparison</Button></div> : parent ? <>
        {parentSelection?.unavailable ? <p className="text-sm text-muted-foreground" data-testid="parent-result-unavailable">Parent: {parentSelection.unavailable}</p> : <p className="break-all text-xs text-muted-foreground">Parent selected flow: {parent.best_run_tag}</p>}
        {revisionSelection.unavailable ? <p className="text-sm text-muted-foreground" data-testid="revision-result-unavailable">Revision: {revisionSelection.unavailable}</p> : <p className="break-all text-xs text-muted-foreground">Revision selected flow: {run.best_run_tag}</p>}
        <Table className="table-fixed text-xs sm:text-sm" data-testid="revision-comparison-table"><TableHeader><TableRow><TableHead className="w-[20%] whitespace-normal">Metric</TableHead><TableHead className="w-[27%] whitespace-normal">Parent</TableHead><TableHead className="w-[27%] whitespace-normal">Revision</TableHead><TableHead className="w-[26%] whitespace-normal">Change</TableHead></TableRow></TableHeader><TableBody>
          {rows.map(({ field, label, unit, digits }) => {
            const delta = measurementDelta(before?.[field], after?.[field]);
            return <TableRow key={field}><TableHead scope="row" className="whitespace-normal" title={field === "clock_mhz" ? "Configured physical-flow clock frequency" : undefined}>{label}</TableHead>{[{ metric: before, result: parent }, { metric: after, result: run }].map(({ metric, result }, index) => {
              return <TableCell key={index} className="whitespace-normal tabular-nums"><span>{finiteMeasurement(metric?.[field]) ? <>{number(metric[field], digits)}<span className="block sm:inline"> {unit}</span></> : "No data"}</span><span className="mt-1 block text-xs text-muted-foreground">{targetLabel(field, metric, targetsFor(result))}</span></TableCell>;
            })}<TableCell className="whitespace-normal tabular-nums" data-testid={`revision-delta-${field}`}>{delta ? <>{signed(delta.absolute, digits)}<span className="block sm:inline"> {unit}</span>{field !== "wns_ns" && delta.percent !== null ? <span className="block text-xs text-muted-foreground">{signed(delta.percent, 2)}%</span> : null}</> : "No data"}</TableCell></TableRow>;
          })}
          <TableRow><TableHead scope="row" className="whitespace-normal">DRC / LVS</TableHead>{[before, after].map((metric, index) => <TableCell key={index} className="whitespace-normal"><span className="flex flex-wrap items-center gap-x-2 gap-y-1"><Signoff value={metric?.drc_ok} /><span aria-hidden="true">/</span><Signoff value={metric?.lvs_ok} /></span></TableCell>)}<TableCell>—</TableCell></TableRow>
        </TableBody></Table>
        <p className="text-xs leading-relaxed text-muted-foreground">Each result uses its own targets. Clock is the configured flow frequency; nonnegative WNS confirms timing at that frequency.</p>
      </> : null}
    </CardContent>
  </Card>;
}
