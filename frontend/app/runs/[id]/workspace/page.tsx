import { CodeWorkspace } from "@/components/run/code-workspace";

export default async function WorkspacePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ view?: string; flow?: string; file?: string }> }) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  return <CodeWorkspace key={id} id={id} initialTab={query.view === "compare" ? "compare" : "edit"} initialFlow={query.flow} initialFile={typeof query.file === "string" ? query.file : undefined} />;
}
