"use client";

// EXPERIMENT (revert freely): animated canvas behind the main content. The previewed orchestrator's provider picks
// the effect, the model name varies its density and speed, and the pointer pushes the motion aside.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Pointer = { x: number; y: number; on: boolean };
type P = { x: number; y: number; vx: number; vy: number; hx: number; hy: number; a: number; r: number };
type World = { w: number; h: number; t: number; m: Pointer; density: number; speed: number };
type Draw = (ctx: CanvasRenderingContext2D) => void;
type Effect = { color: string; alpha: number; trail?: number; make: (world: World) => Draw };

const TAU = Math.PI * 2;
const rnd = (min = 0, max = 1) => min + Math.random() * (max - min);
const particle = (x: number, y: number, a = 0, r = 0): P => ({ x, y, vx: 0, vy: 0, hx: x, hy: y, a, r });
const many = (world: World, area: number, make: () => P) => Array.from({ length: Math.round(world.w * world.h / area * world.density) }, make);

function repel(p: P, m: Pointer, force: number, radius = 150) {
  if (!m.on) return;
  const dx = p.x - m.x, dy = p.y - m.y, d = Math.hypot(dx, dy);
  if (d >= radius || d === 0) return;
  const f = (1 - d / radius) * force;
  p.vx += dx / d * f; p.vy += dy / d * f;
}
function spring(p: P, k: number, damp: number) {
  p.vx = (p.vx + (p.hx - p.x) * k) * damp; p.vy = (p.vy + (p.hy - p.y) * k) * damp;
  p.x += p.vx; p.y += p.vy;
}
function steer(p: P, tx: number, ty: number, k: number) { p.vx += (tx - p.vx) * k; p.vy += (ty - p.vy) * k; }
function move(p: P) { p.x += p.vx; p.y += p.vy; }
// Returns true when the particle jumped edges, so callers skip drawing a segment across the screen.
function wrap(p: P, w: number, h: number, pad = 10) {
  const x = p.x, y = p.y;
  if (p.x < -pad) p.x = w + pad; else if (p.x > w + pad) p.x = -pad;
  if (p.y < -pad) p.y = h + pad; else if (p.y > h + pad) p.y = -pad;
  return x !== p.x || y !== p.y;
}
const dot = (ctx: CanvasRenderingContext2D, x: number, y: number, r: number) => { ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, TAU); };
// Grid of resting points (a, r hold the rest position); hex offsets odd rows for a honeycomb.
function gridPoints(world: World, gap: number, hex = false) {
  const ps: P[] = [];
  for (let row = 0, y = gap / 2; y < world.h + gap; row++, y += hex ? gap * 0.866 : gap)
    for (let x = gap / 2 + (hex && row % 2 ? gap / 2 : 0); x < world.w + gap; x += gap) ps.push(particle(x, y, x, y));
  return ps;
}
const displaced = (p: P, max: number) => Math.min(Math.hypot(p.x - p.hx, p.y - p.hy), max) / max;

// OpenAI: a honeycomb of hexagons pulsing in a travelling wave; pushed cells shrink and turn.
const hexes: Effect = { color: "oklch(0.72 0.15 165)", alpha: 0.55, make: (world) => {
  const gap = 34 / Math.sqrt(world.density), ps = gridPoints(world, gap, true);
  return (ctx) => {
    const { t, m, speed } = world;
    ctx.beginPath();
    for (const p of ps) {
      repel(p, m, 3, 160); spring(p, 0.07, 0.8);
      const push = displaced(p, 30), wave = 0.5 + 0.5 * Math.sin(p.a * 0.008 + p.r * 0.006 - t * speed * 1.2);
      const size = gap * (0.18 + wave * 0.22 - push * 0.15), turn = t * 0.2 + push * 1.5;
      for (let k = 0; k <= 6; k++) {
        const angle = k * TAU / 6 + turn, x = p.x + Math.cos(angle) * size, y = p.y + Math.sin(angle) * size;
        if (k) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      }
    }
    ctx.stroke();
  };
} };

