"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { getRun, getRunMetrics, listRuns, type PublicRun } from "@/lib/api";
import { getFlowDetail, type FlowConfig, type FlowDetail } from "@/lib/flow-inspection";
import { getFlowSources, workspaceFlows, type FlowSources, type WorkspaceFlow } from "@/lib/workspace";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { number, runName } from "./format";

const Diff = dynamic(() => import("./workspace-monaco").then((module) => module.WorkspaceDiff), { ssr: false });
type Evidence = { sources: FlowSources | null; detail: FlowDetail | null; sourceError: string; detailError: string; loading: boolean };

function useComparisonSide(id: string, currentRun: PublicRun, currentOptions: WorkspaceFlow[]) {
  const [other, setOther] = useState<{ id: string; options: WorkspaceFlow[]; error: string } | null>(null);
  const [chosen, setChosen] = useState<{ id: string; key: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (id === currentRun.id) return;
    const controller = new AbortController();
    setOther(null);
    Promise.all([getRun(id, controller.signal), getRunMetrics(id, controller.signal)]).then(([run, metrics]) => {
      if (!controller.signal.aborted) setOther({ id, options: workspaceFlows(run, [], metrics), error: "" });
    }, (reason) => { if (!controller.signal.aborted) setOther({ id, options: [], error: reason instanceof Error ? reason.message : "Run could not be loaded." }); });
    return () => controller.abort();
  }, [id, currentRun.id, attempt]);
  const options = id === currentRun.id ? currentOptions : other?.id === id ? other.options : [];
  return { options, selected: chosen?.id === id ? chosen.key : "", select: (key: string) => setChosen({ id, key }), error: other?.id === id ? other.error : "", loading: id !== currentRun.id && other?.id !== id, retry: () => setAttempt((value) => value + 1) };
}
function useEvidence(runId: string, option: WorkspaceFlow | undefined) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<Evidence>({ sources: null, detail: null, sourceError: "", detailError: "", loading: false });
  const eventId = option && "eventId" in option.selector ? option.selector.eventId : null;
  const tag = option && "runTag" in option.selector ? option.selector.runTag : null;
  useEffect(() => {
    const controller = new AbortController();
    if (eventId === null && tag === null) { setState({ sources: null, detail: null, sourceError: "", detailError: "", loading: false }); return; }
    const selector = eventId !== null ? { eventId } : { runTag: tag! };
    setState({ sources: null, detail: null, sourceError: "", detailError: "", loading: true });
    Promise.allSettled([getFlowSources(runId, selector, controller.signal), getFlowDetail(runId, selector, controller.signal)]).then(([source, detail]) => {
      if (controller.signal.aborted) return;
      setState({ sources: source.status === "fulfilled" ? source.value : null, detail: detail.status === "fulfilled" ? detail.value : null,
        sourceError: source.status === "rejected" ? String(source.reason?.message ?? "Source evidence unavailable.") : "", detailError: detail.status === "rejected" ? String(detail.reason?.message ?? "Flow evidence unavailable.") : "", loading: false });
    });
    return () => controller.abort();
  }, [runId, eventId, tag, attempt]);
  return { ...state, retry: () => setAttempt((value) => value + 1) };
}

function EvidenceNotice({ label, evidence }: { label: string; evidence: Evidence }) {
  return <div className="flex flex-col gap-1 text-xs text-muted-foreground" aria-label={`${label} provenance`}>
    {evidence.loading ? <p role="status">Loading {label.toLowerCase()} evidence…</p> : <>
      <p>{label} source: {evidence.sources?.available ? evidence.sources.provenance === "selected_bundle" ? "verified selected bundle" : "frozen flow snapshot" : "unavailable"}.</p>
      {evidence.sources?.reason || evidence.sourceError ? <p className="wrap-anywhere">{evidence.sources?.reason || evidence.sourceError}</p> : null}
      {evidence.detailError ? <p className="wrap-anywhere">{evidence.detailError}</p> : null}
      {evidence.detail?.provenance.evidence_status === "invalid" ? <p className="text-destructive">Recorded flow evidence failed integrity verification. Its configuration and measurements are not used for comparison.</p> : null}
    </>}
  </div>;
}

const metricRows = [
  ["clock_mhz", "Configured clock", "MHz", 3], ["area_um2", "Cell area", "µm²", 3], ["wns_ns", "Setup WNS", "ns", 3],
  ["tns_ns", "TNS", "ns", 3], ["power_mw", "Reported power", "mW", 6], ["cell_count", "Cells", "", 0],
] as const;
const configs = [["requested_config", "Requested overrides"], ["planned_config", "Planned settings"], ["applied_config", "Applied configuration"], ["resolved_config", "Resolved configuration"]] as const;
const display = (value: unknown) => value === null || value === undefined ? "Unavailable" : Array.isArray(value) ? value.join(" × ") : String(value);

