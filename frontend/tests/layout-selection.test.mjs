import assert from "node:assert/strict";
import test from "node:test";
import { boundsFromPoints, containedImageRect, imagePoint, projectedBounds, selectionBoundsError } from "../lib/layout-selection.ts";

const close = (actual, expected) => {
  for (const key of Object.keys(expected)) assert.ok(Math.abs(actual[key] - expected[key]) < 1e-9, `${key}: ${actual[key]} != ${expected[key]}`);
};

test("object-contain mapping excludes horizontal and vertical letterboxes", () => {
  const wide = containedImageRect({ left: 20, top: 40, width: 400, height: 400 }, 800, 400);
  assert.deepEqual(wide, { left: 20, top: 140, width: 400, height: 200 });
  assert.equal(imagePoint({ x: 220, y: 100 }, wide), null);
  close(imagePoint({ x: 120, y: 190 }, wide), { x: 0.25, y: 0.25 });
  const tall = containedImageRect({ left: 20, top: 40, width: 400, height: 400 }, 400, 800);
  assert.deepEqual(tall, { left: 120, top: 40, width: 200, height: 400 });
  assert.equal(imagePoint({ x: 100, y: 240 }, tall), null);
  close(imagePoint({ x: 170, y: 340 }, tall), { x: 0.25, y: 0.75 });
});

test("the transformed image box maps zoom and pan back to original image coordinates", () => {
  // A 400-square image element scaled 2x around its center and panned (+30, -20).
  const transformed = { left: -150, top: -180, width: 800, height: 800 };
  const content = containedImageRect(transformed, 800, 400);
  assert.deepEqual(content, { left: -150, top: 20, width: 800, height: 400 });
  close(imagePoint({ x: 50, y: 120 }, content), { x: 0.25, y: 0.25 });
  close(imagePoint({ x: 450, y: 320 }, content), { x: 0.75, y: 0.75 });
  // Clipping at the viewer boundary never changes the original image coordinate space.
  close(imagePoint({ x: 0, y: 220 }, content), { x: 0.1875, y: 0.5 });
});

test("reverse drags normalize their corners and captured endpoints clamp to the image", () => {
  const rect = { left: 10, top: 20, width: 200, height: 100 };
  const start = imagePoint({ x: 160, y: 100 }, rect);
  assert.equal(imagePoint({ x: -20, y: 160 }, rect), null);
  const end = imagePoint({ x: -20, y: 160 }, rect, true);
  close(boundsFromPoints(start, end), { x0: 0, y0: 0.8, x1: 0.75, y1: 1 });
});

test("a stored selection projects correctly after resizing, zooming and panning", () => {
  const bounds = { x0: 0.125, y0: 0.2, x1: 0.875, y1: 0.9 };
  for (const rect of [{ left: 40, top: 70, width: 320, height: 160 }, { left: -120, top: 15, width: 960, height: 480 }]) {
    const overlay = projectedBounds(bounds, rect);
    const start = imagePoint({ x: overlay.left, y: overlay.top }, rect);
    const end = imagePoint({ x: overlay.left + overlay.width, y: overlay.top + overlay.height }, rect);
    close(boundsFromPoints(start, end), bounds);
  }
});

test("invalid or tiny selections cannot be submitted, including percentage-entry errors", () => {
  assert.equal(selectionBoundsError({ x0: 0, y0: 0, x1: 1, y1: 1 }, 1000, 500), null);
  assert.equal(selectionBoundsError({ x0: 0.1, y0: 0.1, x1: 0.104, y1: 0.108 }, 1000, 500), null);
  assert.match(selectionBoundsError({ x0: 0.1, y0: 0.1, x1: 0.102, y1: 0.108 }, 1000, 500), /at least 4/);
  assert.match(selectionBoundsError({ x0: 0.5, y0: 0, x1: 0.5, y1: 1 }, 1000, 500), /Left must/);
  assert.match(selectionBoundsError({ x0: -0.1, y0: 0, x1: 1, y1: 1 }, 1000, 500), /between 0 and 100/);
  assert.match(selectionBoundsError({ x0: 0, y0: NaN, x1: 1, y1: 1 }, 1000, 500), /between 0 and 100/);
  assert.match(selectionBoundsError({ x0: 0, y0: 0, x1: 1, y1: 1 }, 0, 500), /image/);
  assert.equal(containedImageRect({ left: 0, top: 0, width: 0, height: 100 }, 400, 200), null);
  assert.equal(containedImageRect({ left: 0, top: 0, width: 100, height: 100 }, 0, 200), null);
});
