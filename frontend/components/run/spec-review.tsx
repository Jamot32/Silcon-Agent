"use client";

import { useState } from "react";
import { CircleAlert, ClipboardCheck, Plus, RotateCcw, X } from "lucide-react";
import { submitReview, type BuildConfig, type DesignSpec, type FlowKnob, type Port, type PublicRun, type ReviewRequest, type RunEvent } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { Panel } from "./panel";

// Mirrors STRATEGIES in backend/app/eda/flow.py; the planner uses AREA 0 when none is chosen.
const strategies = [...[0, 1, 2, 3].map((index) => `AREA ${index}`), ...[0, 1, 2, 3, 4].map((index) => `DELAY ${index}`)];

// The orchestrator's latest request: its drafted DesignSpec, the default BuildConfig and any locked fields.
export function reviewRequest(events: RunEvent[]): ReviewRequest | null {
  const value = events.findLast((event) => event.type === "note" && typeof event.payload.review_request === "object")?.payload.review_request;
  return value && typeof value === "object" && !Array.isArray(value) ? value as unknown as ReviewRequest : null;
}

// Empty number inputs mean "not set"; the API reports anything out of range by field.
const optional = (value: number) => Number.isFinite(value) ? value : null;

function ListField({ id, label, hint, items, min, onChange }: { id: string; label: string; hint: string; items: string[]; min: number; onChange: (items: string[]) => void }) {
  return <fieldset className="grid gap-2" aria-describedby={`${id}-hint`}>
    <legend className="text-sm font-medium">{label}</legend>
    <p id={`${id}-hint`} className="-mt-1 text-xs text-muted-foreground">{hint}</p>
    {items.map((item, index) => <div key={index} className="flex items-start gap-2">
      <Textarea value={item} rows={1} className="min-h-9 text-sm" aria-label={`${label} ${index + 1}`} onChange={(event) => onChange(items.map((value, position) => position === index ? event.target.value : value))} />
      <Button type="button" variant="ghost" size="icon-sm" aria-label={`Remove ${label.toLowerCase()} ${index + 1}`} disabled={items.length <= min} onClick={() => onChange(items.filter((_, position) => position !== index))}><X /></Button>
    </div>)}
    <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => onChange([...items, ""])}><Plus data-icon="inline-start" />Add {label.toLowerCase()} line</Button>
  </fieldset>;
}

function PortsField({ ports, locked, onChange }: { ports: Port[]; locked: boolean; onChange: (ports: Port[]) => void }) {
  const update = (index: number, patch: Partial<Port>) => onChange(ports.map((port, position) => position === index ? { ...port, ...patch } : port));
  return <fieldset className="grid gap-2" disabled={locked}>
    <legend className="text-sm font-medium">Ports</legend>
    <p className="-mt-1 text-xs text-muted-foreground">{locked ? "Fixed by the supplied starter's interface." : "Sequential designs need one-bit inputs clk and rst_n. Names must be unique Verilog identifiers."}</p>
    <div className="hidden grid-cols-[minmax(0,1fr)_7rem_5rem_minmax(0,2fr)_2rem] gap-2 text-xs text-muted-foreground md:grid" aria-hidden="true"><span>Name</span><span>Direction</span><span>Width</span><span>Description</span></div>
    {ports.map((port, index) => <div key={index} className="grid grid-cols-[minmax(0,1fr)_6rem_4rem_2rem] gap-2 border-b pb-2 md:grid-cols-[minmax(0,1fr)_7rem_5rem_minmax(0,2fr)_2rem] md:border-0 md:pb-0">
      <Input value={port.name} aria-label={`Port ${index + 1} name`} className="font-mono text-xs" spellCheck={false} onChange={(event) => update(index, { name: event.target.value })} />
      <NativeSelect value={port.direction} aria-label={`Port ${index + 1} direction`} onChange={(event) => update(index, { direction: event.target.value as Port["direction"] })}>
        <NativeSelectOption value="input">input</NativeSelectOption><NativeSelectOption value="output">output</NativeSelectOption>
      </NativeSelect>
      <Input type="number" min="1" max="1024" step="1" required value={Number.isFinite(port.width) ? port.width : ""} aria-label={`Port ${index + 1} width`} className="text-xs" onChange={(event) => update(index, { width: event.target.valueAsNumber })} />
      <Button type="button" variant="ghost" size="icon-sm" className="md:order-last" aria-label={`Remove port ${index + 1}`} disabled={ports.length <= 1} onClick={() => onChange(ports.filter((_, position) => position !== index))}><X /></Button>
      <Input value={port.description} aria-label={`Port ${index + 1} description`} className="col-span-4 text-xs md:col-span-1" onChange={(event) => update(index, { description: event.target.value })} />
    </div>)}
    <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => onChange([...ports, { name: "", direction: "input", width: 1, description: "" }])}><Plus data-icon="inline-start" />Add port</Button>
  </fieldset>;
}

