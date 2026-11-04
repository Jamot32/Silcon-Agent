import { Check } from "lucide-react";
import type { StageSpan } from "@/lib/run-activity";
import { cn } from "@/lib/utils";
import { duration } from "./format";

const buildStages = ["SPEC", "RTL", "VERIFY", "SYNTH", "FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE", "DONE"];

export function StageTimeline({ stage, status, spans = [], end = null, review = false }: { stage: string; status: string; spans?: StageSpan[]; end?: number | null; review?: boolean }) {
  // Expert runs wait at REVIEW between the drafted spec and RTL.
  const stages = review ? [...buildStages.slice(0, 1), "REVIEW", ...buildStages.slice(1)] : buildStages;
  const current = stages.indexOf(stage);
  return (
    <ol className="flex overflow-x-auto pt-1 pb-2" data-testid="stage-timeline" aria-label="Chip build stages">
      {stages.map((name, index) => {
        const active = name === stage;
        const complete = index < current || (status === "done" && index === current);
        const visits = spans.filter((span) => span.stage === name);
        const time = visits.reduce((sum, span) => sum + (span.end ?? end ?? span.start) - span.start, 0);
        const retried = visits.filter((span) => span.previousOk === false).length;
        return (
          <li key={name} className={cn("relative flex min-w-18 flex-1 flex-col items-center gap-1 font-mono text-[11px] text-muted-foreground", active && "text-primary", complete && !active && "text-foreground/80")} aria-current={active ? "step" : undefined}>
            {index > 0 ? <span aria-hidden="true" className={cn("absolute top-[7px] right-1/2 h-px w-full", complete || active ? "bg-muted-foreground" : "bg-border")} /> : null}
            <span className={cn("relative z-10 mb-1 grid size-3.5 place-items-center rounded-full border-[1.5px] border-muted-foreground/70 bg-background [&_svg]:size-2.5 [&_svg]:stroke-[2.4]", active && "border-primary bg-primary shadow-[0_0_0_3px_var(--background),0_0_0_4px_var(--primary)]", active && status === "running" && "animate-stage-pulse")} aria-hidden="true">{complete && !active ? <Check /> : null}</span>
            <span data-testid={active ? "stage-current" : undefined}>{name}</span>
            {visits.length && name !== "DONE" ? <span className="text-[10px] tabular-nums text-muted-foreground" title={`${visits.length} ${visits.length === 1 ? "visit" : "visits"}${retried ? `, ${retried} after a failed check` : ""}`}>{duration(time / 1000)}{visits.length > 1 ? <span className={cn("ml-1", retried && "text-destructive")}>×{visits.length}</span> : null}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
