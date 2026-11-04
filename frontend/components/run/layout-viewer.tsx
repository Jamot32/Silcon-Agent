"use client";

import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Hand, Maximize, Minus, Plus, Scan } from "lucide-react";
import type { Layout, Metric } from "@/lib/api";
import { boundsFromPoints, containedImageRect, imagePoint, projectedBounds, selectionBoundsError, type ImagePoint, type ImageRect, type LayoutRegionBounds, type LayoutRegionSelection } from "@/lib/layout-selection";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { number } from "./format";

type Props = {
  layout: Layout | null; metrics: Metric[]; runId: string; title?: string; className?: string;
  imageTestId?: string; emptyMessage?: string; variant?: "dashboard" | "result";
  onInspectRegion?: (selection: LayoutRegionSelection) => void;
};
type Drag = { pointerId: number; kind: "pan"; x: number; y: number; originX: number; originY: number }
  | { pointerId: number; kind: "select"; start: ImagePoint };
const boundFields = [["x0", "Left (%)"], ["y0", "Top (%)"], ["x1", "Right (%)"], ["y1", "Bottom (%)"]] as const;
const defaultBounds = { x0: "25", y0: "25", x1: "75", y1: "75" };
const percent = (value: number) => Number((value * 100).toFixed(3)).toString();

export function LayoutViewer(props: Props) {
  // A replacement render must not retain another image's coordinates, zoom, or pointer gesture.
  return <LayoutCanvas key={`${props.runId}:${props.layout?.run_tag ?? "none"}:${props.layout?.image_url ?? ""}`} {...props} />;
}

