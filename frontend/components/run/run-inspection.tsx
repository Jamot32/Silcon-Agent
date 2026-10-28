"use client";

import dynamic from "next/dynamic";
import { Check, Minus, X } from "lucide-react";
import type { Metric, TestResults } from "@/lib/api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { signalText } from "./badges";
import { bestMeasured, number } from "./format";
import { Panel, PanelEmpty } from "./panel";

const MetricsChart = dynamic(() => import("./metrics-chart"), { ssr: false, loading: () => <div className="h-[150px]"><PanelEmpty>Loading chart…</PanelEmpty></div> });

export function Signoff({ value }: { value: boolean | null | undefined }) {
  return <span className={cn("inline-flex items-center gap-1 [&_svg]:size-3 [&_svg]:stroke-[2.5]", value === true ? signalText.pass : value === false ? signalText.fail : signalText.neutral)}>{value === true ? <Check aria-hidden="true" /> : value === false ? <X aria-hidden="true" /> : <Minus aria-hidden="true" />}{value === true ? "clean" : value === false ? "failed" : "unknown"}</span>;
}

const dotTone = (ok: boolean | null | undefined) => ok === true ? "bg-success" : ok === false ? "bg-destructive" : "bg-muted-foreground";

export function RunInspection({ tests, metrics, bestTag, targetClock, isReplay = false, finished = false }: { tests: TestResults | null; metrics: Metric[]; bestTag: string | null; targetClock?: number | null; isReplay?: boolean; finished?: boolean }) {
  const best = bestMeasured(metrics, bestTag, targetClock);
  const countsKnown = tests && typeof tests.passed === "number" && typeof tests.failed === "number";
  const testCount = countsKnown ? tests.passed! + tests.failed! + (tests.skipped ?? 0) : 0;
  return <Panel id="verification-title" title="Verification and Metrics" className="flex flex-col lg:col-span-2 xl:col-span-1">
    <section className="max-h-40 min-h-28 shrink-0 overflow-auto px-4 py-3 [scrollbar-width:thin]" data-testid="test-results" data-last-test-event-id={tests?.event_id ?? 0} data-test-count={testCount} aria-labelledby="test-title">
      <div className="mb-2 flex items-center justify-between gap-2 text-xs"><h3 id="test-title" className="text-sm font-medium">Tests</h3><span className={tests?.ok === true ? signalText.pass : tests?.ok === false ? signalText.fail : signalText.neutral}>{countsKnown ? `${tests.passed} / ${testCount} passed` : tests ? "Execution failed" : finished ? "No results" : "Waiting"}</span></div>
      {tests ? <>
        {tests.cases?.length ? <ul className="space-y-1.5">{tests.cases.map((test, index) => <li key={`${test.test}-${index}`} className="flex min-w-0 items-start gap-2 font-mono text-[11px] leading-snug break-words text-muted-foreground"><span className={cn("mt-px grid size-3.5 shrink-0 place-items-center rounded-full text-background [&_svg]:size-2.5 [&_svg]:stroke-[2.6]", dotTone(test.ok))} aria-label={test.ok === true ? "Passed" : test.ok === false ? "Failed" : "Skipped"}>{test.ok === true ? <Check /> : test.ok === false ? <X /> : <Minus />}</span><span title={test.message}>{test.test}</span></li>)}</ul> : <div className="space-y-1.5 py-1"><p className="text-sm">{countsKnown ? `${tests.passed} passed · ${tests.failed} failed${tests.skipped ? ` · ${tests.skipped} skipped` : ""}` : tests.error ?? tests.first_error ?? "No test counts were returned."}</p>{countsKnown ? <p className="text-xs text-muted-foreground">Actual simulator totals. Per-test names were not recorded.</p> : null}</div>}
        {tests.failures?.length ? <ul className="mt-3 space-y-2 text-xs text-destructive">{tests.failures.map((failure, index) => <li key={`${failure.test}-${index}`}><strong className="font-medium">{failure.test}</strong><p className="mt-1 break-words whitespace-pre-wrap">{failure.message}</p></li>)}</ul> : null}
      </> : <p className="text-xs leading-relaxed text-muted-foreground">{finished ? "No simulator results were recorded before this run ended." : isReplay ? "Recorded simulator results appear during playback." : "The agent will verify reset, normal operation, and edge cases."}</p>}
    </section>
    <section className="flex flex-1 flex-col border-t px-4 pt-3" aria-labelledby="chart-title"><div className="flex flex-wrap items-center justify-between gap-2"><h3 id="chart-title" className="text-sm font-medium">Area and WNS <span className="text-xs font-normal text-muted-foreground">(post-layout)</span></h3><div className="flex items-center gap-3 text-[10px] text-muted-foreground"><span className="inline-flex items-center gap-1.5"><i className="size-2 rounded-full bg-chart-1" />Area (µm²)</span><span className="inline-flex items-center gap-1.5"><i className="size-2 rounded-full bg-chart-2" />WNS (ns)</span></div></div><MetricsChart metrics={metrics} finished={finished} /></section>
    <section className="border-t px-4 py-3" aria-label="Best measured physical run"><h3 className="mb-2 truncate text-sm font-medium">{bestTag ? "Best run" : "Best measured"}{best ? <span className="text-xs font-normal text-muted-foreground" title={best.run_tag}> ({best.run_tag})</span> : null}</h3>
      {best ? <Table className="text-xs"><TableHeader><TableRow><TableHead className="h-8 text-muted-foreground">Target clock</TableHead><TableHead className="h-8 text-muted-foreground">Area (µm²)</TableHead><TableHead className="h-8 text-muted-foreground">WNS (ns)</TableHead><TableHead className="h-8 text-muted-foreground">DRC</TableHead><TableHead className="h-8 text-muted-foreground">LVS</TableHead></TableRow></TableHeader><TableBody><TableRow className="hover:bg-transparent"><TableCell>{number(best.clock_mhz)} MHz</TableCell><TableCell className="tabular-nums">{number(best.area_um2)}</TableCell><TableCell className="tabular-nums">{number(best.wns_ns, 3)}</TableCell><TableCell><Signoff value={best.drc_ok} /></TableCell><TableCell><Signoff value={best.lvs_ok} /></TableCell></TableRow></TableBody></Table> : <p className="text-xs text-muted-foreground">{finished ? "No completed physical runs were recorded." : "No completed physical runs yet."}</p>}
    </section>
  </Panel>;
}
