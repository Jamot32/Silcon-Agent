"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getJson, type Run } from "@/lib/api";

export function RunHistory() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    getJson<Run[]>("/api/runs", controller.signal)
      .then(setRuns)
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, []);
  return (
    <section className="panel history-panel" aria-labelledby="history-title">
      <h2 id="history-title">Your runs</h2>
      {runs && runs.length > 0 ? (
        <ul className="run-list">{runs.map((run) => <li key={run.id}><span>{run.spec_text}</span><span className="check-value">{run.status}</span></li>)}</ul>
      ) : (
        <div className="empty-state" aria-live="polite">
          <h3>{error ? "Run history could not be loaded." : runs ? "No chip designs yet." : "Checking run history…"}</h3>
          <p>{error ? "Check the API connection and reload this page." : "Your real tool runs will appear here."}</p>
          <Link className="text-link" href="/">Start a new design <span aria-hidden="true">→</span></Link>
        </div>
      )}
    </section>
  );
}
