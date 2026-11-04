import type { PublicRun } from "./api";

// Project folders only organize runs; they share no memory or build context.
export type ProjectFolder = "all" | "unfiled" | string;

export const RUN_DRAG_TYPE = "application/x-silicon-run-ids";
const RUN_ID = /^[0-9a-f]{32}$/;

export function inFolder(run: Pick<PublicRun, "project_id">, folder: ProjectFolder): boolean {
  if (folder === "all") return true;
  if (folder === "unfiled") return !run.project_id;
  return run.project_id === folder;
}

export function writeRunDrag(data: DataTransfer, runIds: string[]): void {
  data.setData(RUN_DRAG_TYPE, JSON.stringify(runIds));
  data.effectAllowed = "move";
}

export function isRunDrag(data: DataTransfer): boolean {
  return Array.from(data.types).includes(RUN_DRAG_TYPE);
}

/** Dropped IDs, or an empty list when the payload is foreign or malformed. */
export function readRunDrag(data: Pick<DataTransfer, "getData">): string[] {
  try {
    const value: unknown = JSON.parse(data.getData(RUN_DRAG_TYPE));
    if (!Array.isArray(value) || !value.every((id) => typeof id === "string" && RUN_ID.test(id))) return [];
    return Array.from(new Set(value as string[]));
  } catch {
    return [];
  }
}
