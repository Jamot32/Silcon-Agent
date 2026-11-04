"use client";

import { Search, X } from "lucide-react";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";

export function RunSearchInput({ value, onChange, label, placeholder }: { value: string; onChange: (value: string) => void; label: string; placeholder: string }) {
  return <InputGroup className="max-w-md">
    <InputGroupInput type="search" value={value} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape" && value) { event.preventDefault(); onChange(""); } }} aria-label={label} placeholder={placeholder} autoComplete="off" spellCheck={false} className="[&::-webkit-search-cancel-button]:appearance-none" />
    <InputGroupAddon><Search /></InputGroupAddon>
    {value ? <InputGroupAddon align="inline-end"><InputGroupButton aria-label="Clear search" size="icon-xs" onClick={() => onChange("")}><X /></InputGroupButton></InputGroupAddon> : null}
  </InputGroup>;
}
