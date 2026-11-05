"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Clapperboard, Folder, FolderOpen, History, Pin, Settings, SquarePen } from "lucide-react";
import { AppearanceMenu } from "@/components/appearance-menu";
import { Logo } from "@/components/logo";
import { useRunDrop } from "@/components/project-folders";
import { listRuns, type Project, type Run } from "@/lib/api";
import { writeRunDrag } from "@/lib/projects";
import { RUNS_CHANGED_EVENT } from "@/lib/run-history-events";
import { useProjects } from "@/lib/use-projects";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem, SidebarMenuSub, SidebarMenuSubButton, SidebarMenuSubItem, SidebarRail, useSidebar } from "@/components/ui/sidebar";
import { runName } from "@/components/run/format";

function SidebarProject({ project, runs, pathname, onNavigate }: { project: Project; runs: Run[]; pathname: string; onNavigate: () => void }) {
  const [open, setOpen] = useState(false);
  const { over, dropProps } = useRunDrop(project.id, project.name);
  return <Collapsible asChild open={open || over} onOpenChange={setOpen}>
    <SidebarMenuItem {...dropProps} data-testid={`sidebar-project-${project.id}`} className={over ? "rounded-md ring-2 ring-sidebar-ring" : undefined}>
      <CollapsibleTrigger asChild>
        <SidebarMenuButton tooltip={project.name} aria-label={`${project.name}, ${runs.length} run${runs.length === 1 ? "" : "s"}`}>
          {open ? <FolderOpen /> : <Folder />}<span className="truncate">{project.name}</span>
          <ChevronRight className={open ? "ml-auto rotate-90 transition-transform" : "ml-auto transition-transform"} />
        </SidebarMenuButton>
      </CollapsibleTrigger>
      {!open && runs.length ? <SidebarMenuBadge className="right-7">{runs.length}</SidebarMenuBadge> : null}
      <CollapsibleContent>
        <SidebarMenuSub>
          {runs.length ? runs.map((run) => <SidebarMenuSubItem key={run.id}>
            <SidebarMenuSubButton asChild isActive={pathname.startsWith(`/runs/${run.id}`)}>
              <Link href={`/runs/${run.id}`} onNavigate={onNavigate} title={run.spec_text} onDragStart={(event) => writeRunDrag(event.dataTransfer, [run.id])}><span>{runName(run)}</span></Link>
            </SidebarMenuSubButton>
          </SidebarMenuSubItem>) : <li className="px-2 py-1 text-xs text-muted-foreground">Drag runs here.</li>}
        </SidebarMenuSub>
      </CollapsibleContent>
    </SidebarMenuItem>
  </Collapsible>;
}

const links = [
  { href: "/", label: "New design", icon: SquarePen },
  { href: "/runs", label: "Run history", icon: History },
  { href: "/recordings", label: "Recorded runs", icon: Clapperboard },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppSidebar() {
  const pathname = usePathname();
  const { setOpenMobile } = useSidebar();
  const closeMobileNavigation = () => setOpenMobile(false);
  const [runs, setRuns] = useState<Run[]>([]);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const changed = () => setVersion((value) => value + 1);
    window.addEventListener(RUNS_CHANGED_EVENT, changed);
    return () => window.removeEventListener(RUNS_CHANGED_EVENT, changed);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    // Refreshed on navigation so a newly queued run appears; failures leave the list empty.
    listRuns(controller.signal).then((rows) => { if (!controller.signal.aborted) setRuns(rows); }).catch(() => undefined);
    return () => controller.abort();
  }, [pathname, version]);
  const { projects } = useProjects();
  const pinned = runs.filter((run) => run.pinned);
  // Filed runs live under their project folder instead of Recent.
  const recent = runs.filter((run) => !run.pinned && !run.archived && !run.project_id).slice(0, 12);
  return (
    <Sidebar collapsible="icon" className="[&>[data-slot=sidebar-inner]]:glass [&>[data-slot=sidebar-inner]]:bg-transparent [&>[data-slot=sidebar-inner]]:[--glass-blur:2px] [&>[data-slot=sidebar-inner]]:[--glass-tint:15%]">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/" onNavigate={closeMobileNavigation}>
                <span className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground"><Logo className="size-5" /></span>
                <span className="grid flex-1 text-left text-sm leading-tight"><span className="truncate font-semibold">Silicon Agent</span><span className="truncate text-xs text-muted-foreground">From an idea to silicon</span></span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup role="navigation" aria-label="Main navigation">
          <SidebarGroupContent>
            <SidebarMenu>
              {links.map(({ href, label, icon: Icon }) => {
                const current = pathname === href;
                const active = current || (href !== "/" && pathname.startsWith(`${href}/`));
                return <SidebarMenuItem key={href}><SidebarMenuButton asChild isActive={active} tooltip={label}><Link href={href} onNavigate={closeMobileNavigation} aria-current={current ? "page" : active ? "location" : undefined}><Icon />{label}</Link></SidebarMenuButton></SidebarMenuItem>;
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        {pinned.length ? <SidebarGroup role="navigation" aria-label="Pinned projects">
          <SidebarGroupLabel>Pinned projects</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>{pinned.map((run) => <SidebarMenuItem key={run.id}><SidebarMenuButton asChild isActive={pathname.startsWith(`/runs/${run.id}`)} tooltip={runName(run)}><Link href={`/runs/${run.id}`} onNavigate={closeMobileNavigation} title={runName(run)}><Pin /><span className="truncate">{runName(run)}</span></Link></SidebarMenuButton></SidebarMenuItem>)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup> : null}
        {projects?.length ? <SidebarGroup role="navigation" aria-label="Projects" className="group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel asChild><Link href="/runs" onNavigate={closeMobileNavigation}>Projects</Link></SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>{projects.map((project) => <SidebarProject key={project.id} project={project} runs={runs.filter((run) => run.project_id === project.id)} pathname={pathname} onNavigate={closeMobileNavigation} />)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup> : null}
        {recent.length ? <SidebarGroup className="group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel>Recent runs</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {recent.map((run) => <SidebarMenuItem key={run.id}><SidebarMenuButton asChild isActive={pathname.startsWith(`/runs/${run.id}`)}><Link href={`/runs/${run.id}`} onNavigate={closeMobileNavigation} title={run.spec_text} onDragStart={(event) => writeRunDrag(event.dataTransfer, [run.id])}><span className={run.status === "done" ? "size-1.5 shrink-0 rounded-full bg-success" : run.status === "failed" ? "size-1.5 shrink-0 rounded-full bg-destructive" : "size-1.5 shrink-0 rounded-full bg-muted-foreground"} aria-hidden="true" /><span className="truncate">{runName(run)}</span></Link></SidebarMenuButton></SidebarMenuItem>)}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup> : null}
      </SidebarContent>
      <SidebarFooter><AppearanceMenu /></SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
