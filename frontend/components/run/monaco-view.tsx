"use client";

import { useEffect, useRef, useState } from "react";
import { useAppearance } from "@/hooks/use-appearance";
import Editor, { loader, type Monaco } from "@monaco-editor/react";
import type { editor } from "monaco-editor";

// The editor and its worker are built from pinned npm sources and served by this app.
declare global {
  interface Window {
    SiliconMonaco?: Monaco;
    MonacoEnvironment?: { getWorkerUrl: () => string };
  }
}
let editorAssets: Promise<void> | undefined;
function loadAssets(): Promise<void> {
  if (!editorAssets) editorAssets = new Promise((resolve, reject) => {
    window.MonacoEnvironment = { getWorkerUrl: () => "/monaco/editor.worker.js" };
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = "/monaco/editor.css";
    document.head.appendChild(style);
    const script = document.createElement("script");
    script.src = "/monaco/editor.js";
    script.onload = () => {
      if (!window.SiliconMonaco) return reject(new Error("Local editor did not initialize."));
      loader.config({ monaco: window.SiliconMonaco });
      resolve();
    };
    script.onerror = () => reject(new Error("The local editor assets could not be loaded."));
    document.head.appendChild(script);
  });
  return editorAssets;
}

function theme(monaco: Monaco) {
  monaco.editor.defineTheme("silicon-lab", {
    base: "vs-dark", inherit: true,
    rules: [{ token: "keyword", foreground: "57B9F3" }, { token: "number", foreground: "D8AD73" }, { token: "comment", foreground: "718390" }],
    colors: { "editor.background": "#171717", "editor.foreground": "#FAFAFA", "editorLineNumber.foreground": "#737373", "editor.lineHighlightBackground": "#262626", "editor.selectionBackground": "#404040", "diffEditor.insertedTextBackground": "#2F685936", "diffEditor.removedTextBackground": "#8D444736", "editorGutter.background": "#171717" },
  });
  // Light counterpart on the shadcn light card surface; token hues darkened for contrast on white.
  monaco.editor.defineTheme("silicon-lab-light", {
    base: "vs", inherit: true,
    rules: [{ token: "keyword", foreground: "0B69A3" }, { token: "number", foreground: "9A6A1F" }, { token: "comment", foreground: "5F6F7A" }],
    colors: { "editor.background": "#FFFFFF", "editor.foreground": "#0A0A0A", "editorLineNumber.foreground": "#737373", "editor.lineHighlightBackground": "#F5F5F5", "editor.selectionBackground": "#E5E5E5", "diffEditor.insertedTextBackground": "#22863A26", "diffEditor.removedTextBackground": "#CB243126", "editorGutter.background": "#FFFFFF" },
  });
}
// Shared by the editable workspace; the run inspector remains read-only.
export { loadAssets as loadMonacoAssets, theme as registerMonacoThemes };
const options: editor.IStandaloneEditorConstructionOptions = {
  readOnly: true, minimap: { enabled: false }, fontSize: 13, lineHeight: 21,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", scrollBeyondLastLine: false,
  automaticLayout: true, padding: { top: 14, bottom: 14 }, wordWrap: "off", glyphMargin: false,
  lineNumbersMinChars: 3, overviewRulerLanes: 0, renderLineHighlight: "none", contextmenu: false,
  scrollbar: { verticalScrollbarSize: 7, horizontalScrollbarSize: 7 },
};

function DiffView({ path, before, value, language, themeName }: { path: string; before: string; value: string; language: string; themeName: string }) {
  const container = useRef<HTMLDivElement>(null);
  const models = useRef<{ original: editor.ITextModel; modified: editor.ITextModel } | null>(null);
  useEffect(() => {
    const monaco = window.SiliconMonaco;
    if (!container.current || !monaco) return;
    theme(monaco);
    const original = monaco.editor.createModel("", language);
    const modified = monaco.editor.createModel("", language);
    const view = monaco.editor.createDiffEditor(container.current, { ...options, theme: themeName, renderSideBySide: false, originalEditable: false, ariaLabel: `Read-only changes to ${path}` });
    models.current = { original, modified };
    view.setModel(models.current);
    return () => {
      // Monaco 0.57 requires detaching the diff widget before disposing its text models.
      view.setModel(null);
      view.dispose();
      original.dispose();
      modified.dispose();
      models.current = null;
    };
    // Theme changes go through setTheme below instead of recreating the widget.
  }, [language, path]);
  useEffect(() => { window.SiliconMonaco?.editor.setTheme(themeName); }, [themeName]);
  useEffect(() => {
    const current = models.current;
    if (current?.original.getValue() !== before) current?.original.setValue(before);
    if (current?.modified.getValue() !== value) current?.modified.setValue(value);
  }, [before, value, language, path]);
  return <div ref={container} style={{ height: "100%", width: "100%" }} />;
}

export default function MonacoView({ path, value, before, diff }: { path: string; value: string; before?: string; diff: boolean }) {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const themeName = useAppearance().scheme === "dark" ? "silicon-lab" : "silicon-lab-light";
  useEffect(() => {
    let active = true;
    loadAssets().then(() => { if (active) setReady(true); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Editor unavailable"); });
    return () => { active = false; };
  }, []);
  const language = path.endsWith(".py") ? "python" : "verilog";
  if (error) return <div className="h-full overflow-auto"><p role="status" className="mx-4 my-2 text-xs text-destructive">{error}</p><pre className="px-4 pb-4 font-mono text-xs leading-5 [tab-size:4]">{value}</pre></div>;
  if (!ready) return <div className="h-full overflow-auto"><p className="mx-4 my-2 text-[11px] text-muted-foreground">Loading local editor…</p><pre className="px-4 pb-4 font-mono text-xs leading-5 [tab-size:4]">{value}</pre></div>;
  if (diff && before !== undefined) return <DiffView path={path} before={before} value={value} language={language} themeName={themeName} />;
  return <Editor height="100%" path={path} value={value} language={language} theme={themeName} beforeMount={theme} options={{ ...options, ariaLabel: `Read-only ${path}` }} />;
}
