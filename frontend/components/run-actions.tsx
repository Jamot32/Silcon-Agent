"use client";

import { useEffect, useId, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Archive, ArchiveRestore, Ellipsis, Pin, PinOff, Trash2 } from "lucide-react";
import { deleteRun, updateRunMetadata, type PublicRun, type RunMetadata } from "@/lib/api";
import { notifyRunsChanged } from "@/lib/run-history-events";
import { isTerminal } from "@/lib/run-state";
import { runName } from "@/components/run/format";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";

export function RunActions({ run, onChanged }: { run: PublicRun; onChanged?: () => void | Promise<void> }) {
  const router = useRouter();
  const pathname = usePathname();
  const inputId = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const deleteButton = useRef<HTMLButtonElement>(null);
  const keepButton = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);
  const deletable = isTerminal(run.status) && !run.pinned;
  const dirtyName = name.trim() !== (run.display_name ?? "");
  useEffect(() => {
    if (confirmDelete) { wasConfirming.current = true; keepButton.current?.focus(); }
    else if (wasConfirming.current) { wasConfirming.current = false; deleteButton.current?.focus(); }
  }, [confirmDelete]);

  async function update(patch: RunMetadata, success: string) {
    if (pending) return;
    setPending(true); setError(""); setMessage("");
    try {
      await updateRunMetadata(run.id, patch);
      setMessage(success);
      notifyRunsChanged();
      await onChanged?.();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "This run could not be updated."); }
    finally { setPending(false); }
  }

  async function remove() {
    if (pending || !deletable) return;
    setPending(true); setError("");
    try {
      await deleteRun(run.id);
      setOpen(false);
      notifyRunsChanged();
      if (pathname === `/runs/${run.id}` || pathname.startsWith(`/runs/${run.id}/`)) router.replace("/runs");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "This run could not be deleted."); }
    finally { setPending(false); }
  }

  return <Popover open={open} onOpenChange={(value) => {
    if (pending) return;
    setOpen(value); setConfirmDelete(false); setError(""); setMessage("");
    if (value) setName(run.display_name ?? "");
  }}>
    <PopoverTrigger asChild><Button type="button" variant="outline" size="icon-sm" aria-label={`Manage ${runName(run)}`} data-testid={`run-actions-${run.id}`}><Ellipsis /></Button></PopoverTrigger>
    <PopoverContent align="end" className="max-h-[var(--radix-popover-content-available-height)] w-80 max-w-[calc(100vw-2rem)] gap-4 overflow-y-auto" aria-label={`Manage ${runName(run)}`}>
      <PopoverHeader><PopoverTitle>Manage run</PopoverTitle><PopoverDescription>Keep this design easy to find.</PopoverDescription></PopoverHeader>
      <form onSubmit={(event) => { event.preventDefault(); if (dirtyName) void update({ display_name: name.trim() || null }, "Name saved."); }}>
        <FieldGroup>
          <Field data-disabled={pending}>
            <FieldLabel htmlFor={inputId}>Run name</FieldLabel>
            <Input id={inputId} value={name} maxLength={120} disabled={pending} placeholder={runName({ ...run, display_name: null })} aria-describedby={`${inputId}-help`} onChange={(event) => { setName(event.target.value); setError(""); setMessage(""); }} />
            <FieldDescription id={`${inputId}-help`}>Leave blank to use the design’s original name.</FieldDescription>
          </Field>
          <Button type="submit" size="sm" disabled={pending || !dirtyName}>Save name</Button>
        </FieldGroup>
      </form>
      <Separator />
      <div className="flex flex-col gap-2">
        <Button type="button" variant="outline" disabled={pending} onClick={() => void update({ pinned: !run.pinned }, run.pinned ? "Run unpinned." : "Run pinned and protected from deletion.")}>{run.pinned ? <PinOff data-icon="inline-start" /> : <Pin data-icon="inline-start" />}{run.pinned ? "Unpin run" : "Pin run"}</Button>
        <Button type="button" variant="outline" disabled={pending || (!run.archived && !isTerminal(run.status))} onClick={() => void update({ archived: !run.archived }, run.archived ? "Run restored to history." : "Run archived.")}>{run.archived ? <ArchiveRestore data-icon="inline-start" /> : <Archive data-icon="inline-start" />}{run.archived ? "Restore to history" : "Archive run"}</Button>
        <p className="text-xs text-muted-foreground">{!isTerminal(run.status) ? "Active runs stay in history until they end." : "Archive hides a run from History. It stays available in Archived and keeps its files."}</p>
      </div>
      <Separator />
      {confirmDelete ? <Alert variant="destructive">
        <AlertTitle>Delete this run permanently?</AlertTitle>
        <AlertDescription className="gap-3">
          <p className="wrap-anywhere">“{runName(run)}” and its stored results will be removed. This cannot be undone. Existing follow-up runs are kept.</p>
          <div className="flex flex-wrap gap-2">
            <Button ref={keepButton} type="button" variant="outline" size="sm" disabled={pending} onClick={() => setConfirmDelete(false)}>Keep run</Button>
            <Button type="button" variant="destructive" size="sm" disabled={pending || !deletable} onClick={() => void remove()}>{pending ? <Spinner data-icon="inline-start" /> : <Trash2 data-icon="inline-start" />}Delete permanently</Button>
          </div>
        </AlertDescription>
      </Alert> : <div className="flex flex-col gap-2">
        <Button ref={deleteButton} type="button" variant="outline" disabled={pending || !deletable} onClick={() => { setConfirmDelete(true); setError(""); setMessage(""); }}><Trash2 data-icon="inline-start" />Delete run…</Button>
        {!deletable ? <p className="text-xs text-muted-foreground">{run.pinned ? "Pinned runs are protected. Unpin this run before deleting it." : "Active runs are protected. Wait until this run ends before deleting it."}</p> : null}
      </div>}
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      <p role="status" className="text-xs text-muted-foreground">{pending ? "Updating run…" : message}</p>
    </PopoverContent>
  </Popover>;
}
