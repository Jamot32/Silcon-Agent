import { PageIntro } from "@/components/page-intro";
import { SettingsPanel } from "@/components/settings-panel";

export default function Settings() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
      <PageIntro title="Settings." description="Connect model accounts, manage API keys, and set defaults for new designs." />
      <SettingsPanel />
    </div>
  );
}
