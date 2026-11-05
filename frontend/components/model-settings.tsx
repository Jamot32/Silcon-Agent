"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSettings, type ServerSettings } from "@/lib/api";
import { ChevronDown } from "lucide-react";
import { ArkinousMark, ProviderLogo } from "@/components/provider-logo";
import { providers } from "@/lib/model-catalog";
import { OrchestratorBackground } from "@/components/orchestrator-background";
import { Button } from "@/components/ui/button";
import { InputGroupButton } from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";

// shortcut: model selections remain a preview until the worker accepts per-agent models.
// Option values are "provider/model" because one model can be offered by more than one provider.
// Taskfit (Arkinous) evaluates the task and picks the model for each role; design only, nothing evaluates yet.
const taskfit = "Arkinous/taskfit";
const agents = [
  { id: "scope", name: "Scope", detail: "Reads the spec and sets targets" },
  { id: "rtl", name: "RTL", detail: "Writes and lints Verilog" },
  { id: "verify", name: "Verify", detail: "Runs independent tests and repairs" },
  { id: "optimize", name: "Optimize", detail: "Runs sky130 flow variants" },
];
const inherit = "inherit";

function ModelOptions({ withInherit }: { withInherit?: boolean }) {
  return <SelectContent position="popper" align="end">
    {withInherit ? <><SelectItem value={inherit} className="text-xs">Same as orchestrator</SelectItem><SelectSeparator /></> : null}
    <SelectGroup>
      <SelectLabel>Arkinous</SelectLabel>
      <SelectItem value={taskfit} className="text-xs"><ArkinousMark />Taskfit<span className="ml-auto text-[10px] text-muted-foreground">Best model for the task</span></SelectItem>
    </SelectGroup>
    <SelectSeparator />
    {providers.map((provider) => <SelectGroup key={provider.name}>
      <SelectLabel>{provider.name}</SelectLabel>
      {provider.models.map((model) => <SelectItem key={model} value={`${provider.name}/${model}`} className="font-mono text-xs"><ProviderLogo provider={provider.logo} />{model}</SelectItem>)}
      {provider.unavailable?.map((model) => <SelectItem key={model.name} value={`${provider.name}/${model.name}`} disabled className="font-mono text-xs"><ProviderLogo provider={provider.logo} />{model.name}<span className="ml-auto font-sans text-[10px]">{model.reason}</span></SelectItem>)}
    </SelectGroup>)}
  </SelectContent>;
}

export function ModelSettings() {
  const [server, setServer] = useState<ServerSettings>();
  const [serverError, setServerError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    getSettings(controller.signal).then(setServer, () => { if (!controller.signal.aborted) setServerError(true); });
    return () => controller.abort();
  }, []);
  const [orchestrator, setOrchestrator] = useState(`${providers[0].name}/${providers[0].models[0]}`);
  const [agentModels, setAgentModels] = useState<Record<string, string>>({});
  const custom = agents.filter((agent) => (agentModels[agent.id] ?? inherit) !== inherit).length;
  const taskfitEverywhere = orchestrator === taskfit && custom === 0;
  return (
    <>
    {/* EXPERIMENT (revert freely): animated background keyed to the previewed orchestrator. */}
    <OrchestratorBackground kind={orchestrator === taskfit ? "arkinous" : providers.find((provider) => orchestrator.startsWith(`${provider.name}/`))?.logo} model={orchestrator} />
    <Popover>
      <PopoverTrigger asChild>
        <InputGroupButton type="button" variant="ghost" size="sm" className="ml-auto rounded-full text-muted-foreground" aria-label="Model settings">
          {server ? <ProviderLogo provider={server.provider === "meta" ? "meta" : "openai"} /> : null}<span className="max-w-44 truncate font-mono text-xs">{server?.model ?? (serverError ? "Model unavailable" : "Loading model…")}</span><ChevronDown data-icon="inline-end" />
        </InputGroupButton>
      </PopoverTrigger>
      {/* React bubbles portal clicks to the input-group addon, which would steal focus to the clock input and close this popover. */}
      <PopoverContent align="end" className="max-h-[var(--radix-popover-content-available-height)] w-[26rem] max-w-[calc(100vw-2rem)] gap-4 overflow-y-auto" aria-labelledby="models-title" onClick={(event) => event.stopPropagation()}>
        <PopoverHeader>
          <PopoverTitle id="models-title">Models</PopoverTitle>
          <PopoverDescription className="text-xs">Check your active build model and explore model assignments.</PopoverDescription>
        </PopoverHeader>
        <div className="space-y-2 rounded-lg border p-3">
          <p className="text-xs">{server ? <>Builds use <strong>{server.provider === "meta" ? "Meta" : "Codex"}</strong> · <code className="break-all">{server.model}</code>.</> : serverError ? "The build model could not be loaded. Check your server connection." : "Loading the build model…"}</p>
          <Link href="/settings" className="text-xs underline underline-offset-4">Manage accounts and API keys</Link>
        </div>
        <p className="text-xs font-medium text-muted-foreground">Preview assignments · these choices do not change builds</p>
        <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3 rounded-lg border bg-muted/40 p-3 sm:flex">
          <ArkinousMark className="size-8 shrink-0" />
          <div className="min-w-0 flex-1 space-y-0.5">
            <p className="text-sm font-medium">Taskfit <span className="text-xs font-normal text-muted-foreground">by Arkinous</span></p>
            <p className="text-xs text-muted-foreground">Planned automatic model selection for the orchestrator and each agent. Preview only.</p>
          </div>
          <Button type="button" size="sm" className="col-start-2 justify-self-start" variant={taskfitEverywhere ? "secondary" : "default"} disabled={taskfitEverywhere} onClick={() => { setOrchestrator(taskfit); setAgentModels({}); }}>{taskfitEverywhere ? "Selected" : "Preview"}</Button>
        </div>
        <div className="grid gap-2 sm:flex sm:items-center sm:justify-between sm:gap-3">
          <div className="min-w-0 flex-1 space-y-0.5"><Label htmlFor="model-orchestrator">Orchestrator</Label><p className="text-xs text-muted-foreground">Plans stages and tool calls</p></div>
          <Select value={orchestrator} onValueChange={setOrchestrator}>
            <SelectTrigger id="model-orchestrator" size="sm" className="w-full shrink-0 font-mono text-xs sm:w-52"><SelectValue /></SelectTrigger>
            <ModelOptions />
          </Select>
        </div>
        <Separator />
        <div className="space-y-3">
          <p className="text-xs font-medium text-muted-foreground">Agents</p>
          {agents.map((agent) => (
            <div key={agent.id} className="grid gap-2 sm:flex sm:items-center sm:justify-between sm:gap-3">
              <div className="min-w-0 flex-1 space-y-0.5"><Label htmlFor={`model-${agent.id}`}>{agent.name}</Label><p className="text-xs text-muted-foreground">{agent.detail}</p></div>
              <Select value={agentModels[agent.id] ?? inherit} onValueChange={(value) => setAgentModels((current) => ({ ...current, [agent.id]: value }))}>
                <SelectTrigger id={`model-${agent.id}`} size="sm" className="w-full shrink-0 text-xs sm:w-52"><SelectValue /></SelectTrigger>
                <ModelOptions withInherit />
              </Select>
            </div>
          ))}
        </div>
        <p className="rounded-md bg-muted px-2.5 py-2 text-xs text-muted-foreground">Preview: this selection is not sent to builds yet. Runs use the server-configured model.</p>
      </PopoverContent>
    </Popover>
    </>
  );
}
