"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CircleAlert, Play } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Item, ItemActions, ItemContent, ItemDescription, ItemFooter, ItemGroup, ItemTitle } from "@/components/ui/item";
import { createReplay, getJson, type Recording } from "@/lib/api";
import { matchesSearch, recordingSearchFields } from "@/lib/run-search";
import { RunSearchInput } from "@/components/run-search-input";
import { ReplayBadge } from "@/components/run/badges";
import { duration } from "@/components/run/format";

export function RecordedRuns() {
  const router = useRouter();
  const [recordings, setRecordings] = useState<Recording[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    getJson<Recording[]>("/api/recordings", controller.signal).then(setRecordings, () => { if (!controller.signal.aborted) setUnavailable(true); });
    return () => controller.abort();
  }, []);
  async function onReplay(recordingId: string, speed: 1 | 4) {
    if (pending) return;
    setPending(`${recordingId}:${speed}`);
    setError("");
    try {
      const result = await createReplay({ recording_id: recordingId, speed });
      router.push(`/runs/${result.run_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The replay could not be queued.");
      setPending(null);
    }
  }
  const searching = query.trim() !== "";
  const shown = recordings && searching ? recordings.filter((recording) => matchesSearch(query, recordingSearchFields(recording))) : recordings;
  return <section className="space-y-3" aria-label="Recorded runs">
    {recordings?.length ? <>
      <RunSearchInput value={query} onChange={setQuery} label="Search recordings" placeholder="Search by name, keyword, or source run ID" />
      {searching ? <p role="status" className="text-sm text-muted-foreground">{shown?.length ?? 0} of {recordings.length} recording{recordings.length === 1 ? "" : "s"} match.</p> : null}
    </> : null}
    {shown?.length ? <ItemGroup className="gap-2">{shown.map((recording) => <Item key={recording.id} variant="outline" data-recording-id={recording.id} data-source-run-id={recording.source_run_id}>
      <ItemContent className="min-w-0 basis-72">
        <ItemTitle role="heading" aria-level={2} className="flex-wrap">{recording.name}<ReplayBadge>REPLAY</ReplayBadge></ItemTitle>
        <ItemDescription className="line-clamp-none">{recording.description}</ItemDescription>
      </ItemContent>
      <ItemActions>{([1, 4] as const).map((speed) => <Button key={speed} type="button" size="sm" variant="outline" disabled={pending !== null} onClick={() => { void onReplay(recording.id, speed); }} aria-label={`Replay ${recording.name} at ${speed}×`}><Play data-icon="inline-start" />{pending === `${recording.id}:${speed}` ? "Queuing…" : `Replay ${speed}×`}</Button>)}</ItemActions>
      <ItemFooter className="justify-start gap-x-4 text-xs text-muted-foreground"><span>Original duration {duration(recording.duration_seconds)}</span><span>{recording.flow_count} physical runs</span><span title={recording.source_run_id} className="font-mono">Source run {recording.source_run_id.slice(0, 8)}</span></ItemFooter>
    </Item>)}</ItemGroup> : searching && recordings?.length ? <Empty className="border border-dashed" aria-live="polite"><EmptyHeader><EmptyTitle role="heading" aria-level={2}>No recordings match “{query.trim()}”.</EmptyTitle><EmptyDescription>Search matches recording names, descriptions, and IDs.</EmptyDescription></EmptyHeader><EmptyContent><Button type="button" variant="outline" onClick={() => setQuery("")}>Clear search</Button></EmptyContent></Empty> : <Empty className="border border-dashed" aria-live="polite"><EmptyHeader>{unavailable ? <><EmptyTitle role="heading" aria-level={2}>Recordings could not be loaded.</EmptyTitle><EmptyDescription>Check the API connection and reload this page.</EmptyDescription></> : recordings === null ? <><EmptyTitle role="heading" aria-level={2}>Checking recorded runs…</EmptyTitle><EmptyDescription>Only recordings from real tool runs appear here.</EmptyDescription></> : <><EmptyTitle role="heading" aria-level={2}>No real recordings yet.</EmptyTitle><EmptyDescription>Recorded runs appear after a real tool run is exported.</EmptyDescription></>}</EmptyHeader></Empty>}
    {error ? <Alert variant="destructive"><CircleAlert /><AlertDescription>{error}</AlertDescription></Alert> : null}
  </section>;
}
