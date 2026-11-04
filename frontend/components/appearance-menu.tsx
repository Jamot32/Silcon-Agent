"use client";

import { useState } from "react";
import { Check, Palette } from "lucide-react";
import { cn } from "cn";
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
import { useAppearance } from "@/hooks/use-appearance";
import { saveAppearance, type Appearance } from "@/lib/appearance";

const modes: { label: string; value: Appearance }[] = [
  { label: "Dark, monochrome", value: { scheme: "dark", palette: "mono" } },
  { label: "Light, monochrome", value: { scheme: "light", palette: "mono" } },
  { label: "Dark, color", value: { scheme: "dark", palette: "color" } },
  { label: "Light, color", value: { scheme: "light", palette: "color" } },
];

// Swatch dots echo the provider-logo palette: neutral greys, or brand hues (Meta, Gemini, Mistral).
function Swatch({ value }: { value: Appearance }) {
  const dots = value.palette === "color" ? ["#0081FB", "#3186FF", "#FA500F"] : value.scheme === "dark" ? ["#FAFAFA", "#A3A3A3", "#737373"] : ["#171717", "#525252", "#A3A3A3"];
  return <span aria-hidden="true" className={cn("flex h-7 w-11 shrink-0 items-center justify-center gap-1 rounded-md ring-1 ring-foreground/15", value.scheme === "dark" ? "bg-[#171717]" : "bg-white")}>
    {dots.map((color) => <span key={color} className="size-1.5 rounded-full" style={{ backgroundColor: color }} />)}
  </span>;
}

export function AppearanceMenu() {
  const current = useAppearance();
  const [storageBlocked, setStorageBlocked] = useState(false);
  const active = modes.find(({ value }) => value.scheme === current.scheme && value.palette === current.palette)!;
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <Popover>
          <PopoverTrigger asChild>
            <SidebarMenuButton tooltip="Appearance" aria-label={`Appearance: ${active.label}`}><Palette />Appearance</SidebarMenuButton>
          </PopoverTrigger>
          <PopoverContent side="right" align="end" className="w-64">
            <PopoverHeader><PopoverTitle>Appearance</PopoverTitle><PopoverDescription>Color modes show provider logos in their brand colors.</PopoverDescription></PopoverHeader>
            <div role="radiogroup" aria-label="Appearance mode" className="flex flex-col gap-1">
              {modes.map(({ label, value }) => {
                const checked = value === active.value;
                return <label key={label} className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 hover:bg-accent has-focus-visible:outline-2 has-focus-visible:outline-ring">
                  <input type="radio" name="appearance" className="sr-only" checked={checked} onChange={() => setStorageBlocked(!saveAppearance(value))} />
                  <Swatch value={value} />
                  <span className="flex-1">{label}</span>
                  {checked ? <Check className="size-4" aria-hidden="true" /> : null}
                </label>;
              })}
            </div>
            {storageBlocked ? <p role="status" className="text-xs text-muted-foreground">Browser storage is blocked; this mode lasts until the page reloads.</p> : null}
          </PopoverContent>
        </Popover>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
