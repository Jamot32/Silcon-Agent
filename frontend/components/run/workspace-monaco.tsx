"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Editor, { type Monaco } from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import { useAppearance } from "@/hooks/use-appearance";
import { useIsMobile } from "@/hooks/use-mobile";
import { Textarea } from "@/components/ui/textarea";
import { loadMonacoAssets, registerMonacoThemes } from "./monaco-view";

const options: editor.IStandaloneEditorConstructionOptions = {
  minimap: { enabled: false }, fontSize: 13, lineHeight: 21, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  automaticLayout: true, scrollBeyondLastLine: false, padding: { top: 12 }, wordWrap: "off", glyphMargin: false,
};
function useMonaco() {
  const [state, setState] = useState({ ready: false, error: "" });
  useEffect(() => {
    let live = true;
    loadMonacoAssets().then(() => { if (live) setState({ ready: true, error: "" }); }, (error) => { if (live) setState({ ready: false, error: error instanceof Error ? error.message : "Editor unavailable." }); });
    return () => { live = false; };
  }, []);
  return state;
}

export function WorkspaceEditor({ runId, path, value, replacementRevision, disabled, onChange, onSave }: { runId: string; path: string; value: string; replacementRevision: number; disabled: boolean; onChange: (value: string) => void; onSave: () => void }) {
  const { ready, error } = useMonaco();
  const scheme = useAppearance().scheme;
  const current = useRef({ runId, path, value, onChange, onSave });
  current.current = { runId, path, value, onChange, onSave };
  const view = useRef<editor.IStandaloneCodeEditor | null>(null);
  const modelListener = useRef<{ dispose: () => void } | null>(null);
  const replacing = useRef(false);
  const applyReplacement = useCallback(() => {
    const instance = view.current, latest = current.current;
    const model = instance?.getModel();
    if (!instance || !model || model.uri.toString() !== `workspace://${latest.runId}/${latest.path}` || model.getValue() === latest.value) return;
    const position = instance.saveViewState();
    replacing.current = true;
    try {
      instance.pushUndoStop();
      instance.executeEdits("workspace-replacement", [{ range: model.getFullModelRange(), text: latest.value }]);
      instance.pushUndoStop();
      if (position) instance.restoreViewState(position);
    } finally { replacing.current = false; }
  }, []);
  // Only an explicit source load/reload or a file switch replaces the model.
  // Feeding each React value echo back to Monaco can overwrite newer typing
  // with a stale full-buffer edit and move the cursor to the end of the file.
  useEffect(applyReplacement, [applyReplacement, runId, path, replacementRevision]);
  useEffect(() => () => { modelListener.current?.dispose(); view.current = null; }, []);
  const changed = useCallback((next: string | undefined) => {
    if (!replacing.current) current.current.onChange(next ?? "");
  }, []);
  const mounted = useCallback((instance: editor.IStandaloneCodeEditor, monaco: Monaco) => {
    view.current = instance;
    instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => current.current.onSave());
    modelListener.current?.dispose();
    modelListener.current = instance.onDidChangeModel(applyReplacement);
    applyReplacement();
  }, [applyReplacement]);
  const editorOptions = useMemo(() => ({ ...options, readOnly: disabled, ariaLabel: `Edit ${path}`, tabSize: path.endsWith(".py") ? 4 : 2 }), [disabled, path]);
  if (!ready) return <div className="flex h-full min-h-0 flex-col gap-2 p-3"><p role="status" className="text-xs text-muted-foreground">{error ? `${error} You can keep editing below.` : "Loading local code editor…"}</p><Textarea aria-label={`Edit ${path}`} className="min-h-0 flex-1 font-mono" value={value} disabled={disabled} spellCheck={false} onChange={(event) => onChange(event.target.value)} /></div>;
  return <Editor height="100%" path={`workspace://${runId}/${path}`} defaultValue={value} language={path.endsWith(".py") ? "python" : "verilog"} beforeMount={registerMonacoThemes} theme={scheme === "dark" ? "silicon-lab" : "silicon-lab-light"} onChange={changed} options={editorOptions} onMount={mounted} />;
}

export function WorkspaceDiff({ path, before, after }: { path: string; before: string; after: string }) {
  const { ready, error } = useMonaco();
  const scheme = useAppearance().scheme;
  const themeName = scheme === "dark" ? "silicon-lab" : "silicon-lab-light";
  const container = useRef<HTMLDivElement>(null);
  const mobile = useIsMobile();
  const editorRef = useRef<editor.IStandaloneDiffEditor | null>(null);
  const models = useRef<{ original: editor.ITextModel; modified: editor.ITextModel } | null>(null);
  useEffect(() => {
    const monaco = window.SiliconMonaco;
    if (!ready || !container.current || !monaco) return;
    registerMonacoThemes(monaco);
    const language = path.endsWith(".py") ? "python" : "verilog";
    const original = monaco.editor.createModel("", language), modified = monaco.editor.createModel("", language);
    const view = monaco.editor.createDiffEditor(container.current, { ...options, readOnly: true, originalEditable: false, renderSideBySide: !mobile, useInlineViewWhenSpaceIsLimited: true, theme: themeName, ariaLabel: `Read-only flow comparison for ${path}` });
    editorRef.current = view;
    models.current = { original, modified }; view.setModel(models.current);
    return () => { view.setModel(null); view.dispose(); original.dispose(); modified.dispose(); models.current = null; editorRef.current = null; };
  }, [ready, path]);
  useEffect(() => { window.SiliconMonaco?.editor.setTheme(themeName); }, [themeName]);
  useEffect(() => { editorRef.current?.updateOptions({ renderSideBySide: !mobile }); }, [mobile, ready]);
  useEffect(() => { models.current?.original.setValue(before); models.current?.modified.setValue(after); }, [before, after, ready, path]);
  if (!ready) return <div className="grid h-full min-w-0 grid-cols-2 gap-3 overflow-auto p-3"><p role="status" className="col-span-2 text-xs text-muted-foreground">{error || "Loading source comparison…"}</p><pre aria-label="Baseline source" className="overflow-auto font-mono text-xs">{before}</pre><pre aria-label="Candidate source" className="overflow-auto font-mono text-xs">{after}</pre></div>;
  return <div ref={container} className="h-full w-full" />;
}
