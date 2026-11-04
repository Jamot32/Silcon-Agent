"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CircleAlert, PencilLine } from "lucide-react";
import { createRun, type PublicRun } from "@/lib/api";
import { loadRunDefaults } from "@/lib/run-defaults";
import { revisionDefaults, revisionRequest, type RevisionEdit } from "@/lib/revision";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";

export function ReviseRun({ run, files, size }: { run: PublicRun; files: Record<string, string>; size?: "lg" }) {
  const router = useRouter();
  const rtl = Object.keys(files).filter((path) => path.startsWith("src/") && path.endsWith(".v"));
  const defaults = revisionDefaults(run, rtl.length > 0);
  // Opened lazily so the form starts from the run's final state, then keeps the draft between openings.
  const [edit, setEdit] = useState<RevisionEdit | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState("");
  const [expert, setExpert] = useState(false);
  const [review, setReview] = useState(true);
  const form = edit ?? defaults;
  const { body, rerun } = revisionRequest(run, form, defaults);
  const change = (patch: Partial<RevisionEdit>) => { setEdit({ ...form, ...patch }); setFailure(""); };

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    if (form.spec.trim().length < 10) return setFailure("Describe the chip in at least 10 characters.");
    if (!(form.clock >= 1 && form.clock <= 1000)) return setFailure("Target clock must be between 1 and 1000 MHz.");
    setSubmitting(true);
    try {
      const result = await createRun({ ...body, ...(expert && review ? { review: true } : {}) });
      router.push(`/runs/${result.run_id}`);
    } catch (reason) {
      setFailure(reason instanceof Error ? reason.message : "The build could not be queued.");
      setSubmitting(false);
    }
  }

  // Expert mode lives in browser settings, so it is read when the sheet opens.
  return <Sheet onOpenChange={(open) => { if (open) { setEdit((current) => current ?? defaults); setFailure(""); setExpert(loadRunDefaults().expert); } }}>
    <SheetTrigger asChild><Button variant="outline" size={size} className={size ? "flex-1 sm:flex-none" : undefined} data-testid="revise-run"><PencilLine data-icon="inline-start" />Revise</Button></SheetTrigger>
    <SheetContent className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-lg">
      <SheetHeader className="border-b pr-12">
        <SheetTitle>Revise this run</SheetTitle>
        <SheetDescription>Edit the full request: it replaces the previous one, so add what should change rather than writing only the change. This starts a new {run.is_replay ? "live build, not a replay," : "build"} with real model and EDA calls.</SheetDescription>
      </SheetHeader>
      <form id="revise-form" onSubmit={submit} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4" aria-label="Revision">
        <div className="grid gap-2">
          <Label htmlFor="revise-spec">Request</Label>
          <Textarea id="revise-spec" className="max-h-[45svh] min-h-40 text-sm leading-relaxed" value={form.spec} spellCheck={false}
            onChange={(event) => change({ spec: event.target.value })}
            onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) event.currentTarget.form?.requestSubmit(); }} />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
          <Label htmlFor="revise-clock" className="gap-1.5 text-xs font-normal text-muted-foreground">Clock
            <Input id="revise-clock" type="number" min="1" max="1000" value={Number.isFinite(form.clock) ? form.clock : ""} onChange={(event) => change({ clock: event.target.valueAsNumber })} className="h-7 w-20 text-xs" aria-label="Target clock (MHz)" />MHz
          </Label>
          <div className="flex items-center gap-2">
            <Checkbox id="revise-fit" checked={form.fit} onCheckedChange={(checked) => change({ fit: checked === true })} />
            <Label htmlFor="revise-fit" className="text-xs font-normal text-muted-foreground">Fit in one Tiny Tapeout tile</Label>
          </div>
        </div>
        <div className="flex items-start gap-3 rounded-lg border p-3">
          <Checkbox id="revise-reuse" className="mt-0.5" checked={form.reuse} disabled={!rtl.length} onCheckedChange={(checked) => change({ reuse: checked === true })} aria-describedby="revise-reuse-detail" />
          <div className="grid gap-1">
            <Label htmlFor="revise-reuse">Start from this run&apos;s RTL</Label>
            <p id="revise-reuse-detail" className="text-xs text-muted-foreground">{rtl.length
              ? `The orchestrator loads ${run.status === "done" ? "the selected design from its bundle" : "its last source state"} and the RTL designer changes only what the new request needs. Tests are written fresh from the new request.`
              : "This run produced no RTL, so the revision starts from scratch."}</p>
          </div>
        </div>
        {expert ? <div className="flex items-center gap-2">
          <Checkbox id="revise-review" checked={review} onCheckedChange={(checked) => setReview(checked === true)} />
          <Label htmlFor="revise-review" className="text-xs font-normal text-muted-foreground">Review spec before RTL</Label>
        </div> : null}
        {failure ? <Alert variant="destructive"><CircleAlert /><AlertDescription>{failure}</AlertDescription></Alert> : null}
      </form>
      <SheetFooter className="border-t">
        <p className="text-xs text-muted-foreground" aria-live="polite">{rerun ? "Nothing changed: this repeats the same request." : `New run linked to run ${run.id.slice(0, 8)}.`}</p>
        <Button type="submit" form="revise-form" disabled={submitting} data-testid="revise-submit">{submitting ? <><Spinner data-icon="inline-start" />Queuing…</> : rerun ? "Run again" : "Build revision"}</Button>
      </SheetFooter>
    </SheetContent>
  </Sheet>;
}
