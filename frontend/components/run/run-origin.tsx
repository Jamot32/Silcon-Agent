"use client";

import { useEffect, useState } from "react";
import { Bug } from "lucide-react";
import { getJson, type Recording } from "@/lib/api";
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
