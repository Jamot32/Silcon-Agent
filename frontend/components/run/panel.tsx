import type { ComponentProps, ReactNode } from "react";
import { Card, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/* A Card with a fixed toolbar-height header, used by the dense run dashboard panels. */
export function Panel({ id, title, aside, className, children, ...props }: { id: string; title: ReactNode; aside?: ReactNode } & ComponentProps<typeof Card>) {
  return <Card role="region" aria-labelledby={id} className={cn("min-w-0 gap-0 py-0", className)} {...props}>
    <div className="flex h-11 shrink-0 items-center justify-between gap-3 border-b px-4"><CardTitle id={id} role="heading" aria-level={2}>{title}</CardTitle>{aside}</div>
    {children}
  </Card>;
}

export function PanelEmpty({ children }: { children: ReactNode }) {
  return <p className="px-4 py-6 text-sm leading-relaxed text-muted-foreground">{children}</p>;
}