function LayoutCanvas({ layout, metrics, runId, title = "Layout viewer", className, imageTestId = "layout-image", emptyMessage = "A real GDS render appears after physical design completes.", variant = "dashboard", onInspectRegion }: Props) {
  const [zoom, setZoom] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [failedImage, setFailedImage] = useState("");
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const [contentRect, setContentRect] = useState<ImageRect | null>(null);
  const [mode, setMode] = useState<"pan" | "select">("pan");
  const [selection, setSelection] = useState<LayoutRegionBounds | null>(null);
  const [preview, setPreview] = useState<LayoutRegionBounds | null>(null);
  const [boundsDraft, setBoundsDraft] = useState(defaultBounds);
  const [draftDirty, setDraftDirty] = useState(false);
  const [selectionError, setSelectionError] = useState("");
  const drag = useRef<Drag | null>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const instructionsId = useId(), selectionId = useId();
  const clock = metrics.find((metric) => metric.run_tag === layout?.run_tag)?.clock_mhz;
  const loaded = !!layout && failedImage !== layout.image_url && !!imageSize;
  const selecting = !!onInspectRegion && mode === "select";
  const canPan = loaded && zoom > 1 && !selecting;
  const selectionTools = !!onInspectRegion && loaded && (selecting || !!selection);

  function currentImageRect() {
    const image = imageRef.current;
    return image ? containedImageRect(image.getBoundingClientRect(), image.naturalWidth, image.naturalHeight) : null;
  }
  useLayoutEffect(() => {
    const image = imageRef.current, frame = frameRef.current;
    if (!image || !frame) return;
    const measure = () => {
      if (!image.complete || !image.naturalWidth || !image.naturalHeight) return;
      setImageSize((current) => current?.width === image.naturalWidth && current.height === image.naturalHeight ? current : { width: image.naturalWidth, height: image.naturalHeight });
      const rect = containedImageRect(image.getBoundingClientRect(), image.naturalWidth, image.naturalHeight);
      if (!rect) return;
      const viewport = frame.getBoundingClientRect();
      const local = { ...rect, left: rect.left - viewport.left - frame.clientLeft, top: rect.top - viewport.top - frame.clientTop };
      setContentRect((current) => current && Object.keys(local).every((key) => current[key as keyof ImageRect] === local[key as keyof ImageRect]) ? current : local);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(image); observer.observe(frame);
    return () => observer.disconnect();
  }, [zoom, position.x, position.y, imageSize?.width, imageSize?.height, selectionTools, failedImage]);

  function stopDrag() { drag.current = null; setPreview(null); }
  function changeZoom(value: number) {
    stopDrag();
    const next = Math.min(8, Math.max(1, value));
    setZoom(next);
    if (next === 1) setPosition({ x: 0, y: 0 });
  }
  function commitSelection(bounds: LayoutRegionBounds) {
    const error = selectionBoundsError(bounds, imageSize?.width ?? 0, imageSize?.height ?? 0);
    setSelectionError(error ?? "");
    if (error) return;
    setSelection(bounds);
    setBoundsDraft({ x0: percent(bounds.x0), y0: percent(bounds.y0), x1: percent(bounds.x1), y1: percent(bounds.y1) });
    setDraftDirty(false);
  }
  function start(event: PointerEvent<HTMLDivElement>) {
    if (!loaded || drag.current || event.button !== 0) return;
    if (selecting) {
      const point = imagePoint({ x: event.clientX, y: event.clientY }, currentImageRect());
      if (!point) return;
      drag.current = { kind: "select", pointerId: event.pointerId, start: point };
      setPreview(boundsFromPoints(point, point));
      setSelectionError("");
    } else if (canPan) drag.current = { kind: "pan", pointerId: event.pointerId, x: event.clientX, y: event.clientY, originX: position.x, originY: position.y };
    else return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    if (active.kind === "pan") setPosition({ x: active.originX + event.clientX - active.x, y: active.originY + event.clientY - active.y });
    else {
      const point = imagePoint({ x: event.clientX, y: event.clientY }, currentImageRect(), true);
      if (point) setPreview(boundsFromPoints(active.start, point));
    }
  }
  function finish(event: PointerEvent<HTMLDivElement>) {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    if (active.kind === "select") {
      const point = imagePoint({ x: event.clientX, y: event.clientY }, currentImageRect(), true);
      if (point) commitSelection(boundsFromPoints(active.start, point));
    }
    stopDrag();
  }
  function pan(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && drag.current) { event.preventDefault(); stopDrag(); return; }
    if (!canPan || event.altKey || event.ctrlKey || event.metaKey) return;
    const offset = { ArrowLeft: [-40, 0], ArrowRight: [40, 0], ArrowUp: [0, -40], ArrowDown: [0, 40] }[event.key];
    if (!offset) return;
    event.preventDefault();
    setPosition((current) => ({ x: current.x + offset[0], y: current.y + offset[1] }));
  }
  function applyBounds() {
    const value = (key: keyof LayoutRegionBounds) => boundsDraft[key].trim() === "" ? NaN : Number(boundsDraft[key]) / 100;
    commitSelection({ x0: value("x0"), y0: value("y0"), x1: value("x1"), y1: value("y1") });
  }
  const drawn = preview ?? selection;
  const overlay = drawn && contentRect ? projectedBounds(drawn, contentRect) : null;
  const result = variant === "result";
  return <Card role="region" className={cn("min-w-0 gap-0 py-0", result && "flex h-[580px] flex-col max-lg:h-auto", result && selectionTools && "h-auto", className)} id="final-layout" aria-labelledby="layout-title">
    <header className={cn("flex flex-wrap items-center justify-between gap-3 px-4 py-2.5", result && "py-4")}><div className={cn("flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1", result && "flex-col items-start")}><CardTitle id="layout-title" role="heading" aria-level={2} className={result ? "text-lg" : undefined}>{title}</CardTitle>{result ? null : <span className="text-xs text-muted-foreground">Run: {runId.slice(0, 8)}</span>}{layout ? <span className={cn("layout-tag max-w-full truncate font-mono text-xs text-muted-foreground", !result && "border-l pl-4")} title={layout.run_tag}>{layout.run_tag}{clock != null ? ` · ${number(clock)} MHz target` : ""}</span> : null}</div><div className="flex flex-wrap items-center gap-1.5"><Button variant="outline" size="icon-sm" aria-label="Zoom out layout" onClick={() => changeZoom(zoom / 1.25)} disabled={!layout || zoom <= 1}><Minus /></Button>{result ? null : <span className="w-10 text-center text-xs text-muted-foreground tabular-nums">{Math.round(zoom * 100)}%</span>}<Button variant="outline" size="icon-sm" aria-label="Zoom in layout" onClick={() => changeZoom(zoom * 1.25)} disabled={!layout || zoom >= 8}><Plus /></Button><Button variant="outline" size="sm" onClick={() => changeZoom(1)} disabled={!layout}><Maximize data-icon="inline-start" />Fit</Button></div></header>
    {onInspectRegion ? <div role="group" aria-label="Layout interaction" className="flex flex-wrap gap-2 px-4 pb-3"><Button variant={selecting ? "outline" : "secondary"} size="sm" aria-pressed={!selecting} onClick={() => { stopDrag(); setMode("pan"); }}><Hand data-icon="inline-start" />Pan</Button><Button variant={selecting ? "secondary" : "outline"} size="sm" aria-pressed={selecting} disabled={!loaded} onClick={() => { stopDrag(); setMode("select"); }}><Scan data-icon="inline-start" />Select region</Button></div> : null}
    <div ref={frameRef} role="group" aria-label="Layout image" aria-describedby={layout ? instructionsId : undefined} tabIndex={canPan || (selecting && loaded) ? 0 : undefined} className={cn("relative mx-4 mb-4 flex items-center justify-center overflow-hidden rounded-lg border bg-black/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring", result ? selectionTools ? "h-96 min-h-80 flex-none" : "min-h-80 flex-1 max-lg:h-96 max-lg:flex-none" : "h-72 border-dashed", canPan && "cursor-grab touch-none active:cursor-grabbing", selecting && loaded && "touch-none cursor-crosshair")} onKeyDown={pan} onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={stopDrag} onLostPointerCapture={stopDrag}>
      {layout && failedImage !== layout.image_url ? <img ref={imageRef} data-testid={imageTestId} src={layout.image_url} alt={`Real sky130 GDS layout for ${layout.run_tag}`} draggable={false} className="h-[calc(100%-24px)] w-[calc(100%-24px)] origin-center object-contain select-none" style={{ transform: `translate(${position.x}px, ${position.y}px) scale(${zoom})` }} onLoad={(event) => setImageSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} onError={() => { setFailedImage(layout.image_url); setImageSize(null); setSelection(null); stopDrag(); }} /> : <p className="p-5 text-center text-sm text-muted-foreground">{layout ? "The recorded layout image could not be loaded." : emptyMessage}</p>}
      {overlay ? <div data-testid="layout-region-overlay" aria-hidden="true" className="pointer-events-none absolute border-2 border-sky-300 bg-sky-400/15 ring-1 ring-black/70" style={overlay} /> : null}
      {layout ? <span id={instructionsId} className="pointer-events-none absolute right-3 bottom-2 left-3 w-fit max-w-[calc(100%-24px)] rounded-md bg-background/85 px-1.5 py-0.5 text-[10px] text-muted-foreground">sky130A · Real GDS render · {selecting ? "Drag a rectangle, or enter bounds below" : canPan ? "Drag or use arrow keys to pan" : "Zoom in to pan"}</span> : null}
    </div>
    {selectionTools ? <div className="space-y-3 border-t px-4 py-3">
      <p className="text-xs text-muted-foreground" aria-live="polite">{selection ? `Selected image region: left ${percent(selection.x0)}%, top ${percent(selection.y0)}%, right ${percent(selection.x1)}%, bottom ${percent(selection.y1)}%.` : "Draw a rectangle on the image, or enter percentage bounds. Minimum region: 4 × 4 image pixels."}</p>
      <details className="rounded-lg border p-3"><summary className="cursor-pointer rounded-sm text-sm focus-visible:outline-2 focus-visible:outline-ring">Enter region bounds</summary><p id={`${selectionId}-help`} className="mt-2 text-xs text-muted-foreground">Percentages of the original image, measured from the top-left corner.</p><div className="mt-3 grid grid-cols-2 gap-3">{boundFields.map(([key, label]) => <div key={key} className="grid gap-1.5"><Label htmlFor={`${selectionId}-${key}`} className="text-xs">{label}</Label><Input id={`${selectionId}-${key}`} type="number" min="0" max="100" step="any" value={boundsDraft[key]} aria-describedby={`${selectionId}-help`} onChange={(event) => { stopDrag(); setBoundsDraft({ ...boundsDraft, [key]: event.target.value }); setDraftDirty(true); setSelectionError(""); }} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); applyBounds(); } }} /></div>)}</div><Button className="mt-3" variant="outline" size="sm" onClick={applyBounds}>Apply bounds</Button></details>
      {selectionError ? <p role="alert" className="text-xs text-destructive">{selectionError}</p> : null}
      {draftDirty ? <p className="text-xs text-muted-foreground">Apply the edited bounds before asking about the region.</p> : null}
      <div className="flex flex-wrap gap-2"><Button size="sm" disabled={!selection || !!preview || draftDirty} onClick={() => { if (layout && selection && imageSize) onInspectRegion?.({ run_tag: layout.run_tag, image_url: layout.image_url, bounds: { ...selection }, image_width: imageSize.width, image_height: imageSize.height }); }}>Ask about region</Button><Button variant="outline" size="sm" disabled={!selection && !preview && !draftDirty} onClick={() => { stopDrag(); setSelection(null); setBoundsDraft(defaultBounds); setDraftDirty(false); setSelectionError(""); }}>Clear region</Button></div>
    </div> : null}
  </Card>;
}
