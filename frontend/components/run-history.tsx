"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Archive, ArrowRight, Folder, FolderInput, Pin, RefreshCw } from "lucide-react";
import { getJson, getRunMetrics, listRuns, type Metric, type Recording, type Run } from "@/lib/api";
import { RUNS_CHANGED_EVENT } from "@/lib/run-history-events";
import { inFolder, writeRunDrag, type ProjectFolder } from "@/lib/projects";
import { matchesSearch, runSearchFields } from "@/lib/run-search";
import { moveRunsToProject, useProjects } from "@/lib/use-projects";
import { ClearRunHistory, type HistoryView } from "@/components/clear-run-history";
import { ProjectFolders } from "@/components/project-folders";
import { RunActions } from "@/components/run-actions";
import { RunSearchInput } from "@/components/run-search-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Item, ItemActions, ItemContent, ItemDescription, ItemFooter, ItemGroup, ItemTitle } from "@/components/ui/item";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ReplayBadge, StatusBadge } from "@/components/run/badges";
import { bestMeasured, number, replayLabel, runName, usageLabel } from "@/components/run/format";

export function RunHistory() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [metrics, setMetrics] = useState<Record<string, Metric[]>>({});
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const [view, setView] = useState<HistoryView>("history");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const { projects, error: projectsError } = useProjects();
  const [folder, setFolder] = useState<ProjectFolder>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [moveTarget, setMoveTarget] = useState("");
  const [moving, setMoving] = useState(false);
  useEffect(() => {
    const changed = () => setVersion((value) => value + 1);
    window.addEventListener(RUNS_CHANGED_EVENT, changed);
    return () => window.removeEventListener(RUNS_CHANGED_EVENT, changed);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    async function load() {
      try {
        const [runsResult, recordingsResult] = await Promise.allSettled([listRuns(controller.signal), getJson<Recording[]>("/api/recordings", controller.signal)]);
        if (runsResult.status === "rejected") throw runsResult.reason;
        if (controller.signal.aborted) return;
        const rows = runsResult.value;
        if (recordingsResult.status === "fulfilled") setRecordings(recordingsResult.value);
        setRuns(rows); setError(""); setLoading(false);
        const results = await Promise.allSettled(rows.slice(0, 20).map(async (run) => [run.id, await getRunMetrics(run.id, controller.signal)] as const));
        if (controller.signal.aborted) return;
        setMetrics(Object.fromEntries(results.flatMap((result) => result.status === "fulfilled" ? [result.value] : [])));
      } catch (reason) {
        if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : "Run history could not be loaded."); setLoading(false); }
      }
    }
    void load();
    return () => controller.abort();
  }, [version]);
  const projectNames = new Map((projects ?? []).map((project) => [project.id, project.name]));
  // A project deleted in another tab falls back to every run instead of an empty, unknown folder.
  const activeFolder = folder === "all" || folder === "unfiled" || projectNames.has(folder) || projects === null ? folder : "all";
  const folderRuns = (runs ?? []).filter((run) => inFolder(run, activeFolder));
  const visible = folderRuns.filter((run) => view === "all" || (view === "archived" ? run.archived : !run.archived));
  const sources = new Map(recordings.map((recording) => [recording.id, recording.source_run_id]));
  const searching = query.trim() !== "";
  const shown = searching ? visible.filter((run) => matchesSearch(query, runSearchFields(run, runName(run), run.recording_id ? sources.get(run.recording_id) : null))) : visible;
  const chosen = shown.filter((run) => selected.has(run.id)).map((run) => run.id);
  const allChosen = shown.length > 0 && chosen.length === shown.length;
  const toggle = (id: string, on: boolean) => setSelected((current) => { const next = new Set(current); if (on) next.add(id); else next.delete(id); return next; });
  const selectFolder = (next: ProjectFolder) => { setFolder(next); setSelected(new Set()); setMessage(""); };
  async function moveChosen() {
    if (moving || !chosen.length || !moveTarget) return;
    const projectId = moveTarget === "unfiled" ? null : moveTarget;
    setMoving(true); setMessage("");
    try {
      const moved = await moveRunsToProject(chosen, projectId);
      setMessage(`${moved} run${moved === 1 ? "" : "s"} moved to ${projectId ? projectNames.get(projectId) ?? "the project" : "Unfiled"}.`);
      setSelected(new Set()); setMoveTarget("");
    } catch (reason) { setMessage(`Runs could not be moved. ${reason instanceof Error ? reason.message : ""}`.trim()); }
    finally { setMoving(false); }
  }
  const heading = activeFolder === "all" ? null : activeFolder === "unfiled" ? "Unfiled" : projectNames.get(activeFolder);
  return <section aria-label="Your runs" className="grid gap-6 md:grid-cols-[13rem_minmax(0,1fr)]">
    <aside className="flex flex-col gap-2 md:sticky md:top-4 md:self-start">
      <ProjectFolders runs={runs ?? []} projects={projects ?? []} folder={activeFolder} onSelect={selectFolder} onMessage={setMessage} />
      {projectsError ? <p className="px-2 text-xs text-destructive">Projects could not be loaded. {projectsError}</p> : null}
    </aside>
    <div className="flex min-w-0 flex-col gap-4">
    <p className="text-sm text-muted-foreground">{heading ? <><span className="font-medium text-foreground">{heading}.</span> </> : null}Runs stay saved until you delete them. Pin designs to keep them in the sidebar and protect them from cleanup. Drag runs onto a project folder to group them.</p>
    <Tabs value={view} onValueChange={(value) => { setView(value as HistoryView); setSelected(new Set()); setMessage(""); }} className="gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <TabsList aria-label="Run history view"><TabsTrigger value="history">History</TabsTrigger><TabsTrigger value="archived">Archived</TabsTrigger><TabsTrigger value="all">All runs</TabsTrigger></TabsList>
        <div className="flex items-center gap-2"><Button type="button" variant="ghost" size="sm" disabled={loading} onClick={() => setVersion((value) => value + 1)}><RefreshCw data-icon="inline-start" />Refresh</Button><ClearRunHistory runs={visible} view={view} onResult={setMessage} /></div>
      </div>
      <RunSearchInput value={query} onChange={(value) => { setQuery(value); setMessage(""); }} label="Search runs" placeholder="Search by name, spec keyword, or run ID" />
      {error ? <Alert variant="destructive"><AlertDescription>Run history could not be loaded. {error} Use Refresh to try again.</AlertDescription></Alert> : null}
      <p role="status" className="text-sm text-muted-foreground">{message || (runs ? searching ? `${shown.length} of ${visible.length} run${visible.length === 1 ? "" : "s"} match.` : `${visible.length} run${visible.length === 1 ? "" : "s"}${view === "archived" ? " archived" : " in this view"}.` : "")}</p>
      {shown.length > 0 ? <div role="toolbar" aria-label="Selected runs" className="flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-sm">
        <label className="flex items-center gap-2"><Checkbox checked={allChosen ? true : chosen.length ? "indeterminate" : false} onCheckedChange={(value) => setSelected(value === true ? new Set(shown.map((run) => run.id)) : new Set())} aria-label="Select all shown runs" />{chosen.length ? `${chosen.length} selected` : "Select runs"}</label>
        {chosen.length ? <>
          <NativeSelect size="sm" value={moveTarget} disabled={moving} aria-label="Move selected runs to" onChange={(event) => setMoveTarget(event.target.value)}>
            <NativeSelectOption value="">Move to…</NativeSelectOption>
            <NativeSelectOption value="unfiled">Unfiled</NativeSelectOption>
            {(projects ?? []).map((project) => <NativeSelectOption key={project.id} value={project.id}>{project.name}</NativeSelectOption>)}
          </NativeSelect>
          <Button type="button" size="sm" disabled={moving || !moveTarget} onClick={() => void moveChosen()}>{moving ? <Spinner data-icon="inline-start" /> : <FolderInput data-icon="inline-start" />}{moving ? "Moving…" : "Move"}</Button>
          <Button type="button" variant="ghost" size="sm" disabled={moving} onClick={() => setSelected(new Set())}>Clear selection</Button>
        </> : <span className="text-muted-foreground">or drag a run onto a folder.</span>}
      </div> : null}
      <TabsContent value={view}>
    {shown.length > 0 ? <ItemGroup className="gap-2">{shown.map((run) => {
      const source = run.recording_id ? sources.get(run.recording_id) : undefined;
      const best = bestMeasured(metrics[run.id] ?? [], run.best_run_tag, run.design_spec?.targets.clock_mhz ?? run.targets.clock_mhz);
      return <Item key={run.id} variant="outline" role="listitem" data-testid={`run-row-${run.id}`} draggable
        onDragStart={(event) => writeRunDrag(event.dataTransfer, selected.has(run.id) ? chosen : [run.id])}>
        <Checkbox checked={selected.has(run.id)} onCheckedChange={(value) => toggle(run.id, value === true)} aria-label={`Select ${runName(run)}`} className="self-start mt-1" />
        <Link href={`/runs/${run.id}`} draggable={false} className="min-w-0 flex-1 basis-64 rounded-sm focus-visible:outline-2 focus-visible:outline-ring"><ItemContent>
          <ItemTitle className="max-w-full flex-wrap wrap-anywhere">{runName(run)}{run.execution_mode === "manual" ? <Badge variant="outline">Manual build</Badge> : null}{run.pinned ? <Badge variant="secondary"><Pin />Pinned</Badge> : null}{run.archived ? <Badge variant="outline"><Archive />Archived</Badge> : null}{activeFolder === "all" && run.project_id && projectNames.has(run.project_id) ? <Badge variant="outline"><Folder />{projectNames.get(run.project_id)}</Badge> : null}{run.is_replay ? <ReplayBadge>{replayLabel(run)}</ReplayBadge> : null}{run.starter_id ? <Badge variant="outline">Supplied faulty starter</Badge> : null}{run.parent_run_id ? <Badge variant="outline">Follow-up</Badge> : null}</ItemTitle>
          <ItemDescription className="max-w-3xl">{run.spec_text}</ItemDescription>
        </ItemContent></Link>
        <ItemActions className="flex-wrap text-sm text-muted-foreground tabular-nums">{best ? <><span>{number(best.area_um2)} µm²</span><span>{number(best.wns_ns)} ns WNS</span></> : null}<StatusBadge status={run.status} /><RunActions run={run} /></ItemActions>
        <ItemFooter className="flex-wrap justify-start gap-x-3 text-xs text-muted-foreground"><span className="font-mono">{run.id.slice(0, 8)}</span><span>{new Date(run.created_at).toLocaleString()}</span><span>{run.stage}</span><span>{run.execution_mode === "manual" ? "No model calls" : <>{run.is_replay ? "Recorded " : ""}{run.cost_usd == null ? "cost unavailable" : `$${number(run.cost_usd, 4)}`}</>}</span>{run.is_replay ? <span title={source ?? run.recording_id ?? undefined}>{source ? `Source run ${source.slice(0, 8)}` : `Recording ${run.recording_id ?? "unavailable"}`}</span> : null}{run.is_replay ? <span>{usageLabel(run)}</span> : null}</ItemFooter>
      </Item>;
    })}</ItemGroup> : searching && visible.length > 0 ? <Empty className="min-h-64 border border-dashed" aria-live="polite"><EmptyHeader><EmptyTitle role="heading" aria-level={3}>No runs match “{query.trim()}”.</EmptyTitle><EmptyDescription>Search matches run names, specs, run IDs, status, and stage in this view.{view !== "all" ? " Try All runs to search everything." : ""}</EmptyDescription></EmptyHeader><EmptyContent><Button type="button" variant="outline" onClick={() => setQuery("")}>Clear search</Button></EmptyContent></Empty> : runs?.length && heading && !folderRuns.length ? <Empty className="min-h-64 border border-dashed" aria-live="polite"><EmptyHeader><EmptyTitle role="heading" aria-level={3}>{activeFolder === "unfiled" ? "Every run is in a project." : `No runs in ${heading} yet.`}</EmptyTitle><EmptyDescription>{activeFolder === "unfiled" ? "Move a run back here from its project, or delete a project to return its runs." : "Open All runs, then drag runs onto this folder or select them and use Move to."}</EmptyDescription></EmptyHeader><EmptyContent><Button type="button" variant="outline" onClick={() => selectFolder("all")}>Show all runs</Button></EmptyContent></Empty> : <Empty className="min-h-64 border border-dashed" aria-live="polite"><EmptyHeader><EmptyTitle role="heading" aria-level={3}>{!runs ? loading ? "Checking run history…" : "Run history could not be loaded." : view === "archived" ? "No archived runs." : runs.length ? "No runs in this view." : "No chip designs yet."}</EmptyTitle><EmptyDescription>{error ? "Use Refresh to try again." : view === "archived" ? "Archive a finished run to hide it from History without deleting its results." : runs?.length ? "Your saved runs are available in Archived or All runs." : "Your real tool runs will appear here."}</EmptyDescription></EmptyHeader>{view !== "archived" ? <EmptyContent><Button asChild variant="outline"><Link href="/">Start a new design <ArrowRight data-icon="inline-end" /></Link></Button></EmptyContent> : null}</Empty>}
      </TabsContent>
    </Tabs>
    </div>
  </section>;
}
