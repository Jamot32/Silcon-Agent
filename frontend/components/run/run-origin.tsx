"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Bug, GitBranch } from "lucide-react";
import { getJson, type PublicRun, type Recording, type RunEvent } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";

export function ReplaySource({ recordingId }: { recordingId: string | null }) {
  const [source, setSource] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setSource(null);
    setUnavailable(false);
    if (recordingId) getJson<Recording[]>("/api/recordings", controller.signal).then((recordings) => {
      if (controller.signal.aborted) return;
      const recording = recordings.find((item) => item.id === recordingId);
      setSource(recording?.source_run_id ?? null);
      setUnavailable(!recording);
    }).catch(() => { if (!controller.signal.aborted) setUnavailable(true); });
    return () => controller.abort();
  }, [recordingId]);
  return <span className="text-primary/80" data-source-run-id={source ?? undefined} title={source ?? recordingId ?? undefined}>{source ? `Source run: ${source.slice(0, 8)}` : recordingId ? `Recording: ${recordingId}${unavailable ? " · source unavailable" : ""}` : "Source recording unavailable"}</span>;
}

export function StarterNotice({ starterId }: { starterId: string | null }) {
  if (!starterId) return null;
  return <Alert><Bug /><AlertDescription><span className="font-medium text-foreground">Supplied faulty starter.</span> The first RTL was supplied with a known UART timing bug.</AlertDescription></Alert>;
}

export function RevisionNotice({ run, events, ended }: { run: Pick<PublicRun, "parent_run_id" | "carried_files">; events: RunEvent[]; ended: boolean }) {
  if (!run.parent_run_id) return null;
  const files = run.carried_files.join(", ");
  // carried_files is what was requested at queue time; only the orchestrator's marker note shows what happened.
  const outcome = events.findLast((event) => event.type === "note" && (event.payload.carry_over === "loaded" || event.payload.carry_over === "skipped"));
  const text = !files ? "No RTL was carried over from it."
    : outcome?.payload.carry_over === "loaded" ? `Started from its RTL (${files}); tests are written fresh from this request.`
    : outcome && typeof outcome.payload.text === "string" ? `Its RTL was not used. ${outcome.payload.text}`
    : ended ? `Ended before its RTL (${files}) was loaded.` : `Will start from its RTL (${files}).`;
  return <Alert role="note" data-testid="revision-notice"><GitBranch /><AlertDescription>
    <p><span className="font-medium text-foreground">Follows run <Link href={`/runs/${run.parent_run_id}`} className="font-mono">{run.parent_run_id.slice(0, 8)}</Link>.</span> {text}</p>
  </AlertDescription></Alert>;
}