function NumberField({ id, label, value, min, max, step, placeholder, required, onChange }: { id: string; label: string; value: number | null | undefined; min: number; max: number; step?: string; placeholder?: string; required?: boolean; onChange: (value: number) => void }) {
  return <div className="grid gap-1.5">
    <Label htmlFor={id} className="text-xs font-normal text-muted-foreground">{label}</Label>
    <Input id={id} type="number" min={min} max={max} step={step ?? "any"} placeholder={placeholder} required={required} value={value ?? ""} className="text-sm" onChange={(event) => onChange(event.target.valueAsNumber)} />
  </div>;
}

export function SpecReview({ run, events, since, onSubmitted }: { run: PublicRun; events: RunEvent[]; since: number | null; onSubmitted: () => Promise<void> }) {
  const request = reviewRequest(events);
  // Drafts start from the orchestrator's request and stay put while you edit.
  const [draft, setDraft] = useState<{ spec: DesignSpec; build: BuildConfig } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState("");
  if (run.review_submitted) return <Alert data-testid="spec-review" data-state="submitted"><ClipboardCheck /><AlertDescription><span className="font-medium text-foreground">Review submitted.</span> The orchestrator is applying your spec and build settings, then the RTL designer starts.</AlertDescription></Alert>;
  if (!request) return <Alert data-testid="spec-review" data-state="waiting"><Spinner /><AlertDescription>Waiting for the orchestrator&apos;s drafted DesignSpec…</AlertDescription></Alert>;
  const { spec, build } = draft ?? { spec: request.design_spec, build: request.build };
  const locked = new Set(request.locked);
  const setSpec = (patch: Partial<DesignSpec>) => { setDraft({ spec: { ...spec, ...patch }, build }); setFailure(""); };
  const setBuild = (patch: Partial<BuildConfig>) => { setDraft({ spec, build: { ...build, ...patch } }); setFailure(""); };
  const setKnob = (key: FlowKnob, value: string | number | null) => {
    const { [key]: _, ...rest } = build.initial_flow;
    setBuild({ initial_flow: value === null || value === "" ? rest : { ...rest, [key]: value } });
  };

  async function approve(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      await submitReview(run.id, { design_spec: spec, build });
      await onSubmitted();
    } catch (reason) {
      setFailure(reason instanceof Error ? reason.message : "The review could not be submitted.");
    } finally {
      setSubmitting(false);
    }
  }

  return <Panel id="spec-review-title" title="Review the drafted spec" data-testid="spec-review" data-state="open"
    aside={<Button type="button" variant="ghost" size="sm" disabled={!draft} onClick={() => { setDraft(null); setFailure(""); }}><RotateCcw data-icon="inline-start" />Reset to draft</Button>}>
    {/* Approving starts paid RTL and EDA work, so Enter in a one-line field never submits; use the button. */}
    <form onSubmit={approve} onKeyDown={(event) => { if (event.key === "Enter" && event.target instanceof HTMLInputElement) event.preventDefault(); }} className="grid gap-6 p-4" aria-labelledby="spec-review-title">
      <p className="text-sm text-muted-foreground">The orchestrator drafted this DesignSpec from your request and is waiting before any RTL is written. Edit anything, then approve. Tests are written from this spec. The worker stays reserved for this run until you approve or cancel{since !== null ? <>; approve by <time dateTime={new Date(since + 30 * 60_000).toISOString()} className="font-medium text-foreground">{new Date(since + 30 * 60_000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</time> or the run stops</> : "; after 30 minutes the run stops"}.</p>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="grid content-start gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="review-top">Top module</Label>
            <Input id="review-top" value={spec.top_module} disabled={locked.has("top_module")} className="font-mono text-sm" spellCheck={false} onChange={(event) => setSpec({ top_module: event.target.value })} />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="review-comb" checked={spec.purely_combinational} disabled={locked.has("purely_combinational")} onCheckedChange={(checked) => setSpec({ purely_combinational: checked === true })} />
            <Label htmlFor="review-comb" className="font-normal">Purely combinational (no clk or rst_n)</Label>
          </div>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="review-summary">Summary</Label>
          <Textarea id="review-summary" value={spec.summary} className="min-h-20 text-sm" onChange={(event) => setSpec({ summary: event.target.value })} />
        </div>
      </div>
      <PortsField ports={spec.ports} locked={locked.has("ports")} onChange={(ports) => setSpec({ ports })} />
      <div className="grid gap-6 lg:grid-cols-2">
        <ListField id="review-behavior" label="Behavior" hint="Each line is one testable requirement." items={spec.behavior} min={1} onChange={(behavior) => setSpec({ behavior })} />
        <ListField id="review-tests" label="Test plan" hint="At least four tests; the test author writes cocotb tests from these." items={spec.test_plan} min={4} onChange={(test_plan) => setSpec({ test_plan })} />
      </div>
      <fieldset className="grid gap-3">
        <legend className="text-sm font-medium">Targets</legend>
        <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-3">
          <NumberField id="review-clock" label="Clock (MHz)" value={spec.targets.clock_mhz} min={1} max={1000} placeholder="Not set" onChange={(value) => setSpec({ targets: { ...spec.targets, clock_mhz: optional(value) } })} />
          <NumberField id="review-area" label="Max area (µm²)" value={spec.targets.max_area_um2} min={1} max={1e9} placeholder="No limit" onChange={(value) => setSpec({ targets: { ...spec.targets, max_area_um2: optional(value) } })} />
          <div className="col-span-2 flex h-9 items-center gap-2 sm:col-span-1">
            <Checkbox id="review-fit" checked={spec.targets.fit === "tt_1x1_tile"} onCheckedChange={(checked) => setSpec({ targets: { ...spec.targets, fit: checked === true ? "tt_1x1_tile" : null } })} />
            <Label htmlFor="review-fit" className="text-sm font-normal">Fit in one Tiny Tapeout tile</Label>
          </div>
        </div>
      </fieldset>
      <fieldset className="grid gap-3 rounded-lg border p-3">
        <legend className="px-1 text-sm font-medium">Build settings</legend>
        <div className="flex items-start gap-2">
          <Checkbox id="review-optimize" className="mt-0.5" checked={build.optimize} onCheckedChange={(checked) => setBuild({ optimize: checked === true })} />
          <Label htmlFor="review-optimize" className="font-normal">Let the PPA optimizer compare variants after the first layout</Label>
        </div>
        <div className="grid grid-cols-2 items-end gap-3 md:grid-cols-5">
          <NumberField id="review-flows" label="Flow attempts (1–6)" value={Number.isFinite(build.max_flow_runs) ? build.max_flow_runs : null} min={1} max={6} step="1" required onChange={(value) => setBuild({ max_flow_runs: value })} />
          <NumberField id="review-repairs" label="RTL repair loops (0–5)" value={Number.isFinite(build.max_repair_loops) ? build.max_repair_loops : null} min={0} max={5} step="1" required onChange={(value) => setBuild({ max_repair_loops: value })} />
          <div className="grid gap-1.5">
            <Label htmlFor="review-strategy" className="text-xs font-normal text-muted-foreground">Synthesis strategy</Label>
            <NativeSelect id="review-strategy" value={build.initial_flow.SYNTH_STRATEGY ?? ""} onChange={(event) => setKnob("SYNTH_STRATEGY", event.target.value)}>
              <NativeSelectOption value="">Planner default (AREA 0)</NativeSelectOption>
              {strategies.map((strategy) => <NativeSelectOption key={strategy} value={strategy}>{strategy}</NativeSelectOption>)}
            </NativeSelect>
          </div>
          <NumberField id="review-util" label="Core utilization (%)" value={build.initial_flow.FP_CORE_UTIL} min={1} max={90} placeholder="Planner" onChange={(value) => setKnob("FP_CORE_UTIL", optional(value))} />
          <NumberField id="review-density" label="Placement density (%)" value={build.initial_flow.PL_TARGET_DENSITY_PCT} min={1} max={90} placeholder="Planner" onChange={(value) => setKnob("PL_TARGET_DENSITY_PCT", optional(value))} />
        </div>
        <p className="text-xs text-muted-foreground">Synthesis strategy, utilization and density apply to the first layout and to re-measured RTL edits. The planner still sizes the die, and the clock comes from the clock target.</p>
      </fieldset>
      {failure ? <Alert variant="destructive"><CircleAlert /><AlertDescription className="whitespace-pre-line">{failure.split("; ").join("\n")}</AlertDescription></Alert> : null}
      <div className="flex flex-wrap items-center justify-end gap-3">
        <span className="text-xs text-muted-foreground">{draft ? "Edited from the draft." : "Unchanged draft."}</span>
        <Button type="submit" disabled={submitting} data-testid="approve-review">{submitting ? <><Spinner data-icon="inline-start" />Submitting…</> : "Approve and build"}</Button>
      </div>
    </form>
  </Panel>;
}

