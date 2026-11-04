"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { History, Settings, SquarePen } from "lucide-react";
import { Logo } from "@/components/logo";
import { listRuns, type Run } from "@/lib/api";
import { Sidebar, SidebarContent, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarRail } from "@/components/ui/sidebar";
import { runName } from "@/components/run/format";

const links = [
  { href: "/", label: "New design", icon: SquarePen },
  { href: "/runs", label: "Run history", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppSidebar() {
  const pathname = usePathname();
  const [runs, setRuns] = useState<Run[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    // Refreshed on navigation so a newly queued run appears; failures leave the list empty.
    listRuns(controller.signal).then(setRuns).catch(() => undefined);
    return () => controller.abort();
  }, [pathname]);
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/">
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
                const current = href === "/" ? pathname === "/" : pathname === href;
                return <SidebarMenuItem key={href}><SidebarMenuButton asChild isActive={current} tooltip={label}><Link href={href} aria-current={current ? "page" : undefined}><Icon />{label}</Link></SidebarMenuButton></SidebarMenuItem>;
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        {runs.length ? <SidebarGroup className="group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel>Recent runs</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {runs.slice(0, 12).map((run) => <SidebarMenuItem key={run.id}><SidebarMenuButton asChild isActive={pathname.startsWith(`/runs/${run.id}`)}><Link href={`/runs/${run.id}`} title={run.spec_text}><span className={run.status === "done" ? "size-1.5 shrink-0 rounded-full bg-success" : run.status === "failed" ? "size-1.5 shrink-0 rounded-full bg-destructive" : "size-1.5 shrink-0 rounded-full bg-muted-foreground"} aria-hidden="true" /><span className="truncate">{runName(run)}</span></Link></SidebarMenuButton></SidebarMenuItem>)}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup> : null}
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  );
}
