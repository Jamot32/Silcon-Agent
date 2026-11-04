"use client";

import { useEffect, useState } from "react";
import { getSettings, type ServerSettings } from "@/lib/api";
import { factoryDefaults, loadRunDefaults, saveRunDefaults } from "@/lib/run-defaults";
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
        {settings ? <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          {rows.map(([label, value]) => <div key={label} className="contents"><dt className="text-muted-foreground">{label}</dt><dd className="font-mono">{value}</dd></div>)}
        </dl> : <p className="text-sm text-muted-foreground">{error || "Loading configuration…"}</p>}
      </CardContent>
    </Card>
  );
}

function RunDefaultsForm() {
  const [clock, setClock] = useState(String(factoryDefaults.clock));
  const [fit, setFit] = useState(factoryDefaults.fit);
  const [expert, setExpert] = useState(factoryDefaults.expert);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const defaults = loadRunDefaults();
    setClock(String(defaults.clock));
    setFit(defaults.fit);
    setExpert(defaults.expert);
  }, []);
  const valid = Number(clock) >= 1 && Number(clock) <= 1000;
  function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    saveRunDefaults({ clock: Number(clock), fit, expert });
    setSaved(true);
  }
  function reset() {
    saveRunDefaults(factoryDefaults);
    setClock(String(factoryDefaults.clock));
    setFit(factoryDefaults.fit);
    setExpert(factoryDefaults.expert);
    setSaved(true);
  }
  return (
    <Card>
      <form onSubmit={save} className="contents">
        <CardHeader>
          <CardTitle>Run defaults</CardTitle>
          <CardDescription>Prefill the New design form. Saved in this browser only.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="default-clock">Target clock (MHz)</Label>
            <Input id="default-clock" type="number" min="1" max="1000" step="any" value={clock} onChange={(event) => { setClock(event.target.value); setSaved(false); }} className="w-32" aria-invalid={!valid} />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="default-fit" checked={fit} onCheckedChange={(checked) => { setFit(checked === true); setSaved(false); }} />
            <Label htmlFor="default-fit" className="font-normal">Fit in one Tiny Tapeout tile</Label>
          </div>
          <div className="flex items-start gap-2 border-t pt-4">
            <Checkbox id="default-expert" className="mt-0.5" checked={expert} onCheckedChange={(checked) => { setExpert(checked === true); setSaved(false); }} aria-describedby="default-expert-detail" />
            <div className="grid gap-1">
              <Label htmlFor="default-expert">Expert mode</Label>
              <p id="default-expert-detail" className="text-sm text-muted-foreground">Adds a &quot;Review spec before RTL&quot; option to new builds and revisions. The orchestrator stops after drafting the DesignSpec so you can edit every field, the ports, tests and targets, plus the build settings: optimization, flow and repair limits, and synthesis strategy and density for the first flow.</p>
            </div>
          </div>
        </CardContent>
        <CardFooter className="gap-2">
          <Button type="submit" disabled={!valid}>Save defaults</Button>
          <Button type="button" variant="outline" onClick={reset}>Reset</Button>
          <span className="text-sm text-muted-foreground" aria-live="polite">{saved ? "Saved." : valid ? "" : "Clock must be between 1 and 1000 MHz."}</span>
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
