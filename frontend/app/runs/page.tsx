import { PageIntro } from "@/components/page-intro";
import { RunHistory } from "@/components/run-history";

export default function Runs() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
      <PageIntro title="Run history." description="Every design, tool run, and result in one place." />
      <RunHistory />
    </div>
  );
}
