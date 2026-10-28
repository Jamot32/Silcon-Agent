"use client";

import { useEffect, useState } from "react";
import { CHECKS, STATUSES, TIERS, fetchReliability, histogram, money, peers, percent, ReliabilityApiError, seconds, shortHash, type Cohort, type ReliabilityResponse, type Tier, type TierReport } from "../lib/reliability";
import { ChevronRight, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

type State = { kind: "loading" } | { kind: "not-found" } | { kind: "error" } | { kind: "ready"; data: ReliabilityResponse };
const TIER_NAMES: Record<Tier, string> = { "1": "Tier 1", "2": "Tier 2", "3": "Tier 3", "4": "Tier 4" };
const FUNNEL_LABELS: Record<string, string> = { planned_hardware: "Hardware trials", rtl_generated: "RTL produced", lint: "Lint", self_tests: "Own tests", synthesis: "Synthesis", flow: "Physical flow", drc: "DRC", lvs: "LVS", package: "Package", bound_hidden_pass: "Bound hidden pass" };
const CHECK_LABELS: Record<string, string> = { ...FUNNEL_LABELS, hidden: "Hidden checks" };

const micro = "font-mono text-[10px] tracking-wider text-muted-foreground";
const explanation = "my-3 text-xs leading-relaxed text-muted-foreground";
const inlineEmpty = "flex min-h-26 items-center justify-center rounded-lg border border-dashed p-5 text-center text-xs leading-relaxed text-muted-foreground";

function Bar({ value, className }: { value: number; className?: string }) {
  return <div className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true"><i className={cn("block h-full rounded-full bg-primary/70", className)} style={{ width: `${value}%` }} /></div>;
}

function Range({ tier }: { tier: TierReport }) {
  const min = tier.repeat_success_rates.min, max = tier.repeat_success_rates.max;
  if (min === null || max === null) return <span className="text-xs text-muted-foreground">Repeat range unavailable</span>;
  return <>
    <svg className="mt-2 h-6 w-full overflow-visible" viewBox="0 0 104 18" role="img" aria-label={`Observed repeat range ${percent(min)} to ${percent(max)}. Pooled success ${percent(tier.success_rate)}.`}>
      <line x1="2" x2="102" y1="9" y2="9" className="stroke-border" strokeWidth={1} />
      <line x1={2 + min * 100} x2={2 + max * 100} y1="9" y2="9" className="stroke-muted-foreground" strokeWidth={1.5} />
      <line x1={2 + min * 100} x2={2 + min * 100} y1="5" y2="13" className="stroke-muted-foreground" strokeWidth={1.5} />
      <line x1={2 + max * 100} x2={2 + max * 100} y1="5" y2="13" className="stroke-muted-foreground" strokeWidth={1.5} />
      <circle cx={2 + tier.success_rate * 100} cy="9" r="2" className="fill-primary" />
    </svg>
    <p className="text-xs text-muted-foreground">{percent(min)}–{percent(max)} across {tier.repeat_success_rates.count} repeats</p>
  </>;
}

function TierCard({ id, report }: { id: Tier; report?: TierReport }) {
  return <Card size="sm" role="region" aria-labelledby={`tier-${id}`} className="min-w-0"><CardContent>
    <h3 id={`tier-${id}`} className="mb-3 text-xs font-medium text-muted-foreground">{TIER_NAMES[id]}</h3>
    {report ? <><div className="text-3xl font-semibold tracking-tight text-primary tabular-nums">{percent(report.success_rate)}</div><p className="mt-1.5 text-xs text-muted-foreground">{report.successful}/{report.planned} successful · {report.cases} cases</p><Range tier={report} /></> : <p className="text-xs text-muted-foreground">Not included in this cohort</p>}
  </CardContent></Card>;
}

function Section({ id, title, label, children, ...props }: { id?: string; title: string; label: string; children: React.ReactNode } & Omit<React.ComponentProps<typeof Card>, "title">) {
  return <Card role="region" aria-labelledby={id} aria-label={id ? undefined : title} className="min-w-0" {...props}><CardContent>
    <div className="flex flex-wrap items-baseline justify-between gap-3"><h2 id={id} className="text-base font-medium">{title}</h2><span className={micro}>{label}</span></div>
    {children}
  </CardContent></Card>;
}

function Funnel({ cohort }: { cohort: Cohort }) {
  const funnel = cohort.report.hardware_survival_funnel, total = funnel[0].count;
  return <Section id="funnel-title" title="Hardware survival" label={`CUMULATIVE · ${total} TRIALS`}>
    <p className={explanation}>Each row includes trials surviving every preceding row. T4 scope cases are excluded.</p>
    <ol>{funnel.map((row, index) => <li key={row.check} className="grid min-h-8 grid-cols-[minmax(100px,130px)_minmax(0,1fr)_56px] items-center gap-3 text-xs">
      <span>{FUNNEL_LABELS[row.check]}</span><Bar value={total ? row.count / total * 100 : 0} className={index === funnel.length - 1 ? "bg-success" : undefined} /><strong className="text-right font-mono font-normal">{row.count}<small className="text-muted-foreground">/{total}</small></strong>
    </li>)}</ol>
    {total === 0 ? <p className="text-xs text-muted-foreground">No hardware trials were included.</p> : null}
    <Collapsible className="mt-5 border-t pt-3"><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="group -ml-2.5 text-muted-foreground"><ChevronRight className="transition-transform group-data-[state=open]:rotate-90" data-icon="inline-start" />Independent stage checks · all {cohort.report.planned} trials</Button></CollapsibleTrigger><CollapsibleContent forceMount className="data-[state=closed]:hidden">
      <p className={explanation}>These counts describe each stage independently across all tiers. The survival rows above use cumulative hardware checks.</p>
      <Table className="text-xs"><TableCaption className="sr-only">Independent check statuses for all trials</TableCaption><TableHeader><TableRow><TableHead scope="col" className="text-muted-foreground">Check</TableHead>{STATUSES.map((status) => <TableHead scope="col" key={status} className="text-muted-foreground">{status.replaceAll("_", " ")}</TableHead>)}</TableRow></TableHeader><TableBody>{CHECKS.map((check) => <TableRow key={check}><TableHead scope="row" className="font-normal">{CHECK_LABELS[check]}</TableHead>{STATUSES.map((status) => <TableCell key={status} className="tabular-nums">{cohort.report.independent_stage_checks[check][status]}</TableCell>)}</TableRow>)}</TableBody></Table>
    </CollapsibleContent></Collapsible>
  </Section>;
}

function Failures({ data, cohort }: { data: ReliabilityResponse; cohort: Cohort }) {
  const rows = data.top_original_failure_classes[cohort.cohort_id];
  return <Section id="failures-title" title="Original failure classes" label="ALL TIERS">
    <p className={explanation}>Published taxonomy, up to ten classes. Counts use the complete cohort.</p>
    {rows.length ? <ol className="flex flex-col gap-5 py-1">{rows.map((row) => <li key={row.class}><div className="mb-2 flex justify-between gap-3 text-xs"><code className="font-mono break-all">{row.class}</code><span className="shrink-0 text-muted-foreground">{row.count}/{cohort.report.planned} trials</span></div><Bar value={row.count / cohort.report.planned * 100} className="bg-destructive/70" /></li>)}</ol> : <p className={inlineEmpty}>No original failure classes were published.</p>}
  </Section>;
}

function Distribution({ title, values, unknown, unit, statistic }: { title: string; values: (number | null)[]; unknown?: number; unit: "seconds" | "USD"; statistic: number | null }) {
  const distribution = histogram(values), unknownCount = unknown ?? distribution.unknown;
  const maxCount = Math.max(1, ...distribution.bins.map((bin) => bin.count));
  const format = unit === "USD" ? money : seconds;
  return <Section title={title} label={unit.toUpperCase()}>
    <p className="my-4 flex flex-wrap gap-2 text-xs text-muted-foreground">Median <strong className="font-medium text-foreground">{format(statistic)}</strong><span className="ml-auto max-sm:ml-0 max-sm:basis-full">{distribution.known} known · {unknownCount} unknown</span></p>
    {distribution.bins.length ? <ol aria-label={`Observed ${unit} histogram`}>{distribution.bins.map((bin, index) => <li key={index} className="grid min-h-8 grid-cols-[minmax(110px,1fr)_minmax(60px,1.4fr)_26px] items-center gap-3 text-[11px]">
      <span title={bin.from === bin.to ? `${bin.from} ${unit}` : `${bin.from} to ${bin.to} ${unit}; upper bound ${index === distribution.bins.length - 1 ? "inclusive" : "exclusive"}`}>{format(bin.from)}{bin.from === bin.to ? "" : `–${format(bin.to)}`}</span>
      <Bar value={bin.count / maxCount * 100} /><strong className="text-right font-mono font-normal">{bin.count}</strong>
    </li>)}</ol> : <div className={inlineEmpty}>No known {unit === "USD" ? "USD measurements" : "pipeline durations"} were published.</div>}
    <p className={explanation}>{unit === "USD" ? "The distribution includes known USD values only. Unknown trials keep the cohort total unknown." : "Observed trial durations in seconds. Unknown durations are excluded from the bars."}</p>
  </Section>;
}

function Comparison({ data, selected }: { data: ReliabilityResponse; selected: Cohort }) {
  const comparable = peers(data, selected);
  return <Section id="comparison-title" title="Within-group comparison" label={`GROUP ${shortHash(selected.report.comparison_group_sha256)}`}>
    <p className={explanation}>These cohorts share the published comparison conditions. Pipeline versions may vary. Rates and repeat ranges are descriptive.</p>
    {comparable.length > 1 ? <Table className="text-xs"><TableCaption className="sr-only">Tier success rates and observed repeat ranges within one matching comparison group</TableCaption><TableHeader><TableRow><TableHead scope="col" className="text-muted-foreground">Cohort / pipeline</TableHead>{TIERS.map((tier) => <TableHead scope="col" key={tier} className="text-muted-foreground">T{tier}</TableHead>)}</TableRow></TableHeader><TableBody>{comparable.map((cohort) => <TableRow key={cohort.cohort_id} data-state={cohort.cohort_id === selected.cohort_id ? "selected" : undefined} className="data-[state=selected]:bg-primary/5"><TableHead scope="row" className="font-normal"><code className="font-mono">{cohort.cohort_id}</code>{cohort.cohort_id === selected.cohort_id ? <Badge variant="outline" className="ml-2 border-primary/40 text-primary">Selected</Badge> : null}<small className="mt-1 block font-mono text-[10px] text-muted-foreground" title={cohort.report.pipeline_sha256}>{shortHash(cohort.report.pipeline_sha256)}</small></TableHead>{TIERS.map((tier) => { const value = cohort.report.tiers[tier]; return <TableCell key={tier}>{value ? <><strong className="text-sm font-medium tabular-nums">{percent(value.success_rate)}</strong><small className="mt-1 block text-[10px] text-muted-foreground">{value.successful}/{value.planned} · {value.repeat_success_rates.min === null || value.repeat_success_rates.max === null ? "Range unknown" : `${percent(value.repeat_success_rates.min)}–${percent(value.repeat_success_rates.max)}`}</small></> : <span title="Tier not included">—</span>}</TableCell>; })}</TableRow>)}</TableBody></Table> : <p className={inlineEmpty}>One cohort is published in this comparison group. A comparison series is not available yet.</p>}
    <p className={explanation}>Cohorts are ordered by identifier. Other comparison groups are available through the cohort selector.</p>
  </Section>;
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
  return <Card><CardContent><Collapsible><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="group -ml-2.5 text-muted-foreground"><ChevronRight className="transition-transform group-data-[state=open]:rotate-90" data-icon="inline-start" />Published identities and conditions</Button></CollapsibleTrigger><CollapsibleContent forceMount className="data-[state=closed]:hidden"><p className={explanation}>Read-only aggregate identities supplied by the validated export loader.</p><dl className="divide-y border-t text-xs leading-relaxed">{fields.map(([name, value]) => <div key={name} className="grid gap-1 py-2.5 sm:grid-cols-[160px_minmax(0,1fr)] sm:gap-5"><dt className="text-muted-foreground">{name}</dt><dd className="font-mono break-all">{value}</dd></div>)}</dl></CollapsibleContent></Collapsible></CardContent></Card>;
}

function Heading({ children, action }: { children?: React.ReactNode; action?: React.ReactNode }) {
  return <header className="flex flex-wrap items-center justify-between gap-4"><div className="space-y-1.5"><span className="font-mono text-[10px] tracking-wider text-primary">DEV · READ ONLY</span><h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Reliability.</h1>{children}</div>{action}</header>;
}

export function ReliabilityView({ data, selectedId, onSelect, onReload }: { data: ReliabilityResponse; selectedId: string; onSelect: (id: string) => void; onReload: () => void }) {
  const sorted = [...data.cohorts].sort((a, b) => b.cohort_id.localeCompare(a.cohort_id));
  const selected = sorted.find((cohort) => cohort.cohort_id === selectedId) ?? sorted[0];
  if (!selected) return <ReliabilityState kind="empty" onRetry={onReload} />;
  const r = selected.report;
  const summary: { label: string; value: string; notes: string[]; unknownValue: boolean }[] = [
    { label: "Overall success · all tiers", value: percent(r.success_rate), notes: [`${r.successful}/${r.planned} successful trials`], unknownValue: false },
    { label: "Median pipeline time", value: seconds(r.pipeline_time_seconds.median), notes: [`${r.pipeline_time_seconds.count}/${r.planned} durations known`], unknownValue: false },
    { label: "Total USD", value: money(r.cost.total_usd), notes: [`${r.cost.unknown_attempted_trials}/${r.planned} trials unpriced`, ...(r.cost.known_trials ? [`Known subset ${money(r.cost.known_subset.total_usd)} · ${r.cost.known_trials} trials`] : [])], unknownValue: r.cost.total_usd === null },
  ];
  return <div className="mx-auto w-full max-w-7xl space-y-5">
    <Heading action={<Button type="button" variant="outline" onClick={onReload}><RefreshCw data-icon="inline-start" />Reload reports</Button>}><p className="text-muted-foreground">Sealed cohorts and the checks they survived.</p></Heading>
    <div className="flex flex-wrap items-end gap-x-7 gap-y-4 border-y py-4"><div className="grid min-w-0 flex-1 basis-80 gap-2 sm:max-w-xl"><Label htmlFor="reliability-cohort" className="text-xs text-muted-foreground">Published cohort</Label><NativeSelect id="reliability-cohort" className="w-full font-mono" value={selected.cohort_id} onChange={(event) => onSelect(event.target.value)}>{sorted.map((cohort) => <NativeSelectOption key={cohort.cohort_id} value={cohort.cohort_id}>{cohort.cohort_id} · {shortHash(cohort.report.pipeline_sha256)}</NativeSelectOption>)}</NativeSelect></div><p className="text-sm"><strong className="font-medium">{r.planned} trials</strong><span className="mt-1 block text-xs text-muted-foreground">{r.repeats} repeats · {r.comparison_conditions.provider} / {r.comparison_conditions.model}</span></p><Badge variant="outline" className="border-primary/40 text-primary sm:ml-auto">Complete DEV export</Badge></div>
    <section className="grid gap-3 sm:grid-cols-3" aria-label="Selected cohort summary">
      {summary.map(({ label, value, notes, unknownValue }) => <Card key={label} size="sm"><CardContent><span className="mb-2 block text-xs text-muted-foreground">{label}</span><strong data-unknown={unknownValue ? "true" : undefined} className={cn("block text-3xl font-semibold tracking-tight tabular-nums", unknownValue && "text-muted-foreground")}>{value}</strong>{notes.map((note) => <small key={note} className="mt-1.5 block text-xs text-muted-foreground">{note}</small>)}</CardContent></Card>)}
    </section>
    <div className="space-y-3"><div className="flex flex-wrap items-baseline gap-x-5 gap-y-1"><h2 className="text-lg font-medium">Tier outcomes</h2><p className="text-xs text-muted-foreground">Observed repeat min–max; these are empirical ranges.</p></div><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{TIERS.map((tier) => <TierCard key={tier} id={tier} report={r.tiers[tier]} />)}</div></div>
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]"><Funnel cohort={selected} /><Failures data={data} cohort={selected} /></div>
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]"><Distribution title="Pipeline time distribution" values={r.time_distribution_seconds} unit="seconds" statistic={r.pipeline_time_seconds.median} /><Distribution title="Known cost distribution" values={r.known_cost_distribution_usd} unknown={r.unknown_cost_trials} unit="USD" statistic={r.cost.known_subset.median} /></div>
    <Comparison data={data} selected={selected} /><Provenance cohort={selected} />
  </div>;
}

