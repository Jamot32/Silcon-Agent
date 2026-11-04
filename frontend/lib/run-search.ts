import type { PublicRun, Recording } from "./api";

type Field = string | null | undefined;

// Every whitespace-separated keyword must appear (case-insensitively) in at least one field.
export function matchesSearch(query: string, fields: readonly Field[]): boolean {
  const terms = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return true;
  const haystack = fields.filter((field): field is string => typeof field === "string").map((field) => field.toLocaleLowerCase());
  return terms.every((term) => haystack.some((field) => field.includes(term)));
}

// `name` is the displayed run name; the caller computes it so this module stays dependency-free.
export function runSearchFields(run: PublicRun, name: string, sourceRunId?: string | null): Field[] {
  const topModule = run.design_spec?.top_module;
  return [name, run.display_name, typeof topModule === "string" ? topModule : null, run.preset_id, run.spec_text,
    run.id, run.status, run.stage, run.recording_id, sourceRunId];
}

export function recordingSearchFields(recording: Recording): Field[] {
  return [recording.name, recording.description, recording.id, recording.source_run_id];
}