// Anthropic: drifting nodes linked to their neighbours.
const constellation: Effect = { color: "oklch(0.72 0.15 45)", alpha: 0.6, make: (world) => {
  const ps = many(world, 14000, () => { const p = particle(rnd(0, world.w), rnd(0, world.h)); p.a = rnd(-0.3, 0.3); p.r = rnd(-0.3, 0.3); return p; });
  return (ctx) => {
    const { m, speed, w, h } = world, alpha = ctx.globalAlpha;
    ctx.beginPath();
    for (const p of ps) { steer(p, p.a * speed, p.r * speed, 0.02); repel(p, m, 0.5); move(p); wrap(p, w, h); dot(ctx, p.x, p.y, 1.6); }
    ctx.fill();
    ctx.lineWidth = 0.8;
    for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++) {
      const d = Math.hypot(ps[i].x - ps[j].x, ps[i].y - ps[j].y);
      if (d > 120) continue;
      ctx.globalAlpha = alpha * (1 - d / 120);
      ctx.beginPath(); ctx.moveTo(ps[i].x, ps[i].y); ctx.lineTo(ps[j].x, ps[j].y); ctx.stroke();
    }
  };
} };

// Gemini: a sunflower spiral of dots in the logo's blue-violet-pink sweep, slowly turning; the pointer parts it.
const spiral: Effect = { color: "oklch(0.72 0.16 265)", alpha: 0.6, make: (world) => {
  const { w, h } = world, n = Math.round(w * h / 280 * world.density), reach = Math.hypot(w, h) * 0.6 / Math.sqrt(n);
  const ps = Array.from({ length: n }, (_, i) => particle(w / 2, h * 0.42, i, Math.sqrt(i)));
  let fill: CanvasGradient | undefined;
  return (ctx) => {
    const { t, m, speed } = world, cx = w / 2, cy = h * 0.42;
    if (!fill) {
      fill = ctx.createConicGradient(0, cx, cy);
      fill.addColorStop(0, "oklch(0.7 0.17 255)"); fill.addColorStop(0.35, "oklch(0.68 0.2 295)"); fill.addColorStop(0.65, "oklch(0.72 0.18 350)"); fill.addColorStop(1, "oklch(0.7 0.17 255)");
    }
    ctx.fillStyle = fill;
    ctx.beginPath();
    for (const p of ps) {
      const angle = p.a * 2.39996 + t * speed * 0.05, radius = reach * p.r * (1 + Math.sin(t * speed * 0.8 - p.r * 0.15) * 0.03);
      p.hx = cx + Math.cos(angle) * radius; p.hy = cy + Math.sin(angle) * radius;
      repel(p, m, 3, 160); spring(p, 0.06, 0.82);
      dot(ctx, p.x, p.y, 0.9 + p.r / Math.sqrt(n) * 2.4);
    }
    ctx.fill();
  };
} };

// Meta: a breathing dot grid that parts around the pointer and springs back.
const grid: Effect = { color: "oklch(0.68 0.19 250)", alpha: 0.6, make: (world) => {
  const gap = 30 / Math.sqrt(world.density), ps: P[] = [];
  for (let y = gap / 2; y < world.h; y += gap) for (let x = gap / 2; x < world.w; x += gap) ps.push(particle(x, y, x, y));
  return (ctx) => {
    const { t, m, speed } = world;
    ctx.beginPath();
    for (const p of ps) {
      p.hx = p.a + Math.sin(t * speed + p.r * 0.015) * 5; p.hy = p.r + Math.cos(t * speed * 0.8 + p.a * 0.015) * 5;
      repel(p, m, 3.5); spring(p, 0.07, 0.8);
      dot(ctx, p.x, p.y, 1.1 + Math.min(Math.hypot(p.x - p.hx, p.y - p.hy), 40) * 0.05);
    }
    ctx.fill();
  };
} };

