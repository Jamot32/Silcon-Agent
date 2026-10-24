"use client";

import { useEffect, useState } from "react";
import { CHECKS, STATUSES, TIERS, fetchReliability, histogram, money, peers, percent, ReliabilityApiError, seconds, shortHash, type Cohort, type ReliabilityResponse, type Tier, type TierReport } from "../lib/reliability";
import styles from "./reliability-dashboard.module.css";

type State = { kind: "loading" } | { kind: "not-found" } | { kind: "error" } | { kind: "ready"; data: ReliabilityResponse };
const TIER_NAMES: Record<Tier, string> = { "1": "Tier 1", "2": "Tier 2", "3": "Tier 3", "4": "Tier 4" };
const FUNNEL_LABELS: Record<string, string> = { planned_hardware: "Hardware trials", rtl_generated: "RTL produced", lint: "Lint", self_tests: "Own tests", synthesis: "Synthesis", flow: "Physical flow", drc: "DRC", lvs: "LVS", package: "Package", bound_hidden_pass: "Bound hidden pass" };
const CHECK_LABELS: Record<string, string> = { ...FUNNEL_LABELS, hidden: "Hidden checks" };

function Range({ tier }: { tier: TierReport }) {
  const min = tier.repeat_success_rates.min, max = tier.repeat_success_rates.max;
  if (min === null || max === null) return <span className={styles.subtle}>Repeat range unavailable</span>;
  return <>
    <svg className={styles.range} viewBox="0 0 104 18" role="img" aria-label={`Observed repeat range ${percent(min)} to ${percent(max)}. Pooled success ${percent(tier.success_rate)}.`}>
      <line x1="2" x2="102" y1="9" y2="9" className={styles.rangeTrack} />
      <line x1={2 + min * 100} x2={2 + max * 100} y1="9" y2="9" className={styles.rangeSpan} />
      <line x1={2 + min * 100} x2={2 + min * 100} y1="5" y2="13" className={styles.rangeSpan} />
      <line x1={2 + max * 100} x2={2 + max * 100} y1="5" y2="13" className={styles.rangeSpan} />
      <circle cx={2 + tier.success_rate * 100} cy="9" r="2" className={styles.rangePoint} />
    </svg>
    <p className={styles.subtle}>{percent(min)}–{percent(max)} across {tier.repeat_success_rates.count} repeats</p>
  </>;
}

function TierCard({ id, report }: { id: Tier; report?: TierReport }) {
  return <section className={styles.tierCard} aria-labelledby={`tier-${id}`}>
    <h3 id={`tier-${id}`}>{TIER_NAMES[id]}</h3>
    {report ? <><div className={styles.rate}>{percent(report.success_rate)}</div><p>{report.successful}/{report.planned} successful · {report.cases} cases</p><Range tier={report} /></> : <p className={styles.subtle}>Not included in this cohort</p>}
  </section>;
}

