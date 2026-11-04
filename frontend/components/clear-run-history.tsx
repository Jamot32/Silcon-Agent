"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { cleanupRuns, type Run, type RunCleanup } from "@/lib/api";
import { notifyRunsChanged } from "@/lib/run-history-events";
import { isTerminal } from "@/lib/run-state";
import { runName } from "@/components/run/format";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";

export type HistoryView = "history" | "archived" | "all";

export function ClearRunHistory({ runs, view, onResult }: { runs: Run[]; view: HistoryView; onResult: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Run[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const eligible = runs.filter((run) => isTerminal(run.status) && !run.pinned);
  const scope = view === "history" ? "History" : view === "archived" ? "Archived" : "All runs";
  async function clear() {
    if (pending || !selected.length) return;
    setPending(true); setError("");
    const result: RunCleanup = { deleted_ids: [], skipped: [] };
    try {
      // Freeze the confirmed IDs; newly created runs must never enter an in-flight cleanup.
      for (let start = 0; start < selected.length; start += 100) {
        const batch = await cleanupRuns(selected.slice(start, start + 100).map((run) => run.id));
        result.deleted_ids.push(...batch.deleted_ids);
        result.skipped.push(...batch.skipped);
      }
      onResult(`${result.deleted_ids.length} run${result.deleted_ids.length === 1 ? "" : "s"} deleted.${result.skipped.length ? ` ${result.skipped.length} skipped: ${Array.from(new Set(result.skipped.map((item) => item.reason))).join("; ")}.` : " Pinned and active runs were kept."}`);
      setOpen(false);
    } catch (reason) {
      setError(`${result.deleted_ids.length ? `${result.deleted_ids.length} runs were deleted before the request stopped. ` : ""}${reason instanceof Error ? reason.message : "History could not be cleared."} You can retry; protected runs are kept.`);
    } finally {
      notifyRunsChanged();
      setPending(false);
    }
  }
  return <Sheet open={open} onOpenChange={(value) => {
    if (pending) return;
    if (value) { setSelected(eligible); setError(""); }
    setOpen(value);
  }}>
    <SheetTrigger asChild><Button type="button" variant="outline" size="sm" disabled={!eligible.length}><Trash2 data-icon="inline-start" />Clear history…</Button></SheetTrigger>
    <SheetContent className="data-[side=right]:w-full" showCloseButton={!pending}>
      <SheetHeader className="pr-12"><SheetTitle>Clear {scope.toLowerCase()}?</SheetTitle><SheetDescription>Permanently delete {selected.length} unpinned, finished run{selected.length === 1 ? "" : "s"} from {scope} and remove their stored results. This cannot be undone.</SheetDescription></SheetHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4">
        <p className="text-sm text-muted-foreground">Pinned and active runs are protected. Runs outside this view stay saved. Existing follow-up runs are kept.</p>
        <ul aria-label="Runs selected for deletion" className="flex flex-col gap-2">{selected.map((run) => <li key={run.id} className="flex min-w-0 justify-between gap-3 text-sm"><span className="min-w-0 break-words">{runName(run)}</span><code className="shrink-0 text-xs text-muted-foreground">{run.id.slice(0, 8)}</code></li>)}</ul>
        {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      </div>
      <SheetFooter>
        <Button type="button" variant="outline" disabled={pending} onClick={() => setOpen(false)}>Keep runs</Button>
        <Button type="button" variant="destructive" disabled={pending || !selected.length} onClick={() => void clear()}>{pending ? <Spinner data-icon="inline-start" /> : <Trash2 data-icon="inline-start" />}{pending ? "Clearing history…" : `Delete ${selected.length} run${selected.length === 1 ? "" : "s"} permanently`}</Button>
      </SheetFooter>
    </SheetContent>
  </Sheet>;
}