export function ReliabilityState({ kind, onRetry }: { kind: "loading" | "empty" | "error" | "not-found"; onRetry?: () => void }) {
  const copy = { loading: ["Loading reliability reports…", "Reading published DEV aggregates."], empty: ["No sealed DEV cohorts published.", "The enabled aggregate loader has no published reports yet."], error: ["Reliability reports are unavailable.", "The public export could not be loaded or validated. No cohort data is shown."], "not-found": ["Reliability view not found.", "This development view is unavailable."] }[kind];
  return <section className="mx-auto w-full max-w-7xl space-y-5" aria-busy={kind === "loading"}>
    <Heading />
    <Empty className="min-h-60 border border-dashed" role={kind === "error" ? "alert" : "status"}><EmptyHeader><EmptyTitle role="heading" aria-level={2} className="text-lg">{copy[0]}</EmptyTitle><EmptyDescription>{copy[1]}</EmptyDescription></EmptyHeader><EmptyContent>{kind === "loading" ? <Skeleton className="h-8 w-full max-w-md" /> : kind === "not-found" ? <Button asChild variant="outline"><a href="/runs">Run history</a></Button> : <Button type="button" variant="outline" onClick={onRetry}><RefreshCw data-icon="inline-start" />Reload reports</Button>}</EmptyContent></Empty>
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
