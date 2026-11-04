/** Fractions of the original image, measured from its top-left corner. */
export interface LayoutRegionBounds { x0: number; y0: number; x1: number; y1: number }
export interface LayoutRegionSelection {
  run_tag: string; image_url: string; bounds: LayoutRegionBounds;
  image_width: number; image_height: number;
}
export interface ImageRect { left: number; top: number; width: number; height: number }
export interface ImagePoint { x: number; y: number }

const finitePositive = (value: number) => Number.isFinite(value) && value > 0;
const clamp = (value: number) => Math.max(0, Math.min(1, value));

/** The object-contain content inside an img's transformed getBoundingClientRect(). */
export function containedImageRect(box: ImageRect, imageWidth: number, imageHeight: number): ImageRect | null {
  if (![box.left, box.top].every(Number.isFinite) || ![box.width, box.height, imageWidth, imageHeight].every(finitePositive)) return null;
  const scale = Math.min(box.width / imageWidth, box.height / imageHeight);
  const width = imageWidth * scale, height = imageHeight * scale;
  return { left: box.left + (box.width - width) / 2, top: box.top + (box.height - height) / 2, width, height };
}

/** Starts reject letterbox clicks; captured drag endpoints may clamp to the image. */
export function imagePoint(point: ImagePoint, rect: ImageRect | null, clampOutside = false): ImagePoint | null {
  if (!rect || ![point.x, point.y, rect.left, rect.top].every(Number.isFinite) || ![rect.width, rect.height].every(finitePositive)) return null;
  const x = (point.x - rect.left) / rect.width, y = (point.y - rect.top) / rect.height;
  if (!clampOutside && (x < 0 || x > 1 || y < 0 || y > 1)) return null;
  return { x: clamp(x), y: clamp(y) };
}

export function boundsFromPoints(start: ImagePoint, end: ImagePoint): LayoutRegionBounds {
  return { x0: Math.min(start.x, end.x), y0: Math.min(start.y, end.y), x1: Math.max(start.x, end.x), y1: Math.max(start.y, end.y) };
}

export function projectedBounds(bounds: LayoutRegionBounds, rect: ImageRect): ImageRect {
  return { left: rect.left + bounds.x0 * rect.width, top: rect.top + bounds.y0 * rect.height,
    width: (bounds.x1 - bounds.x0) * rect.width, height: (bounds.y1 - bounds.y0) * rect.height };
}

export function selectionBoundsError(bounds: LayoutRegionBounds, imageWidth: number, imageHeight: number): string | null {
  if (![imageWidth, imageHeight].every(finitePositive)) return "Wait for the layout image to load.";
  if (!Object.values(bounds).every((value) => Number.isFinite(value) && value >= 0 && value <= 1)) return "Enter all four bounds between 0 and 100 percent.";
  if (bounds.x0 >= bounds.x1 || bounds.y0 >= bounds.y1) return "Left must be less than right, and top must be less than bottom.";
  if ((bounds.x1 - bounds.x0) * imageWidth < 4 - 1e-6 || (bounds.y1 - bounds.y0) * imageHeight < 4 - 1e-6) return "Select a region at least 4 × 4 image pixels.";
  return null;
}
