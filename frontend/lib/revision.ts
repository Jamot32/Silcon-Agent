import type { CreateRunInput, PublicRun } from "./api";

export interface RevisionEdit { spec: string; clock: number; fit: boolean; reuse: boolean }

// The form opens on what the run actually targeted, so an untouched form repeats it exactly.
export function revisionDefaults(run: PublicRun, hasRtl: boolean): RevisionEdit {
  const targets = { ...run.design_spec?.targets, ...run.targets };
  return { spec: run.spec_text, clock: targets.clock_mhz ?? 50, fit: targets.fit === "tt_1x1_tile", reuse: hasRtl && run.status === "done" };
}

export function revisionRequest(run: PublicRun, edit: RevisionEdit, defaults: RevisionEdit): { body: CreateRunInput; rerun: boolean } {
  const sameText = edit.spec.trim() === run.spec_text.trim();
  const sameTargets = edit.clock === defaults.clock && edit.fit === defaults.fit;
  return {
    rerun: sameText && sameTargets && !edit.reuse,
    body: {
      spec_text: edit.spec.trim(),
      targets: sameTargets ? run.targets : { ...run.targets, clock_mhz: edit.clock, fit: edit.fit ? "tt_1x1_tile" : null },
      parent_run_id: run.id, reuse_design: edit.reuse,
      // NewDesign drops the preset once the text changes; a supplied starter cannot be combined with reused RTL.
      ...(sameText && run.preset_id ? { preset_id: run.preset_id } : {}),
      ...(sameText && !edit.reuse && run.starter_id === "uart_off_by_one" ? { starter_id: run.starter_id } : {}),
    },
  };
}
