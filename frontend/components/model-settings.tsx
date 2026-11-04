"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { ArkinousMark, ProviderLogo } from "@/components/provider-logo";
import { providers } from "@/lib/model-catalog";
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
function ModelLogo({ value }: { value: string }) {
  if (value === taskfit) return <ArkinousMark />;
  return <ProviderLogo provider={providers.find((provider) => value.startsWith(`${provider.name}/`))?.logo ?? "openai"} />;
}
const labelOf = (value: string) => value === taskfit ? "Taskfit" : value.slice(value.indexOf("/") + 1);
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
  const [orchestrator, setOrchestrator] = useState(`${providers[0].name}/${providers[0].models[0]}`);
  const [agentModels, setAgentModels] = useState<Record<string, string>>({});
  const custom = agents.filter((agent) => (agentModels[agent.id] ?? inherit) !== inherit).length;
  const taskfitEverywhere = orchestrator === taskfit && custom === 0;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <InputGroupButton type="button" variant="ghost" size="sm" className="ml-auto rounded-full text-muted-foreground" aria-label="Model settings">
          <ModelLogo value={orchestrator} /><span className={orchestrator === taskfit ? "text-xs" : "font-mono text-xs"}>{labelOf(orchestrator)}</span>{custom ? <span className="text-xs">+{custom}</span> : null}<ChevronDown data-icon="inline-end" />
        </InputGroupButton>
      </PopoverTrigger>
      {/* React bubbles portal clicks to the input-group addon, which would steal focus to the clock input and close this popover. */}
      <PopoverContent align="end" className="w-[26rem] gap-4" onClick={(event) => event.stopPropagation()}>
        <PopoverHeader>
          <PopoverTitle>Models</PopoverTitle>
          <PopoverDescription className="text-xs">The orchestrator plans the run; each stage agent can use its own model.</PopoverDescription>
        </PopoverHeader>
        <div className="flex items-center gap-3 rounded-lg border bg-muted/40 p-3">
          <ArkinousMark className="size-8 shrink-0" />
          <div className="min-w-0 flex-1 space-y-0.5">
            <p className="text-sm font-medium">Taskfit <span className="text-xs font-normal text-muted-foreground">by Arkinous</span></p>
            <p className="text-xs text-muted-foreground">Evaluates the task and assigns the best model to the orchestrator and every agent.</p>
          </div>
          <Button type="button" size="sm" variant={taskfitEverywhere ? "secondary" : "default"} disabled={taskfitEverywhere} onClick={() => { setOrchestrator(taskfit); setAgentModels({}); }}>{taskfitEverywhere ? "On" : "Use"}</Button>
        </div>
        <div className="flex items-center justify-between gap-3">
          <div className="space-y-0.5"><Label htmlFor="model-orchestrator">Orchestrator</Label><p className="text-xs text-muted-foreground">Plans stages and tool calls</p></div>
          <Select value={orchestrator} onValueChange={setOrchestrator}>
            <SelectTrigger id="model-orchestrator" size="sm" className="w-52 shrink-0 font-mono text-xs"><SelectValue /></SelectTrigger>
            <ModelOptions />
          </Select>
        </div>
        <Separator />
        <div className="space-y-3">
          <p className="text-xs font-medium text-muted-foreground">Agents</p>
          {agents.map((agent) => (
            <div key={agent.id} className="flex items-center justify-between gap-3">
              <div className="space-y-0.5"><Label htmlFor={`model-${agent.id}`}>{agent.name}</Label><p className="text-xs text-muted-foreground">{agent.detail}</p></div>
              <Select value={agentModels[agent.id] ?? inherit} onValueChange={(value) => setAgentModels((current) => ({ ...current, [agent.id]: value }))}>
                <SelectTrigger id={`model-${agent.id}`} size="sm" className="w-52 shrink-0 text-xs"><SelectValue /></SelectTrigger>
                <ModelOptions withInherit />
              </Select>
            </div>
          ))}
        </div>
        <p className="rounded-md bg-muted px-2.5 py-2 text-xs text-muted-foreground">Preview: this selection is not sent to builds yet. Runs use the server-configured model.</p>
      </PopoverContent>
    </Popover>
  );
}
