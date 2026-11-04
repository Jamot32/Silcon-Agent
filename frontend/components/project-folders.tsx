"use client";

import { useId, useState, type DragEvent, type ReactNode } from "react";
import { Ellipsis, Folder, FolderOpen, FolderPlus, Inbox, Layers, Trash2 } from "lucide-react";
import { createProject, deleteProject, renameProject, type Project, type Run } from "@/lib/api";
import { inFolder, isRunDrag, readRunDrag, type ProjectFolder } from "@/lib/projects";
import { notifyRunsChanged } from "@/lib/run-history-events";
import { moveRunsToProject } from "@/lib/use-projects";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "cn";

const plural = (count: number) => `${count} run${count === 1 ? "" : "s"}`;

/** Drop target for dragged run rows; projectId null returns runs to Unfiled. */
export function useRunDrop(projectId: string | null, destination: string, onMessage?: (message: string) => void) {
  const [over, setOver] = useState(false);
  return {
    over,
    dropProps: {
      onDragOver(event: DragEvent<HTMLElement>) {
        if (!isRunDrag(event.dataTransfer)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        setOver(true);
      },
      onDragLeave(event: DragEvent<HTMLElement>) {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false);
      },
      onDrop(event: DragEvent<HTMLElement>) {
        setOver(false);
        if (!isRunDrag(event.dataTransfer)) return;
        event.preventDefault();
        const ids = readRunDrag(event.dataTransfer);
        if (!ids.length) return;
        moveRunsToProject(ids, projectId).then(
          (moved) => onMessage?.(`${plural(moved)} moved to ${destination}.`),
          (reason: unknown) => onMessage?.(`Runs could not be moved. ${reason instanceof Error ? reason.message : ""}`.trim()),
        );
      },
    },
  };
}

function FolderButton({ label, count, icon: Icon, selected, projectId, droppable, onSelect, onMessage, children }: {
  label: string; count: number; icon: typeof Folder; selected: boolean; projectId: string | null; droppable: boolean;
  onSelect: () => void; onMessage: (message: string) => void; children?: ReactNode;
}) {
  const { over, dropProps } = useRunDrop(projectId, label, onMessage);
  return <li className={cn("group/folder flex items-center gap-1 rounded-md", over && "bg-accent ring-2 ring-ring")} {...(droppable ? dropProps : {})} data-testid={`project-folder-${projectId ?? label.toLowerCase().replace(/\s+/g, "-")}`}>
    <button type="button" onClick={onSelect} aria-current={selected ? "true" : undefined} className={cn("flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring", selected && "bg-accent font-medium")}>
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className="text-xs text-muted-foreground tabular-nums" aria-label={plural(count)}>{count}</span>
    </button>
    {children}
  </li>;
}

function ProjectMenu({ project, count, onDeleted }: { project: Project; count: number; onDeleted: () => void }) {
  const inputId = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(project.name);
  const [pending, setPending] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState("");
  const dirty = name.trim() !== "" && name.trim() !== project.name;
  async function act(action: () => Promise<unknown>, after?: () => void) {
    if (pending) return;
    setPending(true); setError("");
    try { await action(); setOpen(false); after?.(); notifyRunsChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "The project could not be updated."); }
    finally { setPending(false); }
  }
  return <Popover open={open} onOpenChange={(value) => { if (pending) return; setOpen(value); setConfirmDelete(false); setError(""); if (value) setName(project.name); }}>
    <PopoverTrigger asChild><Button type="button" variant="ghost" size="icon-sm" className="opacity-0 group-hover/folder:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100" aria-label={`Manage project ${project.name}`}><Ellipsis /></Button></PopoverTrigger>
    <PopoverContent align="start" className="w-72 gap-4">
      <PopoverHeader><PopoverTitle>Manage project</PopoverTitle><PopoverDescription>Projects only group runs. Each run keeps its own files and results.</PopoverDescription></PopoverHeader>
      <form onSubmit={(event) => { event.preventDefault(); if (dirty) void act(() => renameProject(project.id, name.trim())); }}>
        <FieldGroup>
          <Field data-disabled={pending}><FieldLabel htmlFor={inputId}>Project name</FieldLabel><Input id={inputId} value={name} maxLength={80} disabled={pending} onChange={(event) => { setName(event.target.value); setError(""); }} /></Field>
          <Button type="submit" size="sm" disabled={pending || !dirty}>Save name</Button>
        </FieldGroup>
      </form>
      <Separator />
      {confirmDelete ? <Alert variant="destructive"><AlertDescription className="gap-3">
        <p className="wrap-anywhere">Delete “{project.name}”? Its {plural(count)} move back to Unfiled. No run is deleted.</p>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" disabled={pending} onClick={() => setConfirmDelete(false)}>Keep project</Button>
          <Button type="button" variant="destructive" size="sm" disabled={pending} onClick={() => void act(() => deleteProject(project.id), onDeleted)}>{pending ? <Spinner data-icon="inline-start" /> : <Trash2 data-icon="inline-start" />}Delete project</Button>
        </div>
      </AlertDescription></Alert> : <Button type="button" variant="outline" disabled={pending} onClick={() => setConfirmDelete(true)}><Trash2 data-icon="inline-start" />Delete project…</Button>}
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
    </PopoverContent>
  </Popover>;
}

