"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Recording } from "@/lib/api";
import { duration } from "@/components/run/format";

export function RecordedRuns({ recordings, unavailable, pending, disabled, error, onReplay }: { recordings: Recording[] | null; unavailable: boolean; pending: string | null; disabled: boolean; error: string; onReplay: (id: string, speed: 1 | 4) => void }) {
  return <section className="panel recordings-panel" aria-labelledby="recordings-title">
    <h2 id="recordings-title">Recorded runs</h2>
    {recordings?.length ? <><p className="recordings-explanation">Replay real recorded tool runs. Playback makes no new model or EDA calls.</p><ul className="recording-list">{recordings.map((recording) => <li className="recording-row" key={recording.id} data-recording-id={recording.id} data-source-run-id={recording.source_run_id}>
      <div className="recording-description"><h3>{recording.name}<Badge variant="outline" className="replay-badge">REPLAY</Badge></h3><p>{recording.description}</p><div className="recording-meta"><span>Original duration {duration(recording.duration_seconds)}</span><span>{recording.flow_count} physical runs</span><span title={recording.source_run_id}>Source run {recording.source_run_id.slice(0, 8)}</span></div></div>
      <div className="recording-actions">{([1, 4] as const).map((speed) => <Button key={speed} type="button" variant="outline" disabled={disabled || pending !== null} onClick={() => onReplay(recording.id, speed)} aria-label={`Replay ${recording.name} at ${speed}×`}>{pending === `${recording.id}:${speed}` ? "Queuing…" : `Replay ${speed}×`}</Button>)}</div>
    </li>)}</ul></> : <div className="empty-state" aria-live="polite">{unavailable ? <><h3>Recordings could not be loaded.</h3><p>Check the API connection and reload this page.</p></> : recordings === null ? <><h3>Checking recorded runs…</h3><p>Only recordings from real tool runs appear here.</p></> : <><h3>No real recordings yet.</h3><p>Recorded runs appear after a real tool run is exported.</p></>}</div>}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </section>;
}
