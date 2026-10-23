"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { Copy, GitCompareArrows } from "lucide-react";
import type { FileDiff } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const MonacoView = dynamic(() => import("./monaco-view"), { ssr: false, loading: () => <p className="panel-empty">Loading source editor…</p> });

export function SourcePanel({ files, diffs }: { files: Record<string, string>; diffs: Record<string, FileDiff> }) {
  const paths = Object.keys(files).sort();
  const [selected, setSelected] = useState("");
  const [showDiff, setShowDiff] = useState(false);
  const [copied, setCopied] = useState(false);
  const latestEvent = Math.max(0, ...Object.values(diffs).map((diff) => diff.event_id));
  const previousEvent = useRef<number | null>(null);
  const path = selected && files[selected] !== undefined ? selected : paths.find((name) => name.startsWith("src/")) ?? paths[0] ?? "";
  const diff = diffs[path];
  useEffect(() => {
    if (previousEvent.current !== null && latestEvent > previousEvent.current) {
      const changed = Object.values(diffs).find((entry) => entry.event_id === latestEvent);
      if (changed) { setSelected(changed.path); setShowDiff(true); }
    }
    if (latestEvent > 0) previousEvent.current = latestEvent;
  }, [latestEvent, diffs]);
  async function copy() {
    try { await navigator.clipboard.writeText(files[path]); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { setCopied(false); }
  }
  return <section className="instrument-panel source-panel" aria-label="Design source code">
    <header className="source-header">
      <Tabs value={path} onValueChange={(value) => { setSelected(value); setShowDiff(false); }}>
        <TabsList variant="line" className="file-tabs" aria-label="RTL and test files">
          {paths.map((name) => <TabsTrigger key={name} value={name}>{name}</TabsTrigger>)}
        </TabsList>
      </Tabs>
    </header>
    <div className="source-toolbar"><span>{showDiff ? "Latest file changes" : "Read-only"}</span><div>
      {diff ? <Button size="xs" variant={showDiff ? "secondary" : "ghost"} onClick={() => setShowDiff(!showDiff)} aria-pressed={showDiff}><GitCompareArrows data-icon="inline-start" />Changes</Button> : null}
      <Button size="icon-xs" variant="ghost" onClick={copy} disabled={!path} aria-label={copied ? "Copied source" : "Copy source"}><Copy /></Button>
    </div></div>
    <div className="source-editor" data-testid="source-editor" data-file-path={path} data-last-file-event-id={latestEvent}>
      {path ? showDiff && diff && (diff.before === null || diff.after === null) ? <pre className="raw-diff">{diff.diff}</pre> : <MonacoView path={path} value={showDiff && diff?.after != null ? diff.after : files[path]} before={diff?.before ?? undefined} diff={showDiff} /> : <p className="panel-empty">RTL and tests appear as the agent writes them.</p>}
    </div>
  </section>;
}
