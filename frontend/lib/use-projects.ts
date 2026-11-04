"use client";

import { useEffect, useState } from "react";
import { listProjects, moveRuns, type Project } from "./api";
import { notifyRunsChanged, RUNS_CHANGED_EVENT } from "./run-history-events";

/** Project folders, reloaded whenever runs or projects change; null until the first load settles. */
export function useProjects(): { projects: Project[] | null; error: string } {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const changed = () => setVersion((value) => value + 1);
    window.addEventListener(RUNS_CHANGED_EVENT, changed);
    return () => window.removeEventListener(RUNS_CHANGED_EVENT, changed);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    listProjects(controller.signal).then((rows) => {
      if (!controller.signal.aborted) { setProjects(rows); setError(""); }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) { setProjects((current) => current ?? []); setError(reason instanceof Error ? reason.message : "Projects could not be loaded."); }
    });
    return () => controller.abort();
  }, [version]);
  return { projects, error };
}

/** Moves the frozen ID list in API-sized batches; every list refreshes afterwards, even on failure. */
export async function moveRunsToProject(runIds: string[], projectId: string | null): Promise<number> {
  let moved = 0;
  try {
    for (let start = 0; start < runIds.length; start += 100) {
      moved += (await moveRuns(runIds.slice(start, start + 100), projectId)).length;
    }
    return moved;
  } finally {
    notifyRunsChanged();
  }
}
