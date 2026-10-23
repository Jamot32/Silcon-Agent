"use client";

import { useEffect, useState } from "react";
import { getJson, type Recording } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

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
  return <span className="replay-source" data-source-run-id={source ?? undefined} title={source ?? recordingId ?? undefined}>{source ? `Source run: ${source.slice(0, 8)}` : recordingId ? `Recording: ${recordingId}${unavailable ? " · source unavailable" : ""}` : "Source recording unavailable"}</span>;
}

export function StarterNotice({ starterId }: { starterId: string | null }) {
  if (!starterId) return null;
  return <p className="starter-notice"><Badge variant="outline">Supplied faulty starter</Badge><span>The first RTL was supplied with a known UART timing bug.</span></p>;
}