export function WorkspaceCompare({ run, options, initialFlow }: { run: PublicRun; options: WorkspaceFlow[]; initialFlow?: string }) {
  const [runs, setRuns] = useState<PublicRun[]>([run]);
  const [listError, setListError] = useState("");
  const [baselineRun, setBaselineRun] = useState(run.parent_run_id ?? run.id);
  const [candidateRun, setCandidateRun] = useState(run.id);
  const baseline = useComparisonSide(baselineRun, run, options), candidate = useComparisonSide(candidateRun, run, options);
  const left = baseline.options.find((option) => option.key === baseline.selected) ?? baseline.options.find((option) => option.selected) ?? baseline.options[0];
  const right = candidate.options.find((option) => option.key === candidate.selected)
    ?? candidate.options.find((option) => option.tag === initialFlow)
    ?? (baselineRun === candidateRun ? candidate.options.find((option) => option.key !== left?.key) : candidate.options.find((option) => option.selected))
    ?? candidate.options[0];
  const before = useEvidence(baselineRun, left), after = useEvidence(candidateRun, right);
  const [file, setFile] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    listRuns(controller.signal).then((value) => { if (!controller.signal.aborted) setRuns(value); }, (reason) => { if (!controller.signal.aborted) setListError(reason instanceof Error ? reason.message : "Saved runs could not be loaded."); });
    return () => controller.abort();
  }, []);
  const choices = runs.some((item) => item.id === run.id) ? runs : [run, ...runs];
  const beforeFiles = before.sources?.available ? before.sources.files : {}, afterFiles = after.sources?.available ? after.sources.files : {};
  const paths = Array.from(new Set([...Object.keys(beforeFiles), ...Object.keys(afterFiles)])).sort();
  const selectedFile = paths.includes(file) ? file : paths[0] ?? "";
  const sourceReady = !!before.sources?.available && !!after.sources?.available;
  const beforeMetrics = before.detail?.provenance.evidence_status === "invalid" ? null : before.detail?.metrics;
  const afterMetrics = after.detail?.provenance.evidence_status === "invalid" ? null : after.detail?.metrics;
  return <div className="flex min-w-0 flex-col gap-4" data-testid="workspace-comparison">
    <p className="text-sm text-muted-foreground">Compare exact recorded flows across this design or saved runs. Manual builds create linked runs; the parent’s selected flow is the starting baseline.</p>
    {listError ? <Alert><AlertDescription>{listError} The current run remains available.</AlertDescription></Alert> : null}
    <div className="grid min-w-0 gap-4 md:grid-cols-2">{[
      { label: "Baseline", id: baselineRun, set: setBaselineRun, side: baseline, flow: left, evidence: before },
      { label: "Candidate", id: candidateRun, set: setCandidateRun, side: candidate, flow: right, evidence: after },
    ].map(({ label, id, set, side, flow, evidence }) => <Card key={label} className="min-w-0">
      <CardHeader><CardTitle>{label}</CardTitle><CardDescription className="wrap-anywhere">{flow ? flow.tag ?? flow.label : "Choose a recorded physical flow."}</CardDescription></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3"><FieldGroup>
        <Field><FieldLabel htmlFor={`compare-${label}-run`}>{label} run</FieldLabel><NativeSelect id={`compare-${label}-run`} className="w-full" value={id} onChange={(event) => set(event.target.value)}>
          {!choices.some((item) => item.id === id) ? <NativeSelectOption value={id}>Run {id.slice(0, 8)}</NativeSelectOption> : null}
          {choices.map((item) => <NativeSelectOption key={item.id} value={item.id}>{runName(item)} · {item.id.slice(0, 8)}</NativeSelectOption>)}
        </NativeSelect></Field>
        <Field><FieldLabel htmlFor={`compare-${label}-flow`}>{label} flow</FieldLabel><NativeSelect id={`compare-${label}-flow`} className="w-full" value={flow?.key ?? ""} disabled={!side.options.length} onChange={(event) => side.select(event.target.value)}>
          {!side.options.length ? <NativeSelectOption value="">{side.loading ? "Loading flows…" : "No recorded flows"}</NativeSelectOption> : side.options.map((option) => <NativeSelectOption key={option.key} value={option.key}>{option.label}</NativeSelectOption>)}
        </NativeSelect></Field>
      </FieldGroup>{side.error ? <p role="alert" className="text-sm text-destructive">{side.error}</p> : null}<EvidenceNotice label={label} evidence={evidence} />{side.error || evidence.sourceError || evidence.detailError ? <Button type="button" variant="outline" size="sm" onClick={() => { side.retry(); evidence.retry(); }}>Retry {label.toLowerCase()} evidence</Button> : null}</CardContent>
    </Card>)}</div>
    <Card className="min-w-0"><CardHeader><CardTitle>Source comparison</CardTitle><CardDescription>Baseline on the left, candidate on the right; narrow screens use a unified diff. These recorded files are read-only.</CardDescription></CardHeader><CardContent className="flex min-w-0 flex-col gap-3">
      {sourceReady && paths.length ? <><Field><FieldLabel htmlFor="compare-file">Compare file</FieldLabel><NativeSelect id="compare-file" className="w-full" value={selectedFile} onChange={(event) => setFile(event.target.value)}>{paths.map((path) => <NativeSelectOption key={path} value={path}>{path}{beforeFiles[path] === undefined ? " · added" : afterFiles[path] === undefined ? " · removed" : beforeFiles[path] === afterFiles[path] ? " · unchanged" : " · changed"}</NativeSelectOption>)}</NativeSelect></Field>
        <p className="text-xs text-muted-foreground">{beforeFiles[selectedFile] === undefined ? "File is absent from the baseline snapshot." : afterFiles[selectedFile] === undefined ? "File is absent from the candidate snapshot." : beforeFiles[selectedFile] === afterFiles[selectedFile] ? "This file is identical in both snapshots." : "Changes are highlighted between the two snapshots."}</p>
        <div className="h-[560px] min-w-0 overflow-hidden rounded-md border" data-testid="workspace-source-diff"><Diff path={selectedFile} before={beforeFiles[selectedFile] ?? ""} after={afterFiles[selectedFile] ?? ""} /></div>
      </> : <p role="status" className="text-sm text-muted-foreground">{before.loading || after.loading ? "Loading immutable source snapshots…" : "Source comparison requires an available snapshot on each side. Missing evidence is never replaced with current working files."}</p>}
    </CardContent></Card>
    {beforeMetrics?.clock_mhz != null && afterMetrics?.clock_mhz != null && beforeMetrics.clock_mhz !== afterMetrics.clock_mhz ? <Alert><AlertDescription>These flows use different clock targets. Their WNS and PPA changes do not isolate the effect of the source edits.</AlertDescription></Alert> : null}
    <Card className="min-w-0"><CardHeader><CardTitle>Measurements</CardTitle><CardDescription>Change = candidate − baseline. Clock is a configured target; power may be reported at different corners.</CardDescription></CardHeader><CardContent className="min-w-0"><Table className="table-fixed text-xs"><TableHeader><TableRow><TableHead className="whitespace-normal">Measurement</TableHead><TableHead>Baseline</TableHead><TableHead>Candidate</TableHead><TableHead>Change</TableHead></TableRow></TableHeader><TableBody>
      {metricRows.map(([key, label, unit, digits]) => { const a = beforeMetrics?.[key], b = afterMetrics?.[key], known = typeof a === "number" && Number.isFinite(a) && typeof b === "number" && Number.isFinite(b); return <TableRow key={key}><TableHead scope="row" className="whitespace-normal">{label}<span className="block">{unit}</span></TableHead><TableCell className="whitespace-normal wrap-anywhere">{a == null ? "Unknown" : number(a, digits)}</TableCell><TableCell className="whitespace-normal wrap-anywhere">{b == null ? "Unknown" : number(b, digits)}</TableCell><TableCell className="whitespace-normal wrap-anywhere">{known ? `${b - a > 0 ? "+" : ""}${number(b - a, digits)}` : "Unknown"}</TableCell></TableRow>; })}
    </TableBody></Table></CardContent></Card>
    <Card className="min-w-0"><CardHeader><CardTitle>Configuration comparison</CardTitle><CardDescription>Each configuration stage stays separate; unavailable settings are not inferred from another stage.</CardDescription></CardHeader><CardContent className="flex min-w-0 flex-col gap-3">{configs.map(([key, label]) => {
      const a = before.detail?.provenance.evidence_status === "invalid" ? null : before.detail?.[key] ?? null;
      const b = after.detail?.provenance.evidence_status === "invalid" ? null : after.detail?.[key] ?? null;
      const keys = Array.from(new Set([...Object.keys(a ?? {}), ...Object.keys(b ?? {})])) as (keyof FlowConfig)[];
      return <details key={key} className="rounded-md border p-3"><summary className="cursor-pointer rounded-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">{label}</summary>{keys.length ? <Table className="mt-3 table-fixed text-xs"><TableHeader><TableRow><TableHead>Setting</TableHead><TableHead>Baseline</TableHead><TableHead>Candidate</TableHead></TableRow></TableHeader><TableBody>{keys.map((setting) => <TableRow key={setting}><TableHead scope="row" className="whitespace-normal wrap-anywhere">{setting}</TableHead><TableCell className="whitespace-normal wrap-anywhere">{display(a?.[setting])}</TableCell><TableCell className="whitespace-normal wrap-anywhere">{display(b?.[setting])}</TableCell></TableRow>)}</TableBody></Table> : <p className="mt-3 text-sm text-muted-foreground">{a === null && b === null ? "This stage was not recorded for either flow." : "No overrides were recorded for the available configuration."}</p>}</details>;
    })}</CardContent></Card>
  </div>;
}
