"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, CircleAlert } from "lucide-react";
import { createRun, getJson, type Check, type Health } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/logo";
import { ModelSettings } from "@/components/model-settings";
import { loadRunDefaults } from "@/lib/run-defaults";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

const initialSpec = "An 8-bit up/down counter with enable, synchronous load, and active-low reset.";

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
  const [selectedPreset, setSelectedPreset] = useState<string | undefined>("counter");
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState("");
  const [spec, setSpec] = useState(initialSpec);
  const [clock, setClock] = useState("50");
  const [fit, setFit] = useState(false);
  const [expert, setExpert] = useState(false);
  const [review, setReview] = useState(true);
  const [health, setHealth] = useState<Health>();
  const [apiState, setApiState] = useState("Checking");

  useEffect(() => {
    const controller = new AbortController();
    // localStorage only exists in the browser, so saved defaults apply after mount.
    const defaults = loadRunDefaults();
    setClock(String(defaults.clock));
    setFit(defaults.fit);
    setExpert(defaults.expert);
    getJson<Health>("/api/health", controller.signal).then((value) => { setHealth(value); setApiState("Ready"); }, () => { if (!controller.signal.aborted) setApiState("Unavailable"); });
    return () => controller.abort();
  }, []);

  async function build(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (building) return;
    if (!valid) {
      setBuildError(spec.trim().length < 10 ? "Describe the chip in at least 10 characters." : "Target clock must be between 1 and 1000 MHz.");
      return;
    }
    setBuilding(true);
    setBuildError("");
    try {
      const result = await createRun({ spec_text: spec, preset_id: selectedPreset, targets: { clock_mhz: Number(clock), ...(fit ? { fit: "tt_1x1_tile" as const } : {}) }, ...(expert && review ? { review: true } : {}) });
      router.push(`/runs/${result.run_id}`);
    } catch (reason) {
      setBuildError(reason instanceof Error ? reason.message : "The build could not be queued.");
      setBuilding(false);
    }
  }
  const valid = spec.trim().length >= 10 && Number(clock) >= 1 && Number(clock) <= 1000;
  const checks = [
    { name: "API", label: apiState, detail: apiState === "Ready" ? "Backend API is reachable." : undefined, ready: apiState === "Ready" },
    { name: "Database", label: checkLabel(health?.checks.database, apiState === "Unavailable" ? "Unavailable" : "Checking"), detail: health?.checks.database.detail, ready: health?.checks.database.status === "ok" },
    { name: "EDA", label: checkLabel(health?.checks.eda, apiState === "Unavailable" ? "Unavailable" : "Not verified"), detail: health?.checks.eda.detail, ready: health?.checks.eda.status === "ok" },
    { name: health ? health.llm_provider === "codex" ? "Codex" : "Meta" : "Model", label: checkLabel(health?.checks.llm, apiState === "Unavailable" ? "Unavailable" : "Checking"), detail: health?.checks.llm.detail, ready: health?.checks.llm.status === "ok" },
  ];

  return (
    <div className="mx-auto flex min-h-[calc(100svh-6.5rem)] w-full max-w-3xl flex-col gap-6 pb-[10vh]">
      <div className="flex flex-1 flex-col items-center justify-center gap-5">
        <Logo className="size-28 text-neutral-400 opacity-40" strokeWidth={1.25} />
        <h1 className="text-2xl font-medium tracking-tight text-muted-foreground">Describe a chip. Get a real layout.</h1>
      </div>
      <form onSubmit={build} className="@container space-y-3" aria-labelledby="design-title">
        <h2 id="design-title" className="sr-only">Design specification</h2>
        {/* The stock group dims whenever a child is disabled; drive fade/glow from the prompt instead. */}
        <InputGroup className={cn("rounded-2xl bg-card transition-[opacity,box-shadow,border-color] duration-300 has-disabled:bg-card dark:bg-card dark:has-disabled:bg-card", spec.trim() ? "border-ring/60 shadow-[0_0_32px_-6px_oklch(1_0_0/0.18)] has-disabled:opacity-100" : "opacity-60 shadow-none has-disabled:opacity-60 focus-within:opacity-100 focus-within:has-disabled:opacity-100")}>
          <Label className="sr-only" htmlFor="design-spec">Describe your chip</Label>
          <InputGroupTextarea id="design-spec" className="min-h-28 px-4 pt-4 text-base leading-relaxed" value={spec} onChange={(event) => { setSpec(event.target.value); setSelectedPreset(undefined); setBuildError(""); }} onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) event.currentTarget.form?.requestSubmit(); }} spellCheck={false} placeholder="An 8-bit counter with enable and synchronous reset…" />
          <InputGroupAddon align="block-end" className="flex-wrap items-center gap-3 border-t px-3 pt-2.5">
            <Label htmlFor="target-clock" className="gap-1.5 text-xs font-normal text-muted-foreground">Clock
              <Input id="target-clock" type="number" min="1" max="1000" value={clock} onChange={(event) => setClock(event.target.value)} className="h-7 w-20 text-xs" aria-label="Target clock (MHz)" />MHz
            </Label>
            <div className="flex h-4 items-center gap-2 @md:border-l @md:pl-3" onClick={(event) => event.stopPropagation()}>
              <Checkbox id="fit-tile" checked={fit} onCheckedChange={(checked) => setFit(checked === true)} />
              <Label htmlFor="fit-tile" className="text-xs font-normal text-muted-foreground">Fit in one Tiny Tapeout tile</Label>
            </div>
            {/* Expert mode (Settings) only: the orchestrator stops after drafting the spec so every field can be edited. */}
            {expert ? <div className="flex h-4 items-center gap-2 @md:border-l @md:pl-3" onClick={(event) => event.stopPropagation()}>
              <Checkbox id="review-spec" checked={review} onCheckedChange={(checked) => setReview(checked === true)} />
              <Label htmlFor="review-spec" className="text-xs font-normal text-muted-foreground">Review spec before RTL</Label>
            </div> : null}
            <ModelSettings />
            {/* Collapses to an icon until there is a spec to build. */}
            <InputGroupButton type="submit" variant="default" size={spec.trim() || building ? "sm" : "icon-sm"} className="rounded-full" aria-label="Build my chip" disabled={building || !spec.trim()}>{building ? <><Spinner data-icon="inline-start" />Queuing your chip…</> : spec.trim() ? <>Build my chip<ArrowUp data-icon="inline-end" /></> : <ArrowUp />}</InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
        {buildError ? <Alert variant="destructive"><CircleAlert /><AlertDescription>{buildError}</AlertDescription></Alert> : null}
      </form>
      <section aria-labelledby="toolchain-title" className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
        <h2 id="toolchain-title" className="text-xs font-medium text-muted-foreground">Toolchain</h2>
        <dl className="flex flex-wrap items-center justify-center gap-2" aria-live="polite">
          {checks.map((check) => (
            <div className="check-row flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs" key={check.name} title={check.detail}>
              <span className={check.ready ? "size-1.5 rounded-full bg-success" : "size-1.5 rounded-full bg-muted-foreground"} aria-hidden="true" />
              <dt className="font-medium">{check.name}</dt>
              <dd className="text-muted-foreground">{check.label}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
