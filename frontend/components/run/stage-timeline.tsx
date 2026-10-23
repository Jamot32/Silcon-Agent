import { Check } from "lucide-react";

const stages = ["SPEC", "RTL", "VERIFY", "SYNTH", "FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE", "DONE"];

export function StageTimeline({ stage, status }: { stage: string; status: string }) {
  const current = stages.indexOf(stage);
  return (
    <ol className="stage-timeline" data-testid="stage-timeline" aria-label="Chip build stages">
      {stages.map((name, index) => {
        const active = name === stage;
        const complete = index < current || (status === "done" && index === current);
        return (
          <li key={name} className={active ? "stage active" : complete ? "stage complete" : "stage"} aria-current={active ? "step" : undefined}>
            <span className={active && status === "running" ? "stage-node running" : "stage-node"} aria-hidden="true">{complete && !active ? <Check /> : null}</span>
            <span data-testid={active ? "stage-current" : undefined}>{name}</span>
          </li>
        );
      })}
    </ol>
  );
}
