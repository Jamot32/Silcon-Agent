import { PageIntro } from "@/components/page-intro";
import { RecordedRuns } from "@/components/recorded-runs";

export default function Recordings() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
      <PageIntro title="Recorded runs." description="Replay committed recordings of real tool runs. Playback makes no new model or EDA calls." />
      <RecordedRuns />
    </div>
  );
}