// Taskfit (Arkinous): a halftone dot screen whose dot sizes drift like clouds; the pointer clears a hole.
const halftone: Effect = { color: "oklch(0.7 0.19 300)", alpha: 0.32, make: (world) => {
  const gap = 18 / Math.sqrt(world.density), ps = gridPoints(world, gap);
  return (ctx) => {
    const { t, m, speed } = world;
    ctx.beginPath();
    for (const p of ps) {
      repel(p, m, 3, 150); spring(p, 0.07, 0.8);
      const cloud = Math.sin(p.a * 0.006 + t * speed * 0.5) * Math.cos(p.r * 0.007 - t * speed * 0.4) + Math.sin((p.a + p.r) * 0.004 + t * speed * 0.3);
      const radius = (cloud + 2) / 4 * gap * 0.42 * (1 - displaced(p, 30));
      if (radius > 0.3) dot(ctx, p.x, p.y, radius);
    }
    ctx.fill();
  };
} };

// Kimi: full-width terminal rain; glyph trails bend around the pointer.
const glyphs = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ0123456789";
const rain: Effect = { color: "oklch(0.8 0.09 240)", alpha: 0.75, trail: 0.06, make: (world) => {
  const size = 16, drops = Array.from({ length: Math.ceil(world.w / size) }, (_, i) => particle(i * size + size / 2, rnd(-world.h, world.h), rnd(0.3, 0.7)));
  return (ctx) => {
    const { m, speed, h } = world;
    ctx.font = `${size - 2}px ui-monospace, monospace`; ctx.textAlign = "center";
    for (const p of drops) {
      p.r += p.a * speed;
      if (p.r < 1) continue;
      p.r -= 1; p.y += size;
      if (p.y > h + size && Math.random() > 0.96) { p.y = -size; p.a = rnd(0.3, 0.7); }
      let x = p.x, y = p.y;
      const dx = x - m.x, dy = y - m.y, d = Math.hypot(dx, dy);
      if (m.on && d < 160 && d > 0) { const push = (1 - d / 160) * 70; x += dx / d * push; y += dy / d * push * 0.4; }
      ctx.fillText(glyphs[Math.floor(Math.random() * glyphs.length)], x, y);
    }
  };
} };

// Qwen: wobbling bubbles rising from the bottom.
const bubbles: Effect = { color: "oklch(0.7 0.18 285)", alpha: 0.55, make: (world) => {
  const ps = many(world, 12000, () => particle(rnd(0, world.w), rnd(0, world.h), rnd(0, TAU), rnd(2, 7)));
  return (ctx) => {
    const { t, m, speed, w, h } = world;
    ctx.beginPath();
    for (const p of ps) {
      steer(p, Math.sin(t * 1.4 + p.a) * 0.4, -(0.3 + p.r * 0.09) * speed, 0.05); repel(p, m, 1.2); move(p);
      if (p.y < -10) { p.y = h + 10; p.x = rnd(0, w); }
      wrap(p, w, h + 20);
      dot(ctx, p.x, p.y, p.r);
    }
    ctx.stroke();
  };
} };

// DeepSeek: dense wobbling rings filling the screen from one source, dented by the pointer.
const ripples: Effect = { color: "oklch(0.65 0.19 265)", alpha: 0.65, make: (world) => {
  const rings = 28, points = 140, last = new Array<number>(rings).fill(0), ps: P[] = [];
  for (let ring = 0; ring < rings; ring++) for (let k = 0; k < points; k++) ps.push(particle(world.w / 2, world.h * 0.4, k / points * TAU, ring));
  return (ctx) => {
    const { t, m, speed, w, h } = world, alpha = ctx.globalAlpha, max = Math.hypot(w, h) * 0.65;
    for (let ring = 0; ring < rings; ring++) {
      const frac = (ring / rings + t * 0.02 * speed) % 1, radius = frac * max, reset = radius < last[ring];
      last[ring] = radius;
      ctx.globalAlpha = alpha * Math.min(1, frac * 6) * (1 - frac * 0.6);
      ctx.beginPath();
      for (let k = 0; k < points; k++) {
        const p = ps[ring * points + k], wobble = radius + Math.sin(p.a * 6 + t * speed + ring) * radius * 0.03;
        p.hx = w / 2 + Math.cos(p.a) * wobble; p.hy = h * 0.4 + Math.sin(p.a) * wobble;
        if (reset) { p.x = p.hx; p.y = p.hy; p.vx = p.vy = 0; }
        repel(p, m, 3, 170); spring(p, 0.1, 0.8);
        if (k) ctx.lineTo(p.x, p.y); else ctx.moveTo(p.x, p.y);
      }
      ctx.closePath(); ctx.stroke();
    }
  };
} };

