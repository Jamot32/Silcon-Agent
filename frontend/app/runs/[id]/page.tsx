import { RunDashboard } from "@/components/run/run-dashboard";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RunDashboard id={id} />;
}
