import { RunResult } from "@/components/run/run-result";

export default async function ResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RunResult id={id} />;
}
