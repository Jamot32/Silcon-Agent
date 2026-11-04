"use client";

export const RUNS_CHANGED_EVENT = "silicon-agent:runs-changed";

export function notifyRunsChanged() {
  window.dispatchEvent(new Event(RUNS_CHANGED_EVENT));
}
