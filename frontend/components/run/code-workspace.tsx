"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, FileCode, FolderOpen, Play, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { ApiError, createRun } from "@/lib/api";
import { useRun } from "@/lib/use-run";
import { notifyRunsChanged } from "@/lib/run-history-events";
import { clearWorkspaceRecovery, getFlowSources, getWorkspace, readWorkspaceRecovery, saveWorkspace, saveWorkspaceRecovery, validateWorkspace, workspaceBuildProblems, workspaceFilePattern, workspaceFingerprint, workspaceFlows, type WorkspaceDraft, type WorkspaceFiles, type WorkspaceRecovery, type WorkspaceSource } from "@/lib/workspace";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RunUnavailable } from "./loading-state";
import { runName } from "./format";
import { WorkspaceCompare } from "./workspace-compare";

const CodeEditor = dynamic(() => import("./workspace-monaco").then((module) => module.WorkspaceEditor), { ssr: false });
type Confirmation = { title: string; description: string; action: () => void; confirm: string };
const sourceDescription = (source: WorkspaceSource | null) => !source ? "New workspace" : source.kind === "working" ? "Latest working files" : source.run_tag ? `Flow ${source.run_tag}` : `Flow attempt event ${source.event_id}`;

export function CodeWorkspace({ id, initialTab = "edit", initialFlow, initialFile }: { id: string; initialTab?: "edit" | "compare"; initialFlow?: string; initialFile?: string }) {
  const router = useRouter();
  const { run, files: workingFiles, events, metrics, loading: runLoading, error: runError } = useRun(id);
  const [files, setFiles] = useState<WorkspaceFiles>({});
  const [replacementRevision, setReplacementRevision] = useState(0);
  const [source, setSource] = useState<WorkspaceSource | null>(null);
  const [revision, setRevision] = useState(0);
  const [savedFingerprint, setSavedFingerprint] = useState(workspaceFingerprint({}, null));
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState("");
  const [flowKey, setFlowKey] = useState("");
  const [newPath, setNewPath] = useState("");
  const [pathError, setPathError] = useState("");
  const [mode, setMode] = useState<"agent" | "manual">("agent");
  const [busy, setBusy] = useState<"save" | "load" | "build" | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [recoveryError, setRecoveryError] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const recovery = useRef<WorkspaceRecovery | null>(null);
  const pendingInitialFiles = useRef(false);
  const requestedFile = useRef(initialFile);
  const options = useMemo(() => run ? workspaceFlows(run, events, metrics) : [], [run, events, metrics]);
  const chosenFlow = options.find((option) => option.key === flowKey) ?? options.find((option) => option.tag === initialFlow) ?? options.find((option) => option.selected) ?? options[0];
  const paths = Object.keys(files).sort();
  const path = selected in files ? selected : paths[0] ?? "";
  const dirty = workspaceFingerprint(files, source) !== savedFingerprint;
  const invalid = validateWorkspace(files);
  const buildProblems = run ? workspaceBuildProblems(run, files, mode) : [];
  const disabled = !!busy || !ready;

  useEffect(() => {
    const controller = new AbortController();
    getWorkspace(id, controller.signal).then((draft) => {
      if (controller.signal.aborted) return;
      const local = readWorkspaceRecovery(id);
      recovery.current = local.recovery;
      const initialFiles = local.recovery?.files ?? draft.files ?? {};
      // An intentionally empty saved/recovered draft is still a draft.
      pendingInitialFiles.current = draft.files === null && !local.recovery;
      setFiles(initialFiles);
      setReplacementRevision((value) => value + 1);
      if (requestedFile.current && Object.hasOwn(initialFiles, requestedFile.current)) setSelected(requestedFile.current);
      setSource(local.recovery ? local.recovery.base_source : draft.base_source);
      setRevision(local.recovery?.revision ?? draft.revision);
      setSavedFingerprint(workspaceFingerprint(draft.files ?? {}, draft.base_source));
      setSavedAt(draft.updated_at); setReady(true); setError("");
      setMessage(local.recovery ? "Recovered your unsaved edits from this browser." : draft.files ? "Saved workspace loaded." : "Load source files or add a file to begin editing.");
      if (local.recovery && local.recovery.revision !== draft.revision) setError("The server draft changed after these local edits. Keep a copy of your changes, then use Reload saved draft to load the newer version. Saving will not overwrite it.");
      if (!local.available) setRecoveryError("Browser recovery is unavailable. Save your draft before leaving this page.");
    }, (reason) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Workspace could not be loaded."); });
    return () => controller.abort();
  }, [id, attempt]);
  useEffect(() => {
    if (!ready || runLoading || !pendingInitialFiles.current || !Object.keys(workingFiles).length) return;
    // Consume this once, before updating state, so live file events never replace an edited draft.
    pendingInitialFiles.current = false;
    const initialFiles = { ...workingFiles };
    const base: WorkspaceSource = { kind: "working", run_tag: null, event_id: null };
    setFiles(initialFiles); setSource(base);
    setReplacementRevision((value) => value + 1);
    if (requestedFile.current && Object.hasOwn(initialFiles, requestedFile.current)) setSelected(requestedFile.current);
    const local: WorkspaceRecovery = { version: 1, revision, files: initialFiles, base_source: base };
    if (saveWorkspaceRecovery(id, local)) { recovery.current = local; setRecoveryError(""); }
    else setRecoveryError("Browser recovery could not be saved. Keep this page open; save a valid draft or copy your edits before leaving.");
    setMessage("Working files are ready. Click code to edit, then Save draft. These files may differ from the selected physical result.");
  }, [id, ready, revision, runLoading, workingFiles]);
  useEffect(() => {
    if (!dirty || !recoveryError) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, recoveryError]);
  useEffect(() => {
    if (!dirty || !recoveryError) return;
    const guard = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
      const destination = new URL(link.href, window.location.href);
      if (destination.origin !== window.location.origin || destination.pathname + destination.search === window.location.pathname + window.location.search) return;
      event.preventDefault(); event.stopPropagation();
      setConfirmation({ title: "Leave without saving?", description: "Browser recovery is unavailable and this draft has unsaved edits. Stay here and save the draft to keep your changes.", confirm: "Leave without saving", action: () => router.push(destination.pathname + destination.search + destination.hash) });
    };
    document.addEventListener("click", guard, true);
    return () => document.removeEventListener("click", guard, true);
  }, [dirty, recoveryError, router]);

  function edit(next: WorkspaceFiles, nextSource = source) {
    if (busy) return;
    pendingInitialFiles.current = false;
    setFiles(next); setSource(nextSource); setError(""); setMessage("");
    const local: WorkspaceRecovery = { version: 1, revision, files: next, base_source: nextSource };
    if (saveWorkspaceRecovery(id, local)) { recovery.current = local; setRecoveryError(""); }
    else setRecoveryError("Browser recovery could not be saved. Keep this page open; save a valid draft or copy your edits before leaving.");
  }
  function confirmReplacement(action: () => void) {
    if (disabled) return;
    if (dirty) setConfirmation({ title: "Replace unsaved changes?", description: "This replaces your current editor files. Save the draft or copy anything you want to keep first.", action, confirm: "Replace files" });
    else action();
  }
  function acceptSaved(draft: WorkspaceDraft) {
    setRevision(draft.revision); setSavedAt(draft.updated_at);
    setSavedFingerprint(workspaceFingerprint(draft.files ?? {}, draft.base_source));
    if (!clearWorkspaceRecovery(id, recovery.current)) setRecoveryError("The draft is saved on the server, but this browser could not clear its recovery copy.");
    else { recovery.current = null; setRecoveryError(""); }
  }
  async function persist() {
    const draft = await saveWorkspace(id, files, revision, source);
    acceptSaved(draft);
    return draft;
  }
  async function save() {
    if (disabled || invalid.length || !dirty) return;
    setBusy("save"); setError("");
    try { await persist(); setMessage("Draft saved on the server."); }
    catch (reason) { setError(reason instanceof ApiError && reason.status === 409 ? "Another tab saved a newer draft. Your edits are still here. Copy anything you want to keep, then Reload saved draft before saving again." : reason instanceof Error ? reason.message : "Draft could not be saved."); }
    finally { setBusy(null); }
  }
  async function reloadDraft() {
    pendingInitialFiles.current = false;
    setBusy("load"); setError("");
    try { const draft = await getWorkspace(id); setFiles(draft.files ?? {}); setReplacementRevision((value) => value + 1); setSource(draft.base_source); acceptSaved(draft); setMessage(draft.files ? "Saved draft reloaded." : "There is no saved server draft. Your workspace is empty."); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Saved draft could not be loaded."); }
    finally { setBusy(null); }
  }
  async function loadFlow() {
    if (!chosenFlow) return;
    pendingInitialFiles.current = false;
    setBusy("load"); setError("");
    try {
      const snapshot = await getFlowSources(id, chosenFlow.selector);
      if (!snapshot.available) throw new Error(snapshot.reason ?? "No immutable source snapshot is available for this flow.");
      const base: WorkspaceSource = { kind: "flow", run_tag: "runTag" in chosenFlow.selector ? chosenFlow.selector.runTag : null, event_id: "eventId" in chosenFlow.selector ? chosenFlow.selector.eventId : null };
      setFiles(snapshot.files); setSource(base);
      setReplacementRevision((value) => value + 1);
      const local: WorkspaceRecovery = { version: 1, revision, files: snapshot.files, base_source: base };
      if (saveWorkspaceRecovery(id, local)) { recovery.current = local; setRecoveryError(""); }
      else setRecoveryError("Browser recovery could not be saved. Save this draft before leaving.");
      setMessage(`Loaded ${chosenFlow.label} from ${snapshot.provenance === "selected_bundle" ? "its verified selected bundle" : "its frozen source snapshot"}.${snapshot.reason ? ` ${snapshot.reason}` : ""}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Source snapshot could not be loaded. Your edits are unchanged."); }
    finally { setBusy(null); }
  }
  async function build() {
    if (!run || disabled || buildProblems.length) return;
    setBusy("build"); setError("");
    try {
      await persist();
      const result = await createRun({ spec_text: run.spec_text, parent_run_id: id, execution_mode: mode, manual_files: files });
      notifyRunsChanged(); router.push(`/runs/${result.run_id}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The edited design could not be queued. Your draft is retained."); setBusy(null); }
  }

  if (!run) return <RunUnavailable title={runLoading ? "Opening code workspace…" : "Workspace unavailable."} description={runError ?? "Loading the saved run."} />;
  return <div className="flex min-w-0 flex-col gap-4" data-testid="code-workspace">
    <header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h1 className="text-2xl font-semibold tracking-tight wrap-anywhere">{runName(run)} · Code workspace</h1><p className="mt-1 text-sm text-muted-foreground">Edit a draft without changing recorded results. Every build creates a new linked run.</p></div><Button asChild variant="outline"><Link href={`/runs/${id}`}><ArrowLeft data-icon="inline-start" />Back to run</Link></Button></header>
    <Tabs defaultValue={initialTab} className="gap-4"><TabsList aria-label="Workspace view"><TabsTrigger value="edit">Edit code</TabsTrigger><TabsTrigger value="compare">Compare flows</TabsTrigger></TabsList>
      <TabsContent value="edit" className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex flex-wrap items-center gap-2"><Badge variant={dirty ? "outline" : "secondary"}>{dirty ? "Unsaved changes" : savedAt ? "Saved draft" : "No saved draft"}</Badge><span className="text-xs text-muted-foreground">{savedAt ? `Server saved ${new Date(savedAt).toLocaleString()}` : "No server draft saved yet"}</span></div><div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={disabled} onClick={() => confirmReplacement(() => void reloadDraft())}><RotateCcw data-icon="inline-start" />Reload saved draft</Button><Button type="button" disabled={disabled || invalid.length > 0 || !dirty} onClick={() => void save()}>{busy === "save" ? <Spinner data-icon="inline-start" /> : <Save data-icon="inline-start" />}Save draft</Button></div></div>
        {error || runError ? <Alert variant="destructive"><AlertDescription className="wrap-anywhere">{error || runError}{!ready ? <Button variant="outline" size="sm" className="mt-2" onClick={() => setAttempt((value) => value + 1)}>Retry workspace</Button> : null}</AlertDescription></Alert> : null}
        {recoveryError ? <Alert><AlertDescription>{recoveryError}</AlertDescription></Alert> : null}
        <p role="status" className="text-sm text-muted-foreground">{!ready && !error ? "Loading saved workspace…" : busy === "load" ? "Loading source files…" : busy === "build" ? "Saving draft and queuing a new build…" : message || (dirty ? "Edits are recovered in this browser. Save draft to persist them on the server." : "")}</p>
        <Card className="min-w-0"><CardHeader><CardTitle>Source files</CardTitle><CardDescription className="wrap-anywhere">{sourceDescription(source)}. Loading another source replaces the editor draft.</CardDescription></CardHeader><CardContent className="flex flex-wrap items-end gap-3">
          <Button type="button" variant="outline" disabled={disabled || !Object.keys(workingFiles).length} onClick={() => confirmReplacement(() => { edit({ ...workingFiles }, { kind: "working", run_tag: null, event_id: null }); setReplacementRevision((value) => value + 1); setMessage("Loaded latest working files. These may differ from the selected physical result."); })}><FolderOpen data-icon="inline-start" />Load working files</Button>
          <Field className="min-w-0 flex-1 basis-64"><FieldLabel htmlFor="workspace-flow">Source snapshot</FieldLabel><NativeSelect id="workspace-flow" className="w-full" disabled={disabled || !options.length} value={chosenFlow?.key ?? ""} onChange={(event) => setFlowKey(event.target.value)}>{options.length ? options.map((option) => <NativeSelectOption key={option.key} value={option.key}>{option.label}</NativeSelectOption>) : <NativeSelectOption value="">No recorded flows</NativeSelectOption>}</NativeSelect></Field>
          <Button type="button" variant="outline" disabled={disabled || !chosenFlow} onClick={() => confirmReplacement(() => void loadFlow())}>Load flow snapshot</Button>
        </CardContent></Card>
        {invalid.length ? <Alert variant="destructive"><AlertDescription><ul className="list-disc pl-4">{invalid.map((item) => <li key={item} className="wrap-anywhere">{item}</li>)}</ul></AlertDescription></Alert> : null}
        <div className="grid min-w-0 gap-3 lg:grid-cols-[220px_minmax(0,1fr)]">
          <Card className="min-w-0 gap-3"><CardHeader><CardTitle>Files</CardTitle><CardDescription>{paths.length} / 64 files</CardDescription></CardHeader><CardContent className="flex min-w-0 flex-col gap-4">
            <nav aria-label="Workspace files" className="flex min-w-0 flex-col gap-3">{["src", "test"].map((directory) => <div key={directory} className="flex min-w-0 flex-col gap-1"><p className="text-xs font-medium text-muted-foreground">{directory}/</p>{paths.filter((name) => name.startsWith(`${directory}/`)).map((name) => <Button key={name} type="button" variant={path === name ? "secondary" : "ghost"} size="sm" className="max-w-full justify-start" title={name} aria-pressed={path === name} disabled={!!busy} onClick={() => setSelected(name)}><FileCode data-icon="inline-start" /><span className="truncate">{name.slice(directory.length + 1)}</span></Button>)}</div>)}</nav>
            <details><summary className="cursor-pointer rounded-sm text-sm focus-visible:outline-2 focus-visible:outline-ring">Add file</summary><form className="mt-3" onSubmit={(event) => { event.preventDefault(); if (disabled) return; const name = newPath.trim(); if (!workspaceFilePattern.test(name)) { setPathError("Use src/name.v or test/name.py. Names use letters, numbers and underscores, starting with a letter or underscore."); return; } if (name in files) { setPathError("That file already exists."); return; } if (paths.length >= 64) { setPathError("A workspace can contain at most 64 files."); return; } edit({ ...files, [name]: "" }); setSelected(name); setNewPath(""); setPathError(""); }}><FieldGroup><Field data-invalid={!!pathError}><FieldLabel htmlFor="workspace-new-path">New file path</FieldLabel><Input id="workspace-new-path" value={newPath} disabled={disabled} placeholder="src/counter.v" aria-invalid={!!pathError} aria-describedby={pathError ? "workspace-path-error" : undefined} onChange={(event) => { pendingInitialFiles.current = false; setNewPath(event.target.value); setPathError(""); }} />{pathError ? <p id="workspace-path-error" role="alert" className="text-xs text-destructive">{pathError}</p> : null}</Field><Button type="submit" variant="outline" size="sm" disabled={disabled || !newPath.trim()}><Plus data-icon="inline-start" />Add file</Button></FieldGroup></form></details>
          </CardContent></Card>
          <Card className="min-w-0 gap-0 overflow-hidden py-0"><div className="flex min-w-0 items-center justify-between gap-2 border-b px-3 py-2"><p className="min-w-0 font-mono text-xs wrap-anywhere">{path || "No file selected"}</p><Button type="button" variant="ghost" size="icon-sm" aria-label="Remove file" disabled={disabled || !path} onClick={() => { const remove = () => { const next = { ...files }; delete next[path]; edit(next); }; if (files[path]) setConfirmation({ title: "Remove this file?", description: `${path} will be removed from your draft. Recorded run files stay unchanged.`, action: remove, confirm: "Remove file" }); else remove(); }}><Trash2 /></Button></div>
            <div className="h-[560px] min-w-0" data-testid="workspace-editor" data-file-path={path}>{path ? <CodeEditor runId={id} path={path} value={files[path]} replacementRevision={replacementRevision} disabled={disabled} onChange={(value) => { if (!disabled) edit({ ...files, [path]: value }); }} onSave={() => void save()} /> : <Empty className="h-full"><EmptyHeader><EmptyTitle>No draft files</EmptyTitle><EmptyDescription>Load working files, choose a recorded source snapshot, or add a file.</EmptyDescription></EmptyHeader></Empty>}</div>
          </Card>
        </div>
        <Card><CardHeader><CardTitle>Build edited design</CardTitle><CardDescription>The saved parent specification and targets stay attached to the new run. Your current files are saved before submission.</CardDescription></CardHeader><CardContent className="flex flex-col gap-4"><FieldGroup><Field><FieldLabel htmlFor="workspace-build-mode">Build mode</FieldLabel><NativeSelect id="workspace-build-mode" className="w-full sm:max-w-md" value={mode} disabled={disabled} onChange={(event) => setMode(event.target.value as "agent" | "manual")}><NativeSelectOption value="agent">Agent repair and optimize</NativeSelectOption><NativeSelectOption value="manual">Verify without AI changes</NativeSelectOption></NativeSelect><FieldDescription>{mode === "agent" ? "The agent starts from your edited RTL, writes fresh independent tests, and may repair or optimize the design. Your edited tests stay in this draft and the submitted snapshot; they do not replace independent verification. This uses model and EDA calls." : "Runs your RTL and exactly one edited test module, then synthesis and one physical flow. No model calls, AI repairs, or optimization. Failing checks stop the new run without rewriting your code."}</FieldDescription></Field></FieldGroup>
          {buildProblems.length ? <ul className="list-disc pl-4 text-sm text-muted-foreground" aria-label="Build requirements">{buildProblems.map((item) => <li key={item} className="wrap-anywhere">{item}</li>)}</ul> : null}
          <Button type="button" className="self-start" disabled={disabled || buildProblems.length > 0} onClick={() => void build()}>{busy === "build" ? <Spinner data-icon="inline-start" /> : <Play data-icon="inline-start" />}Build edited design</Button>
        </CardContent></Card>
      </TabsContent>
      <TabsContent value="compare"><WorkspaceCompare run={run} options={options} initialFlow={initialFlow} /></TabsContent>
    </Tabs>
    <Sheet open={!!confirmation} onOpenChange={(open) => { if (!open) setConfirmation(null); }}><SheetContent className="data-[side=right]:w-full"><SheetHeader><SheetTitle>{confirmation?.title}</SheetTitle><SheetDescription className="wrap-anywhere">{confirmation?.description}</SheetDescription></SheetHeader><SheetFooter><Button type="button" variant="outline" onClick={() => setConfirmation(null)}>Keep editing</Button><Button type="button" onClick={() => { const action = confirmation?.action; setConfirmation(null); action?.(); }}>{confirmation?.confirm}</Button></SheetFooter></SheetContent></Sheet>
  </div>;
}
