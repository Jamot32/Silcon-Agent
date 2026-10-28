import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

const stages = ["SPEC", "RTL", "VERIFY", "SYNTH", "FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE", "DONE"];

export function StageTimeline({ stage, status }: { stage: string; status: string }) {
  const current = stages.indexOf(stage);
  return (
    <ol className="flex overflow-x-auto pt-1 pb-2" data-testid="stage-timeline" aria-label="Chip build stages">
      {stages.map((name, index) => {
        const active = name === stage;
        const complete = index < current || (status === "done" && index === current);
        return (
          <li key={name} className={cn("relative flex min-w-18 flex-1 flex-col items-center gap-2 font-mono text-[11px] text-muted-foreground", active && "text-primary", complete && !active && "text-foreground/80")} aria-current={active ? "step" : undefined}>
            {index > 0 ? <span aria-hidden="true" className={cn("absolute top-[7px] right-1/2 h-px w-full", complete || active ? "bg-muted-foreground" : "bg-border")} /> : null}
            <span className={cn("relative z-10 grid size-3.5 place-items-center rounded-full border-[1.5px] border-muted-foreground/70 bg-background [&_svg]:size-2.5 [&_svg]:stroke-[2.4]", active && "border-primary bg-primary shadow-[0_0_0_3px_var(--background),0_0_0_4px_var(--primary)]", active && status === "running" && "animate-stage-pulse")} aria-hidden="true">{complete && !active ? <Check /> : null}</span>
            <span data-testid={active ? "stage-current" : undefined}>{name}</span>
          </li>
        );
      })}
    </ol>
  );
}