function NewProject({ onCreated }: { onCreated: (project: Project) => void }) {
  const inputId = useId();
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function create() {
    if (pending || !name.trim()) return;
    setPending(true); setError("");
    try { const project = await createProject(name.trim()); setName(""); notifyRunsChanged(); onCreated(project); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "The project could not be created."); }
    finally { setPending(false); }
  }
  return <form className="flex flex-col gap-2" onSubmit={(event) => { event.preventDefault(); void create(); }}>
    <Field data-disabled={pending}>
      <FieldLabel htmlFor={inputId} className="sr-only">New project name</FieldLabel>
      <div className="flex gap-2">
        <Input id={inputId} value={name} maxLength={80} disabled={pending} placeholder="New project" onChange={(event) => { setName(event.target.value); setError(""); }} />
        <Button type="submit" variant="outline" size="icon" disabled={pending || !name.trim()} aria-label="Create project">{pending ? <Spinner /> : <FolderPlus />}</Button>
      </div>
      {error ? <FieldDescription className="text-destructive">{error}</FieldDescription> : null}
    </Field>
  </form>;
}

export function ProjectFolders({ runs, projects, folder, onSelect, onMessage }: {
  runs: Run[]; projects: Project[]; folder: ProjectFolder; onSelect: (folder: ProjectFolder) => void; onMessage: (message: string) => void;
}) {
  const count = (target: ProjectFolder) => runs.filter((run) => inFolder(run, target)).length;
  return <nav aria-label="Project folders" className="flex flex-col gap-3">
    <ul className="flex flex-col gap-0.5">
      <FolderButton label="All runs" icon={Layers} count={runs.length} selected={folder === "all"} projectId={null} droppable={false} onSelect={() => onSelect("all")} onMessage={onMessage} />
      <FolderButton label="Unfiled" icon={Inbox} count={count("unfiled")} selected={folder === "unfiled"} projectId={null} droppable onSelect={() => onSelect("unfiled")} onMessage={onMessage} />
    </ul>
    <div className="flex flex-col gap-1">
      <h3 className="px-2 text-xs font-medium text-muted-foreground">Projects</h3>
      {projects.length ? <ul className="flex flex-col gap-0.5">{projects.map((project) => <FolderButton key={project.id} label={project.name} icon={folder === project.id ? FolderOpen : Folder} count={count(project.id)} selected={folder === project.id} projectId={project.id} droppable onSelect={() => onSelect(project.id)} onMessage={onMessage}>
        <ProjectMenu project={project} count={count(project.id)} onDeleted={() => { if (folder === project.id) onSelect("unfiled"); onMessage(`Project “${project.name}” deleted. Its runs are in Unfiled.`); }} />
      </FolderButton>)}</ul> : <p className="px-2 text-xs text-muted-foreground">No projects yet. Create one, then drag runs onto it or select runs and use Move to.</p>}
    </div>
    <NewProject onCreated={(project) => { onSelect(project.id); onMessage(`Project “${project.name}” created.`); }} />
  </nav>;
}
