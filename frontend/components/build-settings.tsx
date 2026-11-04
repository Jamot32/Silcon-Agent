"use client";

import { useId } from "react";
import { buildSettingsError, synthesisStrategies, type BuildSettingsDraft } from "@/lib/build-settings";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";

export function BuildSettings({ value, onChange, disabled = false }: { value: BuildSettingsDraft; onChange: (draft: BuildSettingsDraft) => void; disabled?: boolean }) {
  const id = useId();
  const error = buildSettingsError(value);
  const edit = (patch: Partial<BuildSettingsDraft>) => onChange({ ...value, ...patch });
  return <fieldset disabled={disabled} className="space-y-4 rounded-lg border p-3" aria-describedby={`${id}-help${error ? ` ${id}-error` : ""}`}>
    <legend className="px-1 text-sm font-medium">Flow configuration</legend>
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="grid gap-1.5"><Label htmlFor={`${id}-attempts`} className="text-xs">Flow attempts (1–6)</Label><Input id={`${id}-attempts`} type="number" min="1" max="6" step="1" required value={value.attempts} onChange={(event) => edit({ attempts: event.target.value })} /></div>
      <div className="grid gap-1.5"><Label htmlFor={`${id}-repairs`} className="text-xs">RTL repair loops (0–5)</Label><Input id={`${id}-repairs`} type="number" min="0" max="5" step="1" required value={value.repairs} onChange={(event) => edit({ repairs: event.target.value })} /></div>
    </div>
    <div className="flex items-start gap-2"><Checkbox id={`${id}-optimize`} className="mt-0.5" checked={value.optimize} disabled={disabled} onCheckedChange={(checked) => edit({ optimize: checked === true })} /><Label htmlFor={`${id}-optimize`} className="text-xs font-normal leading-relaxed">Compare optimization variants after the first layout</Label></div>
    {value.optimize && Number(value.attempts) === 1 ? <p className="text-xs text-muted-foreground">One flow attempt leaves no budget for a physical comparison.</p> : null}
    <div className="grid gap-1.5"><Label htmlFor={`${id}-strategy`} className="text-xs">Initial synthesis strategy</Label><NativeSelect id={`${id}-strategy`} className="w-full" value={value.strategy} onChange={(event) => edit({ strategy: event.target.value })}><NativeSelectOption value="">Planner default</NativeSelectOption>{synthesisStrategies.map((strategy) => <NativeSelectOption key={strategy} value={strategy}>{strategy}</NativeSelectOption>)}</NativeSelect><p className="text-xs text-muted-foreground">Choose a synthesis recipe to explore area or delay. The resulting trade-off must be measured.</p></div>
    <div className="grid grid-cols-2 gap-3">
      <div className="grid gap-1.5"><Label htmlFor={`${id}-utilization`} className="text-xs">Core utilization (%)</Label><Input id={`${id}-utilization`} type="number" min="1" max="90" step="any" value={value.utilization} placeholder="Planner" onChange={(event) => edit({ utilization: event.target.value })} /></div>
      <div className="grid gap-1.5"><Label htmlFor={`${id}-density`} className="text-xs">Placement density (%)</Label><Input id={`${id}-density`} type="number" min="1" max="90" step="any" value={value.density} placeholder="Planner" onChange={(event) => edit({ density: event.target.value })} /></div>
    </div>
    <p id={`${id}-help`} className="text-xs leading-relaxed text-muted-foreground">These knobs seed the first layout and re-measured RTL edits. Optimizer proposals may change them. Clock comes from your target; the planner sizes the die. Timing, electrical checks, and verification remain required.</p>
    {error ? <p id={`${id}-error`} role="alert" className="text-xs text-destructive">{error}</p> : null}
  </fieldset>;
}
