"use client";

import { useEffect, useState } from "react";
import { getSettings, type ServerSettings } from "@/lib/api";
import { factoryDefaults, loadRunDefaults, saveRunDefaults, type RunDefaults } from "@/lib/run-defaults";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ProviderConnections } from "@/components/provider-connections";

function ServerConfiguration() {
  const [settings, setSettings] = useState<ServerSettings>();
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    getSettings(controller.signal).then(setSettings, (reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Settings could not be loaded."); });
    return () => controller.abort();
  }, []);
  const rows = settings ? [
    ["Provider", settings.provider === "codex" ? "Codex" : "Meta"],
    ["Model", settings.model],
    ...(settings.reasoning_effort ? [["Reasoning effort", settings.reasoning_effort]] : []),
    ["Model calls per run", String(settings.max_calls)],
    ["Tokens per run", settings.max_tokens === null ? "Unlimited" : settings.max_tokens.toLocaleString()],
    // Codex runs on the ChatGPT plan with unknown USD cost; the budget only binds Meta calls.
    ["Budget per run", settings.provider === "codex" ? "Not applicable (cost unavailable)" : `$${settings.budget_usd.toFixed(2)}`],
  ] : [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Server configuration</CardTitle>
        <CardDescription>Read from <code>.env</code> by the API and the host worker. Edit the file and rerun <code>make dev</code> to change it.</CardDescription>
      </CardHeader>
      <CardContent aria-live="polite">
        {settings ? <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm">
          {rows.map(([label, value]) => <div key={label} className="contents"><dt className="text-muted-foreground">{label}</dt><dd className="min-w-0 break-words font-mono">{value}</dd></div>)}
        </dl> : <p className="text-sm text-muted-foreground">{error || "Loading configuration…"}</p>}
      </CardContent>
    </Card>
  );
}

function RunDefaultsForm() {
  const [clock, setClock] = useState(String(factoryDefaults.clock));
  const [fit, setFit] = useState(factoryDefaults.fit);
  const [expert, setExpert] = useState(factoryDefaults.expert);
  const [savedDefaults, setSavedDefaults] = useState(factoryDefaults);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const defaults = loadRunDefaults();
    setClock(String(defaults.clock));
    setFit(defaults.fit);
    setExpert(defaults.expert);
    setSavedDefaults(defaults);
  }, []);
  const valid = Number(clock) >= 1 && Number(clock) <= 1000;
  const dirty = Number(clock) !== savedDefaults.clock || fit !== savedDefaults.fit || expert !== savedDefaults.expert;
  const atFactoryDefaults = Number(clock) === factoryDefaults.clock && fit === factoryDefaults.fit && expert === factoryDefaults.expert;
  function edited() { setMessage(""); setError(""); }
  function setValues(defaults: RunDefaults) {
    setClock(String(defaults.clock));
    setFit(defaults.fit);
    setExpert(defaults.expert);
  }
  function persist(defaults: RunDefaults) {
    if (!saveRunDefaults(defaults)) {
      setError("Browser storage is unavailable or full. Your defaults were not saved. Allow site storage or free space, then try again.");
      setMessage("");
      return false;
    }
    setSavedDefaults(defaults);
    setError("");
    setMessage("Saved in this browser.");
    return true;
  }
  function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid || !dirty) return;
    persist({ clock: Number(clock), fit, expert });
  }
  function reset() {
    if (persist(factoryDefaults)) setValues(factoryDefaults);
  }
  return (
    <Card>
      <form onSubmit={save} className="contents" aria-labelledby="run-defaults-title">
        <CardHeader>
          <CardTitle id="run-defaults-title">Run defaults</CardTitle>
          <CardDescription>Prefill the New design form. Saved in this browser only.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="default-clock">Target clock (MHz)</Label>
            <Input id="default-clock" type="number" min="1" max="1000" step="any" value={clock} onChange={(event) => { setClock(event.target.value); edited(); }} className="w-32" aria-invalid={!valid} aria-describedby="default-clock-help" />
            <p id="default-clock-help" className={`text-xs ${valid ? "text-muted-foreground" : "text-destructive"}`}>{valid ? "Between 1 and 1000 MHz. Decimal values are supported." : "Clock must be between 1 and 1000 MHz."}</p>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="default-fit" checked={fit} onCheckedChange={(checked) => { setFit(checked === true); edited(); }} />
            <Label htmlFor="default-fit" className="font-normal">Fit in one Tiny Tapeout tile</Label>
          </div>
          <div className="flex items-start gap-2 border-t pt-4">
            <Checkbox id="default-expert" className="mt-0.5" checked={expert} onCheckedChange={(checked) => { setExpert(checked === true); edited(); }} aria-describedby="default-expert-detail" />
            <div className="grid gap-1">
              <Label htmlFor="default-expert">Expert mode</Label>
              <p id="default-expert-detail" className="text-sm text-muted-foreground">Adds a &quot;Review spec before RTL&quot; option to new builds and revisions. The orchestrator stops after drafting the DesignSpec so you can edit every field, the ports, tests and targets, plus the build settings: optimization, flow and repair limits, and synthesis strategy and density for the first flow.</p>
            </div>
          </div>
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
        </CardContent>
        <CardFooter className="flex-wrap gap-2">
          <Button type="submit" disabled={!valid || !dirty}>Save defaults</Button>
          <Button type="button" variant="outline" onClick={reset} disabled={atFactoryDefaults && !dirty}>Reset defaults</Button>
          {dirty ? <Button type="button" variant="ghost" onClick={() => { setValues(savedDefaults); edited(); }}>Undo changes</Button> : null}
          <span className="w-full text-sm text-muted-foreground" role="status">{dirty ? "Unsaved changes" : message}</span>
        </CardFooter>
      </form>
    </Card>
  );
}

export function SettingsPanel() {
  return (
    <div className="grid min-w-0 grid-cols-1 gap-6">
      <ProviderConnections />
      <RunDefaultsForm />
      <ServerConfiguration />
    </div>
  );
}
