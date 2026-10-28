import type { ComponentProps } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { title } from "./format";

export function ReplayBadge({ className, ...props }: ComponentProps<typeof Badge>) {
  return <Badge variant="outline" className={cn("border-primary/40 tracking-wider text-primary", className)} {...props} />;
}

export function StatusBadge({ status, className, ...props }: { status: string } & ComponentProps<typeof Badge>) {
  const tone = status === "done" ? "bg-success/15 text-success" : status === "failed" ? "bg-destructive/15 text-destructive" : status === "running" ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground";
  return <Badge variant="secondary" className={cn(tone, className)} {...props}>{title(status)}</Badge>;
}

export const signalText = { pass: "text-success", fail: "text-destructive", neutral: "text-muted-foreground" } as const;
