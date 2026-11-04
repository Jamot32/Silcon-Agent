"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { CircleAlert, GitBranch, Plus, SlidersHorizontal, Wrench } from "lucide-react";
import { createRun, type BuildConfig, type LayoutRegionInput, type PublicRun, type RevisionIntent } from "@/lib/api";
import { BuildSettings } from "@/components/build-settings";
import { buildSettingsConfig, buildSettingsDraft, buildSettingsError, type BuildSettingsDraft } from "@/lib/build-settings";
import { loadRunDefaults } from "@/lib/run-defaults";
import { followUpRequest, revisionDefaults, revisionRequest, type FollowUpEdit } from "@/lib/revision";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

const goals = [
  { id: "feature", label: "Add a feature", icon: Plus, hint: "Describe the new behavior, ports, and acceptance criteria. Existing requirements stay in place unless you change them.", placeholder: "Add a programmable baud divisor. Keep the existing reset and send behavior…" },
  { id: "fix", label: "Fix a problem", icon: Wrench, hint: "Describe the failing behavior and what should happen instead. The previous outcome is included as context.", placeholder: "Fix the missing final bit when send is asserted during a busy cycle…" },
  { id: "optimize", label: "Optimize", icon: SlidersHorizontal, hint: "Name the trade-off: less area, tighter timing, or another measurable goal. Preserve the interface and behavior unless you explicitly change them.", placeholder: "Reduce cell area while preserving the interface, behavior, and clock target…" },
] as const;

type Props = { run: PublicRun; files: Record<string, string>; size?: "lg"; initialFlow?: BuildConfig["initial_flow"]; sourceFlow?: string; triggerLabel?: string; layoutRegion?: LayoutRegionInput; initialFollowUp?: string; initialIntent?: RevisionIntent };
export function ReviseRun(props: Props) {
  // Navigation to another terminal run must not reuse this run's pending form.
  return <RevisionForm key={`${props.run.id}:${props.sourceFlow ?? "default"}:${JSON.stringify(props.layoutRegion ?? null)}`} {...props} />;
}