// xAI: an accretion disk of dots spiralling into a dark centre, inner rings faster; the pointer scatters them.
const accretion: Effect = { color: "oklch(0.88 0 0)", alpha: 0.55, make: (world) => {
  const { w, h } = world, max = Math.hypot(w, h) * 0.62, ps: P[] = [];
  for (let r = 30; r < max; r += (10 + r * 0.04) / Math.sqrt(world.density)) {
    const count = Math.floor(TAU * r / (12 + r * 0.02));
    for (let k = 0; k < count; k++) ps.push(particle(w / 2, h * 0.42, k / count * TAU, r));
  }
  return (ctx) => {
    const { m, speed } = world, cx = w / 2, cy = h * 0.42;
    ctx.beginPath();
    for (const p of ps) {
      p.a += speed * 0.06 / Math.sqrt(p.r);
      p.r -= speed * 0.05 * (1 + 200 / p.r);
      if (p.r < 24) p.r = max;
      p.hx = cx + Math.cos(p.a) * p.r; p.hy = cy + Math.sin(p.a) * p.r;
      if (p.r === max) { p.x = p.hx; p.y = p.hy; p.vx = p.vy = 0; }
      repel(p, m, 3, 160); spring(p, 0.08, 0.8);
      dot(ctx, p.x, p.y, 0.5 + p.r / max * 1.8);
    }
    ctx.fill();
  };
} };

// Mistral: pixel blocks in the logo's yellow-to-red gradient, swelling in diagonal bands.
const pixels: Effect = { color: "oklch(0.75 0.17 55)", alpha: 0.32, make: (world) => {
  const gap = 22 / Math.sqrt(world.density), ps = gridPoints(world, gap);
  let fill: CanvasGradient | undefined;
  return (ctx) => {
    const { t, m, speed, h } = world;
    if (!fill) {
      fill = ctx.createLinearGradient(0, 0, 0, h);
      fill.addColorStop(0, "oklch(0.87 0.17 95)"); fill.addColorStop(0.5, "oklch(0.75 0.18 55)"); fill.addColorStop(1, "oklch(0.62 0.22 28)");
    }
    ctx.fillStyle = fill;
    ctx.beginPath();
    for (const p of ps) {
      repel(p, m, 3, 160); spring(p, 0.07, 0.8);
      const level = 0.5 + 0.5 * Math.sin((p.a + p.r) * 0.01 - t * speed * 1.4 + Math.sin(p.r * 0.008 + t * 0.5) * 2);
      const size = gap * (0.15 + level * 0.45) * (1 - displaced(p, 30) * 0.5);
      ctx.rect(p.x - size / 2, p.y - size / 2, size, size);
    }
    ctx.fill();
  };
} };

// Z.ai: a triangular mesh that stretches away from the pointer.
const lattice: Effect = { color: "oklch(0.68 0.14 220)", alpha: 0.4, make: (world) => {
  const gap = 46 / Math.sqrt(world.density), cols = Math.ceil(world.w / gap) + 2, rows = Math.ceil(world.h / (gap * 0.866)) + 2, ps: P[] = [];
  for (let row = 0; row < rows; row++) for (let col = 0; col < cols; col++) {
    const x = (col - 1) * gap + (row % 2 ? gap / 2 : 0), y = (row - 1) * gap * 0.866;
    ps.push(particle(x, y, x, y));
  }
  const at = (row: number, col: number) => row < rows && col >= 0 && col < cols ? ps[row * cols + col] : undefined;
  return (ctx) => {
    const { t, m, speed } = world;
    for (const p of ps) {
      p.hx = p.a + Math.sin(t * speed * 0.7 + p.r * 0.01) * 6; p.hy = p.r + Math.cos(t * speed * 0.6 + p.a * 0.01) * 6;
      repel(p, m, 4, 170); spring(p, 0.05, 0.82);
    }
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    for (let row = 0; row < rows; row++) for (let col = 0; col < cols; col++) {
      const p = ps[row * cols + col], shift = row % 2;
      for (const q of [at(row, col + 1), at(row + 1, col - 1 + shift), at(row + 1, col + shift)]) if (q) { ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); }
    }
    ctx.stroke();
  };
} };

