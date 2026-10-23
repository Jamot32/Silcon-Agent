"use client";

import dynamic from "next/dynamic";
import { Check, Minus, X } from "lucide-react";
import type { Metric, TestResults } from "@/lib/api";
import { bestMeasured, number } from "./format";

const MetricsChart = dynamic(() => import("./metrics-chart"), { ssr: false, loading: () => <div className="metrics-chart"><p className="panel-empty">Loading chart…</p></div> });

export function Signoff({ value }: { value: boolean | null | undefined }) {
  return <span className={value === true ? "signoff pass-text" : value === false ? "signoff fail-text" : "signoff muted"}>{value === true ? <Check aria-hidden="true" /> : value === false ? <X aria-hidden="true" /> : <Minus aria-hidden="true" />}{value === true ? "clean" : value === false ? "failed" : "unknown"}</span>;
}

export function RunInspection({ tests, metrics, bestTag, targetClock, isReplay = false, finished = false }: { tests: TestResults | null; metrics: Metric[]; bestTag: string | null; targetClock?: number | null; isReplay?: boolean; finished?: boolean }) {
  const best = bestMeasured(metrics, bestTag, targetClock);
  const countsKnown = tests && typeof tests.passed === "number" && typeof tests.failed === "number";
  const testCount = countsKnown ? tests.passed! + tests.failed! + (tests.skipped ?? 0) : 0;
  return <section className="instrument-panel inspection-panel" aria-labelledby="verification-title">
    <header className="instrument-header"><h2 id="verification-title">Verification and Metrics</h2></header>
    <section className="test-section" data-testid="test-results" data-last-test-event-id={tests?.event_id ?? 0} data-test-count={testCount} aria-labelledby="test-title">
      <div className="section-label"><h3 id="test-title">Tests</h3><span className={tests?.ok === true ? "pass-text" : tests?.ok === false ? "fail-text" : "muted"}>{countsKnown ? `${tests.passed} / ${testCount} passed` : tests ? "Execution failed" : finished ? "No results" : "Waiting"}</span></div>
      {tests ? <>
        {tests.cases?.length ? <ul className="test-list">{tests.cases.map((test, index) => <li key={`${test.test}-${index}`}><span className={test.ok === true ? "test-dot pass" : test.ok === false ? "test-dot fail" : "test-dot"} aria-label={test.ok === true ? "Passed" : test.ok === false ? "Failed" : "Skipped"}>{test.ok === true ? <Check /> : test.ok === false ? <X /> : <Minus />}</span><span title={test.message}>{test.test}</span></li>)}</ul> : <div className="test-aggregate"><p>{countsKnown ? `${tests.passed} passed · ${tests.failed} failed${tests.skipped ? ` · ${tests.skipped} skipped` : ""}` : tests.error ?? tests.first_error ?? "No test counts were returned."}</p>{countsKnown ? <span>Actual simulator totals. Per-test names were not recorded.</span> : null}</div>}
        {tests.failures?.length ? <ul className="test-failures">{tests.failures.map((failure, index) => <li key={`${failure.test}-${index}`}><strong>{failure.test}</strong><p>{failure.message}</p></li>)}</ul> : null}
      </> : <p className="muted section-waiting">{finished ? "No simulator results were recorded before this run ended." : isReplay ? "Recorded simulator results appear during playback." : "The agent will verify reset, normal operation, and edge cases."}</p>}
    </section>
    <section className="chart-section" aria-labelledby="chart-title"><div className="section-label chart-heading"><h3 id="chart-title">Area and WNS <span>(post-layout)</span></h3><div className="chart-legend"><span><i className="area-dot" />Area (µm²)</span><span><i className="slack-dot" />WNS (ns)</span></div></div><MetricsChart metrics={metrics} finished={finished} /></section>
    <section className="best-section" aria-label="Best measured physical run"><h3>{bestTag ? "Best run" : "Best measured"}{best ? <span title={best.run_tag}> ({best.run_tag})</span> : null}</h3>
      {best ? <div className="metric-table-scroll"><table className="metric-table"><thead><tr><th>Target clock</th><th>Area (µm²)</th><th>WNS (ns)</th><th>DRC</th><th>LVS</th></tr></thead><tbody><tr><td>{number(best.clock_mhz)} MHz</td><td>{number(best.area_um2)}</td><td>{number(best.wns_ns, 3)}</td><td><Signoff value={best.drc_ok} /></td><td><Signoff value={best.lvs_ok} /></td></tr></tbody></table></div> : <p className="muted section-waiting">{finished ? "No completed physical runs were recorded." : "No completed physical runs yet."}</p>}
    </section>
  </section>;
}
