"use client";

import { useMemo } from "react";
import { Check, CircleAlert, FileCode, FlaskConical, Gauge, Layers, Wrench } from "lucide-react";
import type { RunEvent } from "@/lib/api";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { Message, MessageContent } from "@/components/ui/message";
import { MessageScroller, MessageScrollerButton, MessageScrollerContent, MessageScrollerItem, MessageScrollerProvider, MessageScrollerViewport } from "@/components/ui/message-scroller";
import { Spinner } from "@/components/ui/spinner";
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceDescription, TraceIcon, TraceLine, TraceTitle } from "@/components/ui/trace";
import { cn } from "@/lib/utils";
import { title } from "./format";
import { Panel } from "./panel";

const visibleTypes = new Set(["stage_changed", "tool_started", "tool_finished", "file_written", "test_result", "metric_recorded", "layout_rendered", "note", "error", "run_finished"]);
const traceTypes = new Set(["tool_started", "tool_finished", "file_written", "test_result", "metric_recorded", "layout_rendered"]);

type Block = { kind: "trace"; events: RunEvent[] } | { kind: "single"; event: RunEvent };

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
  return `${title(tool)} ${event.type === "tool_started" ? "running" : result?.ok === false ? "failed" : "finished"}`;
}

function failed(event: RunEvent): boolean {
  const result = event.payload.result;
  if (event.type === "tool_finished") return !!result && typeof result === "object" && !Array.isArray(result) && result.ok === false;
  return event.type === "test_result" && event.payload.ok === false;
}

const icons: Record<string, typeof Wrench> = { file_written: FileCode, test_result: FlaskConical, metric_recorded: Gauge, layout_rendered: Layers };
const time = (event: RunEvent) => new Date(event.ts).toLocaleTimeString("en-US", { hour12: false });

function TraceEvent({ event, running }: { event: RunEvent; running: boolean }) {
  const Icon = icons[event.type] ?? Wrench;
  const status = running ? "running" : failed(event) ? "error" : undefined;
  const line = <TraceLine status={status} data-event-id={event.id}>
    <TraceIcon>{running ? <Spinner /> : <Icon />}</TraceIcon>
    <TraceTitle className="font-mono text-xs">{description(event)}</TraceTitle>
    <TraceDescription className="font-mono text-[11px]"><time dateTime={event.ts}>{time(event)}</time></TraceDescription>
  </TraceLine>;
  if (event.type !== "tool_finished") return line;
  return <TraceCollapsible>
    <TraceCollapsibleTrigger aria-label={`Tool details: ${description(event)}`}>{line}</TraceCollapsibleTrigger>
    <TraceCollapsibleContent><pre className="max-h-60 overflow-auto font-mono text-[10px] leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(event.payload, null, 2)}</pre></TraceCollapsibleContent>
  </TraceCollapsible>;
}

export function AgentLog({ events, spec, title: heading = "Agent log", className }: { events: RunEvent[]; spec?: string; title?: string; className?: string }) {
  const rows = useMemo(() => events.filter((event) => visibleTypes.has(event.type)), [events]);
  const blocks = useMemo(() => {
    // A started tool is shown only until its matching finish arrives (paired by tool_call_id).
    const finishedCalls = new Set(rows.flatMap((event) => event.type === "tool_finished" && typeof event.payload.tool_call_id === "string" ? [event.payload.tool_call_id] : []));
    const result: Block[] = [];
    for (const event of rows) {
      if (event.type === "tool_started" && finishedCalls.has(String(event.payload.tool_call_id))) continue;
      const last = result.at(-1);
      if (!traceTypes.has(event.type)) result.push({ kind: "single", event });
      else if (last?.kind === "trace") last.events.push(event);
      else result.push({ kind: "trace", events: [event] });
    }
    return result;
  }, [rows]);
  const ended = rows.some((event) => event.type === "run_finished");
  return (
    <Panel id="agent-log-title" title={heading} aside={<span className="text-xs text-muted-foreground">{rows.length} events</span>} className={cn("flex flex-col", className)}>
      <MessageScrollerProvider autoScroll defaultScrollPosition="end">
        <MessageScroller className="min-h-0 flex-1">
          <MessageScrollerViewport className="px-4 py-4" data-testid="event-log" data-last-event-id={events.at(-1)?.id ?? 0} data-event-count={events.length} role="log" aria-label="Agent design log" aria-live="polite" aria-relevant="additions">
            <MessageScrollerContent className="gap-4">
              {spec ? <MessageScrollerItem><Message align="end"><MessageContent><Bubble align="end"><BubbleContent className="whitespace-pre-wrap">{spec}</BubbleContent></Bubble></MessageContent></Message></MessageScrollerItem> : null}
              {rows.length === 0 ? <MessageScrollerItem><Trace><TraceLine status="running"><TraceIcon><Spinner /></TraceIcon><TraceTitle>Waiting for the worker to start.</TraceTitle></TraceLine></Trace></MessageScrollerItem> : null}
              {blocks.map((block) => {
                if (block.kind === "trace") return <MessageScrollerItem key={block.events[0].id}><Trace>{block.events.map((event) => <TraceEvent key={event.id} event={event} running={event.type === "tool_started" && !ended} />)}</Trace></MessageScrollerItem>;
                const { event } = block;
                if (event.type === "stage_changed" || event.type === "run_finished") return <MessageScrollerItem key={event.id}>
                  <Marker variant={event.type === "stage_changed" ? "separator" : "default"} data-event-id={event.id} title={typeof event.payload.goal === "string" ? event.payload.goal : undefined}>
                    {event.type === "run_finished" ? <MarkerIcon>{event.payload.status === "done" ? <Check className="text-success" /> : <CircleAlert className="text-destructive" />}</MarkerIcon> : null}
                    <MarkerContent className="font-mono text-xs">{description(event)} · <time dateTime={event.ts}>{time(event)}</time></MarkerContent>
                  </Marker>
                </MessageScrollerItem>;
                return <MessageScrollerItem key={event.id}><Message data-event-id={event.id}><MessageContent><Bubble variant={event.type === "error" ? "destructive" : "ghost"}><BubbleContent className="whitespace-pre-wrap">{description(event)}</BubbleContent></Bubble></MessageContent></Message></MessageScrollerItem>;
              })}
            </MessageScrollerContent>
          </MessageScrollerViewport>
          <MessageScrollerButton />
        </MessageScroller>
      </MessageScrollerProvider>
    </Panel>
  );
}
