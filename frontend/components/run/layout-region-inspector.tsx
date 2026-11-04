"use client";

import { useEffect, useId, useRef, useState, type ComponentProps } from "react";
import { CircleAlert, MessageSquare, RefreshCw, Square } from "lucide-react";
import { askLayoutQuestion, cancelLayoutQuestion, getLayoutQuestion, getLayoutQuestions, type LayoutQuestion, type LayoutRegionInput, type PublicRun } from "@/lib/api";
import type { LayoutRegionSelection } from "@/lib/layout-selection";
import { isTerminal } from "@/lib/run-state";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader } from "@/components/ui/sheet";
import { SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { LayoutViewer } from "./layout-viewer";
import { ReviseRun } from "./revise-run";

const pending = (job: LayoutQuestion | null) => job?.status === "pending" || job?.status === "running";
const sameRegion = (job: LayoutQuestion, selection: LayoutRegionSelection) => job.region.run_tag === selection.run_tag &&
  (["x0", "y0", "x1", "y1"] as const).every((key) => Math.abs(job.region.bounds[key] - selection.bounds[key]) < 1e-8);
const message = (error: unknown) => error instanceof Error ? error.message : "The layout question could not be loaded.";
const percent = (value: number) => `${Math.round(value * 1000) / 10}%`;

export function InspectableLayout({ run, files, ...props }: Omit<ComponentProps<typeof LayoutViewer>, "onInspectRegion"> & { run: PublicRun; files: Record<string, string> }) {
  const [selection, setSelection] = useState<LayoutRegionSelection | null>(null);
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLElement | null>(null);
  return <>
    <LayoutViewer {...props} onInspectRegion={(region) => { trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setSelection(region); setOpen(true); }} />
    {selection && selection.run_tag === props.layout?.run_tag && selection.image_url === props.layout?.image_url ? <RegionInspector key={`${run.id}:${selection.run_tag}:${JSON.stringify(selection.bounds)}`} run={run} files={files} selection={selection} open={open} onOpenChange={setOpen} restoreFocus={() => trigger.current?.focus()} /> : null}
  </>;
}

function RegionInspector({ run, files, selection, open, onOpenChange, restoreFocus }: { run: PublicRun; files: Record<string, string>; selection: LayoutRegionSelection; open: boolean; onOpenChange: (open: boolean) => void; restoreFocus: () => void }) {
  const id = useId();
  const [question, setQuestion] = useState("");
  const [change, setChange] = useState("");
  const [job, setJob] = useState<LayoutQuestion | null>(null);
  const [history, setHistory] = useState<LayoutQuestion[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    getLayoutQuestions(run.id, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      const matching = items.filter((item) => sameRegion(item, selection));
      setHistory(items);
      setJob((current) => matching.find((item) => item.id === current?.id) ?? current ?? matching[0] ?? null);
    }).catch((reason) => { if (!controller.signal.aborted) setError(message(reason)); });
    return () => controller.abort();
  }, [open, run.id, selection, refresh]);
  const activeQuestion = pending(job) ? job : history.find((item) => pending(item)) ?? null;
  useEffect(() => {
    if (!activeQuestion) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      getLayoutQuestion(run.id, activeQuestion.id, controller.signal).then((next) => {
        if (!controller.signal.aborted) { setJob((current) => current?.id === next.id ? next : current); setHistory((items) => items.map((item) => item.id === next.id ? next : item)); setError(""); }
      }).catch((reason) => { if (!controller.signal.aborted) setError(message(reason)); });
    }, 1000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [activeQuestion, run.id, refresh]);
  const requestSelection: LayoutRegionInput = { run_tag: selection.run_tag, bounds: selection.bounds, ...(job?.region.image_sha256 ? { expected_image_sha256: job.region.image_sha256 } : {}) };
  const busy = !!activeQuestion || submitting;
  const bounds = selection.bounds;
  const crop = { x: bounds.x0 * selection.image_width, y: bounds.y0 * selection.image_height, width: (bounds.x1 - bounds.x0) * selection.image_width, height: (bounds.y1 - bounds.y0) * selection.image_height };
  async function ask() {
    if (busy || !question.trim() || question.length > 2000) return;
    setSubmitting(true); setError("");
    try {
      const next = await askLayoutQuestion(run.id, requestSelection, question.trim());
      if (alive.current) { setJob(next); setHistory((items) => [next, ...items.filter((item) => item.id !== next.id)]); }
    } catch (reason) { if (alive.current) setError(message(reason)); }
    finally { if (alive.current) setSubmitting(false); }
  }
  async function cancel() {
    if (!activeQuestion || cancelling) return;
    setCancelling(true); setError("");
    try { const next = await cancelLayoutQuestion(run.id, activeQuestion.id); if (alive.current) { setJob((current) => current?.id === next.id ? next : current); setHistory((items) => items.map((item) => item.id === next.id ? next : item)); } }
    catch (reason) { if (alive.current) setError(message(reason)); }
    finally { if (alive.current) setCancelling(false); }
  }
  return <Sheet open={open} onOpenChange={onOpenChange}>
    <SheetContent className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl" data-testid="layout-region-inspector" onCloseAutoFocus={(event) => { event.preventDefault(); restoreFocus(); }}>
      <SheetHeader className="border-b pr-12"><SheetTitle>Inspect layout region</SheetTitle><SheetDescription>Ask about this part of the layout, or describe a change for the agent.</SheetDescription></SheetHeader>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <figure className="space-y-2">
          <svg role="img" aria-label="Selected layout region" viewBox={`${crop.x} ${crop.y} ${crop.width} ${crop.height}`} className="max-h-56 w-full rounded-lg border bg-black/40" style={{ aspectRatio: `${crop.width} / ${crop.height}` }}><image href={selection.image_url} width={selection.image_width} height={selection.image_height} /></svg>
          <figcaption className="space-y-1 text-xs text-muted-foreground"><p className="font-mono wrap-anywhere">{selection.run_tag}</p><p>{percent(bounds.x0)}–{percent(bounds.x1)} across · {percent(bounds.y0)}–{percent(bounds.y1)} from top · all visible layers</p></figcaption>
        </figure>
        <p className="text-xs leading-relaxed text-muted-foreground">The agent receives the layout image, selected crop, and recorded flow evidence. Image colors alone do not identify exact nets, cells, or layer IDs.</p>
        <Tabs defaultValue="ask">
          <TabsList className="w-full"><TabsTrigger value="ask">Ask agent</TabsTrigger><TabsTrigger value="change">Request a change</TabsTrigger></TabsList>
          <TabsContent value="ask" className="space-y-4 pt-2">
            <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); void ask(); }}>
              <Label htmlFor={`${id}-question`}>What would you like to know?</Label>
              <Textarea id={`${id}-question`} value={question} maxLength={2000} disabled={busy} placeholder="What is visible here, and what evidence would explain this dense area?" onChange={(event) => setQuestion(event.target.value)} />
              <div className="flex flex-wrap gap-2">{["Explain this region.", "What could cause congestion here?", "What should I investigate before changing this area?"].map((text) => <Button key={text} type="button" variant="outline" size="sm" disabled={busy} onClick={() => setQuestion(text)}>{text}</Button>)}</div>
              <div className="flex flex-wrap items-center gap-3"><Button type="submit" disabled={busy || !question.trim() || question.length > 2000}>{busy ? <Spinner /> : <MessageSquare />} {submitting ? "Queuing…" : activeQuestion ? activeQuestion.status === "pending" ? "Question queued" : "Agent is looking…" : "Ask about this region"}</Button>{activeQuestion ? <Button type="button" variant="outline" size="sm" disabled={cancelling || activeQuestion?.cancel_requested} onClick={cancel}><Square />{cancelling || activeQuestion?.cancel_requested ? "Stopping…" : "Stop answer"}</Button> : null}</div>
              <p className="text-xs text-muted-foreground">Uses your configured model. Asking a question does not start a chip build.</p>
            </form>
            {activeQuestion && activeQuestion.id !== job?.id ? <p role="status" className="text-sm text-muted-foreground">A question for another region is still running: {activeQuestion.question}. You can stop it above before asking about this selection.</p> : null}
            {job ? <section className="space-y-3 rounded-lg border p-3" aria-label="Agent answer" aria-live="polite"><div className="flex flex-wrap gap-2"><Badge variant="outline">{job.status}</Badge>{job.model ? <span className="text-xs text-muted-foreground">{job.model}</span> : null}</div><p className="text-sm font-medium whitespace-pre-wrap wrap-anywhere">{job.question}</p>{job.answer ? <p className="text-sm leading-relaxed whitespace-pre-wrap wrap-anywhere">{job.answer}</p> : pending(job) ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner />{job.cancel_requested ? "Waiting for the host worker to stop the answer." : job.status === "pending" ? "Waiting for the host worker." : "Examining the selected image and available evidence."}</p> : <p className="text-sm text-muted-foreground">{job.error ?? "This question was stopped."}</p>}{job.status === "done" ? <p className="text-xs text-muted-foreground">{job.input_tokens + job.output_tokens} tokens · {job.cost_usd == null ? "USD unavailable" : `$${job.cost_usd.toFixed(4)}`}</p> : null}</section> : null}
            {history.filter((item) => item.id !== job?.id && sameRegion(item, selection)).length ? <details><summary className="cursor-pointer text-sm">Earlier questions for this region</summary><ul className="mt-2 space-y-2">{history.filter((item) => item.id !== job?.id && sameRegion(item, selection)).map((item) => <li key={item.id}><Button type="button" variant="ghost" className="h-auto max-w-full whitespace-normal text-left" disabled={busy} onClick={() => setJob(item)}>{item.question}</Button></li>)}</ul></details> : null}
          </TabsContent>
          <TabsContent value="change" className="space-y-3 pt-2"><Label htmlFor={`${id}-change`}>What should change in this region?</Label><Textarea id={`${id}-change`} maxLength={3500} value={change} onChange={(event) => setChange(event.target.value)} placeholder="Investigate the routing concentration in this region and reduce it while preserving the interface and timing target…" /><p className="text-xs leading-relaxed text-muted-foreground">The selected image region becomes context for a new revision. The agent changes RTL or flow settings and verifies a new layout; individual polygons are not edited directly. Placement can change across the whole chip.</p>{isTerminal(run.status) && change.trim().length >= 10 ? <ReviseRun key={change.trim()} run={run} files={files} layoutRegion={requestSelection} initialFollowUp={change.trim()} initialIntent="fix" triggerLabel="Prepare region change" /> : <p className="text-xs text-muted-foreground">{isTerminal(run.status) ? "Describe the change in at least 10 characters to prepare the revision." : "Finish or stop this run before preparing a revision."}</p>}</TabsContent>
        </Tabs>
        {error ? <Alert variant="destructive"><CircleAlert /><AlertDescription><p>{error}</p><Button type="button" size="sm" variant="outline" onClick={() => { setError(""); setRefresh((value) => value + 1); }}><RefreshCw />{job ? "Refresh answer status" : "Reload questions"}</Button></AlertDescription></Alert> : null}
      </div>
    </SheetContent>
  </Sheet>;
}