// MiniMax: bands of audio-waveform bars; the pointer pushes bars apart and they spring back.
const equalizer: Effect = { color: "oklch(0.7 0.2 15)", alpha: 0.45, make: (world) => {
  const step = 8 / Math.sqrt(world.density), band = 110, ps: P[] = [];
  for (let y = band / 2, k = 0; y < world.h + band / 2; y += band, k++) for (let x = step / 2; x < world.w + step; x += step) ps.push(particle(x, y, x, k));
  return (ctx) => {
    const { t, m, speed } = world;
    ctx.beginPath();
    for (const p of ps) {
      repel(p, m, 2.5, 150); spring(p, 0.07, 0.8);
      const level = Math.abs(Math.sin(p.a * 0.012 + t * speed * 2 + p.r) * Math.sin(p.a * 0.003 - t * speed * 0.7 + p.r * 1.7));
      const height = (0.12 + 0.88 * level) * band * 0.45 * (1 - displaced(p, 30) * 0.4);
      ctx.roundRect(p.x - 1.5, p.y - height / 2, 3, height, 1.5);
    }
    ctx.fill();
  };
} };

const effects: Record<string, Effect> = { arkinous: halftone, openai: hexes, anthropic: constellation, gemini: spiral, meta: grid, kimi: rain, qwen: bubbles, deepseek: ripples, xai: accretion, mistral: pixels, zai: lattice, minimax: equalizer };

export function OrchestratorBackground({ kind, model }: { kind: string | undefined; model: string }) {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const inset = document.querySelector<HTMLElement>('[data-slot="sidebar-inset"]');
    if (!inset) return;
    // A stacking context lets the negative-z canvas paint above the inset's own background but below its content.
    const previous = inset.style.isolation;
    inset.style.isolation = "isolate";
    setHost(inset);
    return () => { inset.style.isolation = previous; };
  }, []);
  useEffect(() => {
    const effect = kind ? effects[kind] : undefined;
    const canvas = canvasRef.current, ctx = canvas?.getContext("2d");
    if (!effect || !canvas || !ctx) return;
    let hash = 0;
    for (const ch of model) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    const pointer: Pointer = { x: 0, y: 0, on: false };
    const world: World = { w: 0, h: 0, t: 0, m: pointer, density: 0.7 + (hash % 1000) / 1000 * 0.6, speed: 0.75 + ((hash >>> 10) % 1000) / 1000 * 0.5 };
    let draw: Draw = () => {};
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio, 2);
      world.w = window.innerWidth; world.h = window.innerHeight;
      canvas.width = world.w * dpr; canvas.height = world.h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.strokeStyle = ctx.fillStyle = effect.color;
      draw = effect.make(world);
    };
    const step = () => {
      if (effect.trail) {
        ctx.globalCompositeOperation = "destination-out"; ctx.globalAlpha = effect.trail;
        ctx.fillRect(0, 0, world.w, world.h);
        ctx.globalCompositeOperation = "source-over";
      } else ctx.clearRect(0, 0, world.w, world.h);
      ctx.globalAlpha = effect.alpha; ctx.lineWidth = 1;
      draw(ctx);
      world.t += 1 / 60;
    };
    resize();
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      for (let i = 0; i < 90; i++) step();
      return () => ctx.clearRect(0, 0, world.w, world.h);
    }
    const onMove = (event: PointerEvent) => { pointer.x = event.clientX; pointer.y = event.clientY; pointer.on = true; };
    const onLeave = () => { pointer.on = false; };
    let frame = requestAnimationFrame(function loop() { step(); frame = requestAnimationFrame(loop); });
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    window.addEventListener("blur", onLeave);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      window.removeEventListener("blur", onLeave);
      ctx.clearRect(0, 0, world.w, world.h);
    };
  }, [kind, model, host]);
  return host ? createPortal(<canvas ref={canvasRef} aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 size-full" />, host) : null;
}
