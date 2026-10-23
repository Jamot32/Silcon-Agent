"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Circle, LoaderCircle, X } from "lucide-react";
import type { RunEvent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { title } from "./format";

const visibleTypes = new Set(["stage_changed", "tool_started", "tool_finished", "file_written", "test_result", "metric_recorded", "layout_rendered", "note", "error", "run_finished"]);

function description(event: RunEvent): string {
  const p = event.payload;
  if (event.type === "note") return typeof p.text === "string" ? p.text : "Design note";
  if (event.type === "stage_changed") return `${String(p.stage ?? "Stage")} stage started`;
  if (event.type === "file_written") return `Wrote ${String(p.path ?? "file")}`;
  if (event.type === "test_result") return typeof p.passed === "number" && typeof p.failed === "number" ? `${p.passed} tests passed · ${p.failed} failed` : String(p.error ?? p.first_error ?? "Test execution failed");
  if (event.type === "metric_recorded") return `Recorded physical results · ${String(p.run_tag ?? "")}`;
  if (event.type === "layout_rendered") return `Rendered layout · ${String(p.run_tag ?? "")}`;
  if (event.type === "error") return String(p.error ?? p.message ?? "The run encountered an error.");
  if (event.type === "run_finished") return String(p.summary ?? p.error ?? "Run finished");
  const tool = typeof p.tool === "string" ? p.tool : "Tool";
  const result = p.result && typeof p.result === "object" && !Array.isArray(p.result) ? p.result : null;
  return `${title(tool)} ${event.type === "tool_started" ? "started" : result?.ok === false ? "failed" : "finished"}`;
}

function tone(event: RunEvent): "pass" | "fail" | "working" | "neutral" {
  if (event.type === "error" || (event.type === "test_result" && event.payload.ok === false)) return "fail";
  if (event.type === "tool_finished") {
    const result = event.payload.result;
    return result && typeof result === "object" && !Array.isArray(result) && result.ok === false ? "fail" : "pass";
  }
  if (event.type === "test_result") return event.payload.ok === true ? "pass" : "neutral";
  if (event.type === "tool_started") return "working";
  return "neutral";
}

export function AgentLog({ events }: { events: RunEvent[] }) {
  const rows = useMemo(() => events.filter((event) => visibleTypes.has(event.type)), [events]);
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const [hasNew, setHasNew] = useState(false);
  useEffect(() => {
    const element = scroller.current;
    if (element && pinned.current) element.scrollTop = element.scrollHeight;
    else if (element) setHasNew(true);
  }, [rows.length]);
  function latest() {
    const element = scroller.current;
    if (element) element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    pinned.current = true;
    setHasNew(false);
  }
  return (
    <section className="instrument-panel log-panel" aria-labelledby="agent-log-title">
      <header className="instrument-header"><h2 id="agent-log-title">Agent log</h2><span className="micro-label">{rows.length} events</span></header>
      <div className="event-log" data-testid="event-log" data-last-event-id={events.at(-1)?.id ?? 0} data-event-count={events.length} ref={scroller} onScroll={() => {
        const element = scroller.current;
        if (element) {
          pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 60;
          if (pinned.current) setHasNew(false);
        }
      }} role="log" aria-label="Agent design log" aria-live="polite" aria-relevant="additions">
        {rows.length === 0 ? <p className="panel-empty">Waiting for the worker to start.</p> : (
          <ol>{rows.map((event) => {
            const state = tone(event);
            return <li key={event.id} className={`log-entry ${state}`} data-event-id={event.id}>
              <span className="log-node" aria-hidden="true">{state === "pass" ? <Check /> : state === "fail" ? <X /> : state === "working" ? <LoaderCircle /> : <Circle />}</span>
              <div><time dateTime={event.ts}>{new Date(event.ts).toLocaleTimeString("en-US", { hour12: false })}</time><p>{description(event)}</p>
                {event.type === "tool_finished" || event.type === "error" ? <details><summary>Tool details</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details> : null}
              </div>
            </li>;
          })}</ol>
        )}
      </div>
      {hasNew ? <Button variant="secondary" size="sm" className="new-events-button" onClick={latest}>Latest events <ChevronDown data-icon="inline-end" /></Button> : null}
    </section>
  );
}
