"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cancelRun, eventsUrl, getRun, getRunFiles, getRunMetrics, RUN_EVENT_TYPES } from "./api";
import { applySnapshot, emptyRunState, isTerminal, parseRunEvent, reduceRunEvent, type RunState } from "./run-state";

export type ConnectionState = "connecting" | "open" | "reconnecting" | "closed";

export function useRun(id: string) {
  const [state, setState] = useState<RunState>(emptyRunState);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const controls = useRef<{ refresh: () => Promise<void>; cancel: () => Promise<void> } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let source: EventSource | null = null;
    let scheduled: ReturnType<typeof setTimeout> | null = null;
    let latestRequest = 0;
    let terminal = false;
    let lastEventId = 0;
    let disposed = false;
    let terminalEvent = false;
    setState(emptyRunState());
    setLoading(true);
    setError(null);
    setConnection("connecting");

    const refresh = async () => {
      const request = ++latestRequest;
      try {
        const [run, files, metrics] = await Promise.all([
          getRun(id, controller.signal), getRunFiles(id, controller.signal), getRunMetrics(id, controller.signal),
        ]);
        if (disposed || request !== latestRequest) return;
        terminal = isTerminal(run.status);
        setState((current) => applySnapshot(current, { run, files, metrics }));
        setLoading(false);
        setError(null);
        if (terminal && terminalEvent) {
          source?.close();
          setConnection("closed");
        }
      } catch (caught) {
        if (disposed || controller.signal.aborted || request !== latestRequest) return;
        setLoading(false);
        setError(caught instanceof Error ? caught.message : "The run could not be loaded.");
      }
    };
    const scheduleRefresh = () => {
      if (scheduled !== null) return;
      scheduled = setTimeout(() => {
        scheduled = null;
        void refresh();
      }, 100);
    };
    const cancel = async () => {
      try {
        await cancelRun(id, controller.signal);
        await refresh();
      } catch (caught) {
        if (!disposed && !controller.signal.aborted) setError(caught instanceof Error ? caught.message : "The run could not be cancelled.");
        throw caught;
      }
    };
    controls.current = { refresh, cancel };

    async function start() {
      await refresh();
      if (disposed) return;
      // One EventSource owns reconnection and Last-Event-ID. History starts at 0.
      source = new EventSource(eventsUrl(id));
      const receive = (raw: Event) => {
        if (!(raw instanceof MessageEvent) || typeof raw.data !== "string" || disposed) return;
        try {
          const event = parseRunEvent(raw.data);
          if (event.id <= lastEventId) return;
          lastEventId = event.id;
          setState((current) => reduceRunEvent(current, event));
          if (event.type === "run_finished") {
            terminalEvent = true;
            source?.close();
            setConnection("closed");
            void refresh();
          } else if (["stage_changed", "cost_update", "file_written", "metric_recorded", "layout_rendered", "error"].includes(event.type)) scheduleRefresh();
        } catch (caught) {
          setError(caught instanceof Error ? caught.message : "The live event could not be read.");
        }
      };
      for (const kind of RUN_EVENT_TYPES) source.addEventListener(kind, receive);
      source.onopen = () => { if (!disposed) setConnection("open"); };
      source.onerror = (raw) => {
        // A named application `error` event is different from transport failure.
        if (raw instanceof MessageEvent || disposed) return;
        if (terminal) {
          source?.close();
          setConnection("closed");
          void refresh();
        } else {
          setConnection("reconnecting");
          void refresh();
        }
      };
    }
    void start();
    return () => {
      disposed = true;
      controller.abort();
      source?.close();
      if (scheduled !== null) clearTimeout(scheduled);
      controls.current = null;
    };
  }, [id]);

  const refresh = useCallback(async () => { await controls.current?.refresh(); }, []);
  const cancel = useCallback(async () => { await controls.current?.cancel(); }, []);
  return { ...state, loading, error, connection, cancel, refresh };
}
