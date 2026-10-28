"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { Check, Copy, GitCompareArrows } from "lucide-react";
import type { FileDiff } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PanelEmpty } from "./panel";

const MonacoView = dynamic(() => import("./monaco-view"), { ssr: false, loading: () => <PanelEmpty>Loading source editor…</PanelEmpty> });

export function SourcePanel({ files, diffs, isReplay = false, finished = false }: { files: Record<string, string>; diffs: Record<string, FileDiff>; isReplay?: boolean; finished?: boolean }) {
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
  return <Card role="region" aria-label="Design source code" className="min-w-0 gap-0 overflow-hidden py-0">
    <div className="h-11 shrink-0 overflow-x-auto border-b [scrollbar-width:thin]">
      <Tabs value={path} onValueChange={(value) => { setSelected(value); setShowDiff(false); }} className="h-full">
        <TabsList variant="line" className="h-full gap-0 p-0" aria-label="RTL and test files">
          {paths.map((name) => <TabsTrigger key={name} value={name} className="h-full flex-none rounded-none px-4 font-mono text-xs after:bottom-0 data-active:bg-muted/40">{name}</TabsTrigger>)}
        </TabsList>
      </Tabs>
    </div>
    <div className="flex h-9 shrink-0 items-center justify-between border-b px-3 text-[11px] text-muted-foreground"><span>{showDiff ? "Latest file changes" : "Read-only"}</span><div className="flex items-center gap-1">
      {diff ? <Button size="xs" variant={showDiff ? "secondary" : "ghost"} onClick={() => setShowDiff(!showDiff)} aria-pressed={showDiff}><GitCompareArrows data-icon="inline-start" />Changes</Button> : null}
      <Button size="icon-xs" variant="ghost" onClick={copy} disabled={!path} aria-label={copied ? "Copied source" : "Copy source"}>{copied ? <Check /> : <Copy />}</Button>
    </div></div>
    <div className="min-h-0 flex-1 overflow-hidden" data-testid="source-editor" data-file-path={path} data-last-file-event-id={latestEvent}>
      {path ? showDiff && diff && (diff.before === null || diff.after === null) ? <pre className="h-full overflow-auto p-4 font-mono text-xs leading-5 [tab-size:4]">{diff.diff}</pre> : <MonacoView path={path} value={showDiff && diff?.after != null ? diff.after : files[path]} before={diff?.before ?? undefined} diff={showDiff} /> : <PanelEmpty>{finished ? "No RTL or test files were recorded before this run ended." : isReplay ? "Recorded RTL and tests appear during playback." : "RTL and tests appear as the agent writes them."}</PanelEmpty>}
    </div>
  </Card>;
}