function RevisionForm({ run, files, size, initialFlow, sourceFlow, triggerLabel, layoutRegion, initialFollowUp, initialIntent }: Props) {
  const router = useRouter();
  const formId = useId();
  const rtl = Object.keys(files).filter((path) => path.startsWith("src/") && path.endsWith(".v"));
  const targets = { ...run.design_spec?.targets, ...run.targets };
  const defaults: FollowUpEdit = { ...revisionDefaults(run, rtl.length > 0), area: targets.max_area_um2 ?? null, followUp: initialFollowUp ?? (initialFlow ? `Evaluate the initial flow settings copied from ${sourceFlow ?? "the inspected flow"} while preserving the interface and behavior. Measure the result against the selected parent design.` : ""), intent: initialIntent ?? (initialFlow ? "optimize" : run.status === "failed" ? "fix" : "feature") };
  const inheritedBuild = run.build_config ?? run.requested_build;
  const [flowSettings, setFlowSettings] = useState<BuildSettingsDraft | null>(null);
  const flowDraft = flowSettings ?? buildSettingsDraft(initialFlow ? { ...(inheritedBuild ?? { optimize: true, max_flow_runs: 6, max_repair_loops: 5 }), initial_flow: initialFlow } : inheritedBuild);
  const configuredBuild = !!(flowSettings || initialFlow || inheritedBuild);
  const configurationChanged = !!initialFlow || JSON.stringify(buildSettingsConfig(flowDraft)) !== JSON.stringify(buildSettingsConfig(buildSettingsDraft(inheritedBuild)));
  const [edit, setEdit] = useState<FollowUpEdit | null>(null);
  const [mode, setMode] = useState("follow-up");
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState("");
  const [review, setReview] = useState(false);
  const form = edit ?? defaults;
  const followUp = mode === "follow-up";
  const goal = goals.find((item) => item.id === form.intent)!;
  const { body: replacement, rerun } = revisionRequest(run, form, defaults);
  const repeat = rerun && !configurationChanged && !layoutRegion;
  const body = followUp ? followUpRequest(run, form, defaults) : replacement;
  const text = followUp ? form.followUp : form.spec;
  const limit = followUp ? 4000 : 12000;
  const clockValid = Number.isFinite(form.clock) && form.clock >= 1 && form.clock <= 1000;
  const areaValid = !followUp || form.area === null || (Number.isFinite(form.area) && form.area > 0);
  const valid = text.trim().length >= 10 && text.length <= limit && clockValid && areaValid && !buildSettingsError(flowDraft);
  const change = (patch: Partial<FollowUpEdit>) => { if (!submitting) { setEdit({ ...form, ...patch }); setFailure(""); } };

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || !valid) return;
    setSubmitting(true); setFailure("");
    try {
      const result = await createRun({ ...body, ...(layoutRegion ? { layout_region: layoutRegion } : {}), ...(configuredBuild ? { build: buildSettingsConfig(flowDraft)! } : {}), ...(review ? { review: true } : {}) });
      router.push(`/runs/${result.run_id}`);
    } catch (reason) {
      setFailure(reason instanceof Error ? reason.message : "The build could not be queued.");
      setSubmitting(false);
    }
  }

  return <Sheet onOpenChange={(open) => { if (open && !edit) { setEdit(defaults); setReview(loadRunDefaults().expert); } }}>
    <SheetTrigger asChild><Button variant="outline" size={size} className={size ? "flex-1 sm:flex-none" : undefined} data-testid="revise-run"><GitBranch data-icon="inline-start" />{triggerLabel ?? "Continue design"}</Button></SheetTrigger>
    <SheetContent className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl">
      <SheetHeader className="shrink-0 border-b pr-12">
        <SheetTitle>Continue this design</SheetTitle>
        <SheetDescription>Add a feature, fix a problem, or optimize this result. Each submission creates a linked {run.is_replay ? "live build from this recording" : "build"} with model and EDA calls.</SheetDescription>
      </SheetHeader>
      <form id={formId} onSubmit={submit} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4" aria-label="Revision" aria-busy={submitting}>
        <fieldset disabled={submitting} className="contents">
          <Tabs value={mode} onValueChange={(value) => { if (!submitting) { setMode(value); setFailure(""); } }}>
            <TabsList className="w-full" aria-label="Revision mode"><TabsTrigger value="follow-up" disabled={submitting}>Follow-up</TabsTrigger><TabsTrigger value="full-request" disabled={submitting}>Full request</TabsTrigger></TabsList>
            <TabsContent value="follow-up" className="space-y-4 pt-2">
              <div role="group" aria-label="Change goal" className="flex flex-wrap gap-2">
                {goals.map((item) => <Button key={item.id} type="button" size="sm" variant={form.intent === item.id ? "secondary" : "outline"} aria-pressed={form.intent === item.id} onClick={() => change({ intent: item.id })}><item.icon data-icon="inline-start" />{item.label}</Button>)}
              </div>
              <div className="grid gap-2">
                <Label htmlFor="revise-follow-up">What should change?</Label>
                <p id="follow-up-help" className="text-xs leading-relaxed text-muted-foreground">{goal.hint}</p>
                <Textarea id="revise-follow-up" className="min-h-32 text-sm leading-relaxed" value={form.followUp} maxLength={4000} spellCheck={false} aria-describedby="follow-up-help revise-length" placeholder={goal.placeholder} onChange={(event) => change({ followUp: event.target.value })}
                  onKeyDown={(event) => { if (!event.nativeEvent.isComposing && event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
              </div>
              <details className="rounded-lg border p-3 text-xs">
                <summary className="cursor-pointer rounded-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">Previous requirements and outcome</summary>
                <div className="mt-3 space-y-2 text-muted-foreground">
                  <p>Run <code>{run.id.slice(0, 8)}</code> · {run.status}{run.best_run_tag ? ` · selected flow ${run.best_run_tag}` : " · no selected physical flow"}</p>
                  {run.design_spec ? <div className="space-y-2" data-testid="parent-design-contract">
                    <p className="font-medium text-foreground">Saved design specification · <code className="break-all">{run.design_spec.top_module}</code></p>
                    <p>{run.design_spec.summary}</p>
                    <ul className="list-disc space-y-1 pl-4">{run.design_spec.behavior.map((behavior, index) => <li key={index} className="break-words">{behavior}</li>)}</ul>
                    <p className="break-words">Ports: {run.design_spec.ports.map((port) => `${port.name} (${port.direction}, ${port.width} bit${port.width === 1 ? "" : "s"})`).join(" · ")}</p>
                  </div> : null}
                  <details><summary className="cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-ring">Earlier request text</summary><p className="mt-2 whitespace-pre-wrap break-words">{run.spec_text}</p></details>
                  {run.error ? <p className="break-words">Previous error: {run.error}</p> : null}
                  <p>{run.design_spec ? "Your follow-up builds on the saved specification, including reviewed changes." : "The server combines the previous request with your follow-up."} New instructions override earlier requirements only where they conflict.</p>
                </div>
              </details>
            </TabsContent>
            <TabsContent value="full-request" className="space-y-2 pt-2">
              <Label htmlFor="revise-spec">Request</Label>
              <p id="full-request-help" className="text-xs text-muted-foreground">Replace the complete request, or leave it unchanged to repeat it. Include all requirements you want to keep.</p>
              <Textarea id="revise-spec" className="max-h-[45svh] min-h-40 text-sm leading-relaxed" value={form.spec} maxLength={12000} spellCheck={false} aria-describedby="full-request-help revise-length" onChange={(event) => change({ spec: event.target.value })}
                onKeyDown={(event) => { if (!event.nativeEvent.isComposing && event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
            </TabsContent>
          </Tabs>
          <p id="revise-length" className="-mt-2 text-xs text-muted-foreground">{text.length.toLocaleString()} / {limit.toLocaleString()} characters · at least 10 required</p>
          <div className="grid gap-3 rounded-lg border p-3">
            <p className="text-sm font-medium">Engineering targets</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-1.5"><Label htmlFor="revise-clock" className="text-xs">Target clock (MHz)</Label><Input id="revise-clock" type="number" min="1" max="1000" step="any" value={Number.isFinite(form.clock) ? form.clock : ""} onChange={(event) => change({ clock: event.target.valueAsNumber })} aria-invalid={!clockValid} aria-describedby={!clockValid ? "revise-clock-error" : undefined} /></div>
              {followUp ? <div className="grid gap-1.5"><Label htmlFor="revise-area" className="text-xs">Maximum cell area (µm²)</Label><Input id="revise-area" type="number" min="0" step="any" value={form.area === null || !Number.isFinite(form.area) ? "" : form.area} onChange={(event) => change({ area: event.target.value === "" ? null : event.target.valueAsNumber })} placeholder="No limit" aria-invalid={!areaValid} aria-describedby="revise-area-help" /></div> : null}
            </div>
            {!clockValid ? <p id="revise-clock-error" className="text-xs text-destructive">Clock must be between 1 and 1000 MHz.</p> : null}
            {followUp ? <p id="revise-area-help" className={`text-xs ${areaValid ? "text-muted-foreground" : "text-destructive"}`}>{areaValid ? "Leave area blank for no limit. Targets are goals; a build may miss them." : "Area must be greater than zero, or blank for no limit."}</p> : null}
            <div className="flex items-center gap-2"><Checkbox id="revise-fit" checked={form.fit} onCheckedChange={(checked) => change({ fit: checked === true })} /><Label htmlFor="revise-fit" className="text-xs font-normal">Fit in one Tiny Tapeout tile</Label></div>
          </div>
          {sourceFlow ? <p className="break-words text-xs text-muted-foreground">Configuration copied from <code>{sourceFlow}</code>. If RTL reuse is enabled below, it loads {run.status === "done" ? "the selected parent design" : "the parent’s last working source"}. The inspected variant supplies configuration only. Review the inherited clock and area targets.</p> : null}
          {layoutRegion ? <p className="rounded-lg border p-3 text-xs leading-relaxed text-muted-foreground" data-testid="revision-layout-region">Attached layout region from <code className="wrap-anywhere">{layoutRegion.run_tag}</code>. The agent receives the image and selected crop. This starts a new verified build; placement may change beyond the selected area. Reused RTL comes from {run.status === "done" ? "the selected parent design" : "the parent’s last source state"}.</p> : null}
          <BuildSettings value={flowDraft} disabled={submitting} onChange={(value) => { setFlowSettings(value); setFailure(""); }} />
          <div className="flex items-start gap-3 rounded-lg border p-3">
            <Checkbox id="revise-reuse" className="mt-0.5" checked={form.reuse} disabled={!rtl.length || submitting} onCheckedChange={(checked) => change({ reuse: checked === true })} aria-describedby="revise-reuse-detail" />
            <div className="grid gap-1"><Label htmlFor="revise-reuse">Start from this run&apos;s RTL</Label><p id="revise-reuse-detail" className="text-xs text-muted-foreground">{rtl.length
              ? `The orchestrator loads ${run.status === "done" ? "the selected design from its bundle" : "its last source state"} and the RTL designer changes only what the new request needs. Tests are written fresh from the new request.`
              : "This run produced no RTL, so the revision starts from scratch."}</p></div>
          </div>
          <div className="flex items-start gap-2"><Checkbox id="revise-review" className="mt-0.5" checked={review} onCheckedChange={(checked) => setReview(checked === true)} /><div className="space-y-1"><Label htmlFor="revise-review" className="text-xs font-normal">Review requirements and build settings first</Label><p className="text-xs text-muted-foreground">Pause after the specification to check ports, behavior, tests, optimization, and flow limits.</p></div></div>
        </fieldset>
        {failure ? <Alert variant="destructive"><CircleAlert /><AlertDescription>{failure}</AlertDescription></Alert> : null}
      </form>
      <SheetFooter className="shrink-0 border-t">
        <p className="text-xs text-muted-foreground" aria-live="polite">{followUp ? `Keeps prior requirements and links the result to ${run.id.slice(0, 8)}.` : repeat ? "Nothing changed: this repeats the same request." : `New run linked to run ${run.id.slice(0, 8)}.`}</p>
        <Button type="submit" form={formId} disabled={submitting || !valid} data-testid="revise-submit">{submitting ? <><Spinner data-icon="inline-start" />Queuing…</> : followUp ? "Build follow-up" : repeat ? "Run again" : "Build revision"}</Button>
      </SheetFooter>
    </SheetContent>
  </Sheet>;
}
