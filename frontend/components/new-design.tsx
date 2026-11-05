"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, CircleAlert, RefreshCw } from "lucide-react";
import { createRun, getJson, type Check, type Health } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverDescription, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/logo";
import { ModelSettings } from "@/components/model-settings";
import { BuildSettings } from "@/components/build-settings";
import { buildSettingsConfig, buildSettingsDraft, buildSettingsError } from "@/lib/build-settings";
import { clearDesignDraft, loadDesignDraft, saveDesignDraft, maxSpecLength, type DesignDraft } from "@/lib/design-draft";
import { loadRunDefaults } from "@/lib/run-defaults";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

const initialDraft: DesignDraft = {
  spec: "An 8-bit up/down counter with enable, synchronous load, and active-low reset.",
  selectedPreset: "counter", clock: "50", fit: false, review: true,
};

function checkLabel(check: Check | undefined, fallback: string) {
  if (!check) return fallback;
  if (check.status === "ok") return "Ready";
  if (check.status === "not_configured") return "Not configured";
  if (check.status === "not_verified" || check.status === "not_checked") return "Not verified";
  if (check.status === "unavailable" || check.status === "error") return "Unavailable";
  return check.status.replaceAll("_", " ");
}

export function NewDesign() {
  const router = useRouter();
  const [draft, setDraft] = useState<DesignDraft>(initialDraft);
  const savedDraft = useRef<DesignDraft | null>(null);
  const { spec, clock, fit, review, selectedPreset } = draft;
  const [hasDraft, setHasDraft] = useState(false);
  const [draftReady, setDraftReady] = useState(false);
  const [draftMessage, setDraftMessage] = useState("");
  const [draftError, setDraftError] = useState("");
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState("");
  const [expert, setExpert] = useState(false);
  const [health, setHealth] = useState<Health>();
  const [apiState, setApiState] = useState("Checking");
  const healthRequest = useRef<AbortController | null>(null);
  const flowDraft = draft.build ?? buildSettingsDraft();
  const flowError = buildSettingsError(flowDraft);

  async function refreshHealth() {
    healthRequest.current?.abort();
    const controller = new AbortController();
    healthRequest.current = controller;
    setApiState("Checking");
    try {
      const value = await getJson<Health>("/api/health", controller.signal);
      if (!controller.signal.aborted) { setHealth(value); setApiState("Ready"); }
    } catch {
      if (!controller.signal.aborted) { setHealth(undefined); setApiState("Unavailable"); }
    }
  }

  useEffect(() => {
    const defaults = loadRunDefaults();
    const saved = loadDesignDraft();
    savedDraft.current = saved.draft;
    setDraft(saved.draft ?? { ...initialDraft, clock: String(defaults.clock), fit: defaults.fit });
    setExpert(defaults.expert);
    setDraftReady(true);
    setHasDraft(Boolean(saved.draft));
    if (saved.draft) setDraftMessage("Restored your draft from this browser.");
    if (!saved.available) setDraftError("Browser storage is unavailable. Keep this page open to preserve your edits.");
    void refreshHealth();
    return () => healthRequest.current?.abort();
  }, []);

  function editDraft(changes: Partial<DesignDraft>) {
    if (!draftReady || building) return;
    const next = { ...draft, ...changes };
    setDraft(next);
    setHasDraft(true);
    setBuildError("");
    if (saveDesignDraft(next)) { savedDraft.current = next; setDraftMessage("Draft saved in this browser."); setDraftError(""); }
    else { setDraftMessage(""); setDraftError("Draft could not be saved in this browser. Keep this page open to preserve your edits."); }
  }

  function discardDraft() {
    const result = clearDesignDraft(savedDraft.current);
    if (result === "unavailable") { setDraftError("Saved draft could not be removed. Your current edits are still here."); return; }
    savedDraft.current = null;
    const defaults = loadRunDefaults();
    setDraft({ ...initialDraft, clock: String(defaults.clock), fit: defaults.fit });
    setHasDraft(false);
    setDraftMessage(result === "changed" ? "This tab's draft was discarded. A newer draft from another tab was kept." : "Draft discarded. New-design defaults restored.");
    setDraftError("");
    setBuildError("");
  }

  async function build(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (building || !draftReady) return;
    if (!valid) {
      setBuildError(flowError ?? (spec.trim().length < 10 ? "Describe the chip in at least 10 characters." : spec.length > maxSpecLength ? "Keep the chip description within 12,000 characters." : "Target clock must be between 1 and 1000 MHz."));
      return;
    }
    setBuilding(true);
    setBuildError("");
    try {
      const result = await createRun({ spec_text: spec, preset_id: selectedPreset, targets: { clock_mhz: Number(clock), ...(fit ? { fit: "tt_1x1_tile" as const } : {}) }, ...(draft.build ? { build: buildSettingsConfig(flowDraft)! } : {}), ...(expert && review ? { review: true } : {}) });
      clearDesignDraft(savedDraft.current);
      router.push(`/runs/${result.run_id}`);
    } catch (reason) {
      setBuildError(reason instanceof Error ? reason.message : "The build could not be queued.");
      setBuilding(false);
    }
  }
  const valid = spec.trim().length >= 10 && spec.length <= maxSpecLength && Number(clock) >= 1 && Number(clock) <= 1000 && !flowError;
  const checks = [
    { name: "API", label: apiState, detail: apiState === "Ready" ? "Backend API is reachable." : apiState === "Unavailable" ? "The API could not be reached. Check that the app is running, then refresh." : "Checking API availability…", ready: apiState === "Ready" },
    { name: "Database", label: checkLabel(health?.checks.database, apiState === "Unavailable" ? "Unavailable" : "Checking"), detail: health?.checks.database.detail, ready: health?.checks.database.status === "ok" },
    { name: "Worker", label: checkLabel(health?.checks.worker, apiState === "Unavailable" ? "Unavailable" : "Not verified"), detail: health?.checks.worker?.detail ?? "The API has not reported worker status yet.", ready: health?.checks.worker?.status === "ok" },
    { name: "EDA", label: checkLabel(health?.checks.eda, apiState === "Unavailable" ? "Unavailable" : "Not verified"), detail: health?.checks.eda.detail, ready: health?.checks.eda.status === "ok" },
    { name: health ? health.llm_provider === "codex" ? "Codex" : "Meta" : "Model", label: checkLabel(health?.checks.llm, apiState === "Unavailable" ? "Unavailable" : "Checking"), detail: health?.checks.llm.detail, ready: health?.checks.llm.status === "ok" },
  ];

  return (
    <div className="mx-auto flex min-h-[calc(100svh-6.5rem)] w-full max-w-3xl flex-col gap-6 pb-[10vh]">
      <div className="flex flex-1 flex-col items-center justify-center gap-5">
        <Logo className="size-28 text-muted-foreground" strokeWidth={1.5} />
        <h1 className="text-2xl font-medium tracking-tight text-muted-foreground">Describe a chip. Get a real layout.</h1>
      </div>
      <form onSubmit={build} className="@container space-y-3" aria-labelledby="design-title">
        <h2 id="design-title" className="sr-only">Design specification</h2>
        {/* The stock group dims whenever a child is disabled; drive fade/glow from the prompt instead. */}
        <InputGroup aria-busy={building} className={cn("glass rounded-2xl bg-transparent transition-[opacity,box-shadow,border-color] duration-300 has-disabled:bg-transparent dark:bg-transparent dark:has-disabled:bg-transparent", spec.trim() ? "border-ring/60 shadow-[0_0_32px_-6px_oklch(0_0_0/0.14)] dark:shadow-[0_0_32px_-6px_oklch(1_0_0/0.18)] has-disabled:opacity-100" : "opacity-60 shadow-none has-disabled:opacity-60 focus-within:opacity-100 focus-within:has-disabled:opacity-100")}>
          <Label className="sr-only" htmlFor="design-spec">Describe your chip</Label>
          <InputGroupTextarea id="design-spec" className="min-h-28 px-4 pt-4 text-base leading-relaxed" value={spec} maxLength={maxSpecLength} disabled={building || !draftReady} aria-describedby="design-hint" onChange={(event) => editDraft({ spec: event.target.value, selectedPreset: undefined })} onKeyDown={(event) => { if (!event.nativeEvent.isComposing && event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); if (flowError) setBuildError(flowError); else event.currentTarget.form?.requestSubmit(); } }} spellCheck={false} placeholder="An 8-bit counter with enable and synchronous reset…" />
          <InputGroupAddon align="block-end" className="flex-wrap items-center gap-3 border-t px-3 pt-2.5">
            <Label htmlFor="target-clock" className="gap-1.5 text-xs font-normal text-muted-foreground">Clock
              <Input id="target-clock" type="number" min="1" max="1000" step="any" disabled={building || !draftReady} value={clock} onChange={(event) => editDraft({ clock: event.target.value })} className="h-7 w-20 text-xs" aria-label="Target clock (MHz)" />MHz
            </Label>
            <div className="flex h-4 items-center gap-2 @md:border-l @md:pl-3" onClick={(event) => event.stopPropagation()}>
              <Checkbox id="fit-tile" checked={fit} disabled={building || !draftReady} onCheckedChange={(checked) => editDraft({ fit: checked === true })} />
              <Label htmlFor="fit-tile" className="text-xs font-normal text-muted-foreground">Fit in one Tiny Tapeout tile</Label>
            </div>
            {/* Expert mode (Settings) only: the orchestrator stops after drafting the spec so every field can be edited. */}
            {expert ? <div className="flex h-4 items-center gap-2 @md:border-l @md:pl-3" onClick={(event) => event.stopPropagation()}>
              <Checkbox id="review-spec" checked={review} disabled={building || !draftReady} onCheckedChange={(checked) => editDraft({ review: checked === true })} />
              <Label htmlFor="review-spec" className="text-xs font-normal text-muted-foreground">Review spec before RTL</Label>
            </div> : null}
            <ModelSettings />
            {/* Collapses to an icon until there is a spec to build. */}
            <InputGroupButton type="submit" variant="default" size={spec.trim() || building ? "sm" : "icon-sm"} className="rounded-full" aria-label="Build my chip" disabled={building || !draftReady || !spec.trim() || Boolean(flowError)}>{building ? <><Spinner data-icon="inline-start" />Queuing your chip…</> : spec.trim() ? <>Build my chip<ArrowUp data-icon="inline-end" /></> : <ArrowUp />}</InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <p id="design-hint">{spec.length.toLocaleString()} / 12,000 characters · Ctrl or ⌘ + Enter to build</p>
          {hasDraft ? <Button type="button" variant="ghost" size="sm" disabled={building || !draftReady} onClick={discardDraft}>Discard draft</Button> : null}
          <p className="w-full" role="status">{draftError || draftMessage}</p>
        </div>
        {buildError ? <Alert variant="destructive"><CircleAlert /><AlertDescription>{buildError}</AlertDescription></Alert> : null}
        <details className="glass rounded-lg border px-3 py-2">
          <summary className="cursor-pointer rounded-sm text-xs font-medium focus-visible:outline-2 focus-visible:outline-ring">Configure physical flow{draft.build ? " · customized" : ""}{flowError ? " · needs attention" : ""}</summary>
          <div className="pt-3"><BuildSettings value={flowDraft} disabled={building || !draftReady} onChange={(build) => editDraft({ build })} /></div>
        </details>
      </form>
      <section aria-labelledby="toolchain-title" className="space-y-2">
        <div className="flex items-center justify-center gap-2">
          <h2 id="toolchain-title" className="text-xs font-medium text-muted-foreground">Toolchain</h2>
          <Button type="button" size="sm" variant="ghost" disabled={apiState === "Checking"} onClick={() => void refreshHealth()} aria-label="Refresh toolchain status"><RefreshCw className={apiState === "Checking" ? "animate-spin motion-reduce:animate-none" : ""} />Refresh</Button>
        </div>
        <ul className="flex flex-wrap items-center justify-center gap-2" aria-live="polite">
          {checks.map((check) => <li key={check.name}>
            <Popover>
              <PopoverTrigger asChild><Button type="button" variant="outline" size="sm" className="check-row glass rounded-full bg-transparent text-xs dark:bg-transparent" aria-label={`${check.name}: ${check.label}. Show details`}>
                <span className={check.ready ? "size-1.5 rounded-full bg-success" : "size-1.5 rounded-full bg-muted-foreground"} aria-hidden="true" />
                <span className="font-medium">{check.name}</span><span className="text-muted-foreground">{check.label}</span>
              </Button></PopoverTrigger>
              <PopoverContent className="max-w-[calc(100vw-2rem)]">
                <PopoverTitle>{check.name}: {check.label}</PopoverTitle>
                <PopoverDescription>{check.detail ?? "Status has not been reported yet."}</PopoverDescription>
              </PopoverContent>
            </Popover>
          </li>)}
        </ul>
      </section>
    </div>
  );
}
