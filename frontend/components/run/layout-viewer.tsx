"use client";

import { useRef, useState, type PointerEvent } from "react";
import { Minus, Plus } from "lucide-react";
import type { Layout, Metric } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { number } from "./format";

export function LayoutViewer({ layout, metrics, runId, title = "Layout viewer", className, imageTestId = "layout-image", emptyMessage = "A real GDS render appears after physical design completes." }: { layout: Layout | null; metrics: Metric[]; runId: string; title?: string; className?: string; imageTestId?: string; emptyMessage?: string }) {
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
  return <section className={cn("instrument-panel layout-panel", className)} id="final-layout" aria-labelledby="layout-title">
    <header className="layout-header"><div className="layout-heading"><h2 id="layout-title">{title}</h2><span>Run: {runId.slice(0, 8)}</span>{layout ? <span className="layout-tag" title={layout.run_tag}>{layout.run_tag}{clock != null ? ` · ${number(clock)} MHz target` : ""}</span> : null}</div><div className="layout-controls"><Button variant="outline" size="icon-sm" aria-label="Zoom out layout" onClick={() => changeZoom(zoom / 1.25)} disabled={!layout || zoom <= 1}><Minus /></Button><span className="zoom-value">{Math.round(zoom * 100)}%</span><Button variant="outline" size="icon-sm" aria-label="Zoom in layout" onClick={() => changeZoom(zoom * 1.25)} disabled={!layout || zoom >= 8}><Plus /></Button><Button variant="outline" size="sm" onClick={() => { setZoom(1); setPosition({ x: 0, y: 0 }); }} disabled={!layout}>Fit</Button></div></header>
    <div className={layout ? "layout-canvas has-layout" : "layout-canvas"} onPointerDown={start} onPointerMove={move} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
      {layout && failedImage !== layout.image_url ? <img data-testid={imageTestId} src={layout.image_url} alt={`Real sky130 GDS layout for ${layout.run_tag}`} draggable={false} style={{ transform: `translate(${position.x}px, ${position.y}px) scale(${zoom})` }} onError={() => setFailedImage(layout.image_url)} /> : <p>{layout ? "The recorded layout image could not be loaded." : emptyMessage}</p>}
      {layout ? <span className="canvas-caption">sky130A · Real GDS render · Drag to pan</span> : null}
    </div>
  </section>;
}
