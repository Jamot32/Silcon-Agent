"use client";

import { useRef, useState, type PointerEvent } from "react";
import { Maximize, Minus, Plus } from "lucide-react";
import type { Layout, Metric } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { number } from "./format";

export function LayoutViewer({ layout, metrics, runId, title = "Layout viewer", className, imageTestId = "layout-image", emptyMessage = "A real GDS render appears after physical design completes.", variant = "dashboard" }: { layout: Layout | null; metrics: Metric[]; runId: string; title?: string; className?: string; imageTestId?: string; emptyMessage?: string; variant?: "dashboard" | "result" }) {
  const [zoom, setZoom] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [failedImage, setFailedImage] = useState("");
  const drag = useRef<{ x: number; y: number; originX: number; originY: number } | null>(null);
  const clock = metrics.find((metric) => metric.run_tag === layout?.run_tag)?.clock_mhz;
  function changeZoom(value: number) { setZoom(Math.min(8, Math.max(1, value))); }
  function start(event: PointerEvent<HTMLDivElement>) {
    if (!layout) return;
    drag.current = { x: event.clientX, y: event.clientY, originX: position.x, originY: position.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    if (drag.current) setPosition({ x: drag.current.originX + event.clientX - drag.current.x, y: drag.current.originY + event.clientY - drag.current.y });
  }
  const result = variant === "result";
  return <Card role="region" className={cn("min-w-0 gap-0 py-0", result && "flex h-[580px] flex-col max-lg:h-auto", className)} id="final-layout" aria-labelledby="layout-title">
    <header className={cn("flex flex-wrap items-center justify-between gap-3 px-4 py-2.5", result && "py-4")}><div className={cn("flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1", result && "flex-col items-start")}><CardTitle id="layout-title" role="heading" aria-level={2} className={result ? "text-lg" : undefined}>{title}</CardTitle>{result ? null : <span className="text-xs text-muted-foreground">Run: {runId.slice(0, 8)}</span>}{layout ? <span className={cn("layout-tag max-w-full truncate font-mono text-xs text-muted-foreground", !result && "border-l pl-4")} title={layout.run_tag}>{layout.run_tag}{clock != null ? ` · ${number(clock)} MHz target` : ""}</span> : null}</div><div className="flex shrink-0 items-center gap-1.5"><Button variant="outline" size="icon-sm" aria-label="Zoom out layout" onClick={() => changeZoom(zoom / 1.25)} disabled={!layout || zoom <= 1}><Minus /></Button>{result ? null : <span className="w-10 text-center text-xs text-muted-foreground tabular-nums">{Math.round(zoom * 100)}%</span>}<Button variant="outline" size="icon-sm" aria-label="Zoom in layout" onClick={() => changeZoom(zoom * 1.25)} disabled={!layout || zoom >= 8}><Plus /></Button><Button variant="outline" size="sm" onClick={() => { setZoom(1); setPosition({ x: 0, y: 0 }); }} disabled={!layout}><Maximize data-icon="inline-start" />Fit</Button></div></header>
    <div className={cn("relative mx-4 mb-4 flex items-center justify-center overflow-hidden rounded-lg border bg-black/40", result ? "min-h-80 flex-1 max-lg:h-96 max-lg:flex-none" : "h-72 border-dashed", layout && "cursor-grab touch-none active:cursor-grabbing")} onPointerDown={start} onPointerMove={move} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
      {layout && failedImage !== layout.image_url ? <img data-testid={imageTestId} src={layout.image_url} alt={`Real sky130 GDS layout for ${layout.run_tag}`} draggable={false} className="h-[calc(100%-24px)] w-auto max-w-none origin-center object-contain select-none" style={{ transform: `translate(${position.x}px, ${position.y}px) scale(${zoom})` }} onError={() => setFailedImage(layout.image_url)} /> : <p className="p-5 text-center text-sm text-muted-foreground">{layout ? "The recorded layout image could not be loaded." : emptyMessage}</p>}
      {layout ? <span className="pointer-events-none absolute bottom-2 left-3 rounded-md bg-background/85 px-1.5 py-0.5 text-[10px] text-muted-foreground">sky130A · Real GDS render · Drag to pan</span> : null}
    </div>
  </Card>;
}