function Funnel({ cohort }: { cohort: Cohort }) {
  const funnel = cohort.report.hardware_survival_funnel, total = funnel[0].count;
  return <section className={styles.panel} aria-labelledby="funnel-title">
    <div className={styles.panelHeading}><h2 id="funnel-title">Hardware survival</h2><span className={styles.micro}>CUMULATIVE · {total} TRIALS</span></div>
    <p className={styles.explanation}>Each row includes trials surviving every preceding row. T4 scope cases are excluded.</p>
    <ol className={styles.funnel}>{funnel.map((row) => <li key={row.check}>
      <span>{FUNNEL_LABELS[row.check]}</span><div className={styles.barTrack} aria-hidden="true"><i style={{ width: `${total ? row.count / total * 100 : 0}%` }} /></div><strong>{row.count}<small>/{total}</small></strong>
    </li>)}</ol>
    {total === 0 ? <p className={styles.subtle}>No hardware trials were included.</p> : null}
    <details className={styles.details}><summary>Independent stage checks · all {cohort.report.planned} trials</summary>
      <p className={styles.explanation}>These counts describe each stage independently across all tiers. The survival rows above use cumulative hardware checks.</p>
      <div className={styles.tableScroll}><table><caption className={styles.srOnly}>Independent check statuses for all trials</caption><thead><tr><th scope="col">Check</th>{STATUSES.map((status) => <th scope="col" key={status}>{status.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{CHECKS.map((check) => <tr key={check}><th scope="row">{CHECK_LABELS[check]}</th>{STATUSES.map((status) => <td key={status}>{cohort.report.independent_stage_checks[check][status]}</td>)}</tr>)}</tbody></table></div>
    </details>
  </section>;
}

function Failures({ data, cohort }: { data: ReliabilityResponse; cohort: Cohort }) {
  const rows = data.top_original_failure_classes[cohort.cohort_id];
  return <section className={styles.panel} aria-labelledby="failures-title">
    <div className={styles.panelHeading}><h2 id="failures-title">Original failure classes</h2><span className={styles.micro}>ALL TIERS</span></div>
    <p className={styles.explanation}>Published taxonomy, up to ten classes. Counts use the complete cohort.</p>
    {rows.length ? <ol className={styles.failures}>{rows.map((row) => <li key={row.class}><div><code>{row.class}</code><span>{row.count}/{cohort.report.planned} trials</span></div><div className={styles.failureTrack} aria-hidden="true"><i style={{ width: `${row.count / cohort.report.planned * 100}%` }} /></div></li>)}</ol> : <p className={styles.inlineEmpty}>No original failure classes were published.</p>}
  </section>;
}

function Distribution({ title, values, unknown, unit, statistic }: { title: string; values: (number | null)[]; unknown?: number; unit: "seconds" | "USD"; statistic: number | null }) {
  const distribution = histogram(values), unknownCount = unknown ?? distribution.unknown;
  const maxCount = Math.max(1, ...distribution.bins.map((bin) => bin.count));
  const format = unit === "USD" ? money : seconds;
  return <section className={styles.panel} aria-label={title}>
    <div className={styles.panelHeading}><h2>{title}</h2><span className={styles.micro}>{unit.toUpperCase()}</span></div>
    <p className={styles.distributionMeta}>Median <strong>{format(statistic)}</strong><span>{distribution.known} known · {unknownCount} unknown</span></p>
    {distribution.bins.length ? <ol className={styles.histogram} aria-label={`Observed ${unit} histogram`}>{distribution.bins.map((bin, index) => <li key={index}>
      <span title={bin.from === bin.to ? `${bin.from} ${unit}` : `${bin.from} to ${bin.to} ${unit}; upper bound ${index === distribution.bins.length - 1 ? "inclusive" : "exclusive"}`}>{format(bin.from)}{bin.from === bin.to ? "" : `–${format(bin.to)}`}</span>
      <div className={styles.barTrack} aria-hidden="true"><i style={{ width: `${bin.count / maxCount * 100}%` }} /></div><strong>{bin.count}</strong>
    </li>)}</ol> : <div className={styles.inlineEmpty}>No known {unit === "USD" ? "USD measurements" : "pipeline durations"} were published.</div>}
    <p className={styles.explanation}>{unit === "USD" ? "The distribution includes known USD values only. Unknown trials keep the cohort total unknown." : "Observed trial durations in seconds. Unknown durations are excluded from the bars."}</p>
  </section>;
}

function Comparison({ data, selected }: { data: ReliabilityResponse; selected: Cohort }) {
  const comparable = peers(data, selected);
  return <section className={styles.panel} aria-labelledby="comparison-title">
    <div className={styles.panelHeading}><h2 id="comparison-title">Within-group comparison</h2><span className={styles.micro}>GROUP {shortHash(selected.report.comparison_group_sha256)}</span></div>
    <p className={styles.explanation}>These cohorts share the published comparison conditions. Pipeline versions may vary. Rates and repeat ranges are descriptive.</p>
    {comparable.length > 1 ? <div className={styles.tableScroll}><table className={styles.comparisonTable}><caption className={styles.srOnly}>Tier success rates and observed repeat ranges within one matching comparison group</caption><thead><tr><th scope="col">Cohort / pipeline</th>{TIERS.map((tier) => <th scope="col" key={tier}>T{tier}</th>)}</tr></thead><tbody>{comparable.map((cohort) => <tr key={cohort.cohort_id} className={cohort.cohort_id === selected.cohort_id ? styles.selectedRow : undefined}><th scope="row"><code>{cohort.cohort_id}</code>{cohort.cohort_id === selected.cohort_id ? <span className={styles.selectedLabel}>Selected</span> : null}<small title={cohort.report.pipeline_sha256}>{shortHash(cohort.report.pipeline_sha256)}</small></th>{TIERS.map((tier) => { const value = cohort.report.tiers[tier]; return <td key={tier}>{value ? <><strong>{percent(value.success_rate)}</strong><small>{value.successful}/{value.planned} · {value.repeat_success_rates.min === null || value.repeat_success_rates.max === null ? "Range unknown" : `${percent(value.repeat_success_rates.min)}–${percent(value.repeat_success_rates.max)}`}</small></> : <span title="Tier not included">—</span>}</td>; })}</tr>)}</tbody></table></div> : <p className={styles.inlineEmpty}>One cohort is published in this comparison group. A comparison series is not available yet.</p>}
    <p className={styles.explanation}>Cohorts are ordered by identifier. Other comparison groups are available through the cohort selector.</p>
  </section>;
}

function Provenance({ cohort }: { cohort: Cohort }) {
  const r = cohort.report, c = r.comparison_conditions;
  const fields = [
    ["Pipeline", r.pipeline_sha256], ["Comparison group", r.comparison_group_sha256],
    ["Summary", cohort.binding.summary_sha256], ["Seal", cohort.binding.seal_sha256],
    ["Verifier output", cohort.binding.verification_stdout_sha256], ["Sealer", cohort.binding.sealer],
    ["Sealer source", cohort.binding.sealer_sha256], ["Base sealer source", cohort.binding.base_sealer_sha256],
    ["Corpus identity", c.corpus_sha256], ["Grader identity", c.grader_sha256], ["Plan identity", c.plan_sha256],
    ["EDA image", c.tool_versions.eda_image], ["Image identity", c.tool_versions.eda_image_id], ["PDK revision", c.tool_versions.pdk_revision],
    ["Provider / model", `${c.provider} / ${c.model}`], ["CLI", c.cli_version ?? "Unknown"],
    ["Host versions", `Python ${c.tool_versions.python} · OpenAI ${c.tool_versions.openai} · Pydantic ${c.tool_versions.pydantic} · SQLModel ${c.tool_versions.sqlmodel}`],
    ["Published limits", `${c.config.max_calls} calls · ${c.config.max_tokens ?? "unknown"} tokens · ${money(c.config.max_usd)} budget · ${c.config.time_limit_seconds}s deadline · ${c.config.concurrency} jobs`],
  ];
  return <details className={`${styles.panel} ${styles.provenance}`}><summary>Published identities and conditions</summary><p className={styles.explanation}>Read-only aggregate identities supplied by the validated export loader.</p><dl>{fields.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl></details>;
}

export function ReliabilityView({ data, selectedId, onSelect, onReload }: { data: ReliabilityResponse; selectedId: string; onSelect: (id: string) => void; onReload: () => void }) {
  const sorted = [...data.cohorts].sort((a, b) => b.cohort_id.localeCompare(a.cohort_id));
  const selected = sorted.find((cohort) => cohort.cohort_id === selectedId) ?? sorted[0];
  if (!selected) return <ReliabilityState kind="empty" onRetry={onReload} />;
  const r = selected.report;
  return <div className={styles.page}>
    <header className={styles.heading}><div><span className={styles.eyebrow}>DEV · READ ONLY</span><h1>Reliability.</h1><p>Sealed cohorts and the checks they survived.</p></div><button type="button" className={styles.button} onClick={onReload}>Reload reports</button></header>
    <div className={styles.selection}><div><label htmlFor="reliability-cohort">Published cohort</label><select id="reliability-cohort" value={selected.cohort_id} onChange={(event) => onSelect(event.target.value)}>{sorted.map((cohort) => <option key={cohort.cohort_id} value={cohort.cohort_id}>{cohort.cohort_id} · {shortHash(cohort.report.pipeline_sha256)}</option>)}</select></div><p><strong>{r.planned} trials</strong><span>{r.repeats} repeats · {r.comparison_conditions.provider} / {r.comparison_conditions.model}</span></p><span className={styles.sealed}>Complete DEV export</span></div>
    <section className={styles.summary} aria-label="Selected cohort summary">
      <div><span>Overall success · all tiers</span><strong>{percent(r.success_rate)}</strong><small>{r.successful}/{r.planned} successful trials</small></div>
      <div><span>Median pipeline time</span><strong>{seconds(r.pipeline_time_seconds.median)}</strong><small>{r.pipeline_time_seconds.count}/{r.planned} durations known</small></div>
      <div><span>Total USD</span><strong className={r.cost.total_usd === null ? styles.unknown : undefined}>{money(r.cost.total_usd)}</strong><small>{r.cost.unknown_attempted_trials}/{r.planned} trials unpriced</small>{r.cost.known_trials ? <small>Known subset {money(r.cost.known_subset.total_usd)} · {r.cost.known_trials} trials</small> : null}</div>
    </section>
    <div className={styles.tierIntro}><h2>Tier outcomes</h2><p>Observed repeat min–max; these are empirical ranges.</p></div><div className={styles.tiers}>{TIERS.map((tier) => <TierCard key={tier} id={tier} report={r.tiers[tier]} />)}</div>
    <div className={styles.grid}><Funnel cohort={selected} /><Failures data={data} cohort={selected} /></div>
    <div className={styles.grid}><Distribution title="Pipeline time distribution" values={r.time_distribution_seconds} unit="seconds" statistic={r.pipeline_time_seconds.median} /><Distribution title="Known cost distribution" values={r.known_cost_distribution_usd} unknown={r.unknown_cost_trials} unit="USD" statistic={r.cost.known_subset.median} /></div>
    <Comparison data={data} selected={selected} /><Provenance cohort={selected} />
  </div>;
}

export function ReliabilityState({ kind, onRetry }: { kind: "loading" | "empty" | "error" | "not-found"; onRetry?: () => void }) {
  const copy = { loading: ["Loading reliability reports…", "Reading published DEV aggregates."], empty: ["No sealed DEV cohorts published.", "The enabled aggregate loader has no published reports yet."], error: ["Reliability reports are unavailable.", "The public export could not be loaded or validated. No cohort data is shown."], "not-found": ["Reliability view not found.", "This development view is unavailable."] }[kind];
  return <section className={styles.page} aria-busy={kind === "loading"}>
    <div className={styles.heading}><div><span className={styles.eyebrow}>DEV · READ ONLY</span><h1>Reliability.</h1></div></div>
    <div className={styles.state} role={kind === "error" ? "alert" : "status"}><h2>{copy[0]}</h2><p>{copy[1]}</p>{kind === "loading" ? <div className={styles.skeleton} aria-hidden="true" /> : kind === "not-found" ? <a href="/runs" className={styles.button}>Run history</a> : <button type="button" className={styles.button} onClick={onRetry}>Reload reports</button>}</div>
  </section>;
}

export function ReliabilityDashboard() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [selectedId, setSelectedId] = useState("");
  const [request, setRequest] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    void fetchReliability(controller.signal).then((data) => { if (!controller.signal.aborted) setState({ kind: "ready", data }); }).catch((error: unknown) => { if (!controller.signal.aborted) setState({ kind: error instanceof ReliabilityApiError && error.status === 404 ? "not-found" : "error" }); });
    return () => controller.abort();
  }, [request]);
  const reload = () => { setState({ kind: "loading" }); setRequest((value) => value + 1); };
  return state.kind === "ready" ? <ReliabilityView data={state.data} selectedId={selectedId} onSelect={setSelectedId} onReload={reload} /> : <ReliabilityState kind={state.kind} onRetry={reload} />;
}
