"use client";

import { useEffect, useState } from "react";
import Editor, { DiffEditor, loader, type Monaco } from "@monaco-editor/react";
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
    colors: { "editor.background": "#0C1318", "editor.foreground": "#E0E7EE", "editorLineNumber.foreground": "#758899", "editor.lineHighlightBackground": "#111C24", "editor.selectionBackground": "#21484D", "diffEditor.insertedTextBackground": "#2F685936", "diffEditor.removedTextBackground": "#8D444736", "editorGutter.background": "#0C1318" },
  });
}
const options: editor.IStandaloneEditorConstructionOptions = {
  readOnly: true, minimap: { enabled: false }, fontSize: 13, lineHeight: 21,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", scrollBeyondLastLine: false,
  automaticLayout: true, padding: { top: 14, bottom: 14 }, wordWrap: "off", glyphMargin: false,
  lineNumbersMinChars: 3, overviewRulerLanes: 0, renderLineHighlight: "none", contextmenu: false,
  scrollbar: { verticalScrollbarSize: 7, horizontalScrollbarSize: 7 },
};

export default function MonacoView({ path, value, before, diff }: { path: string; value: string; before?: string; diff: boolean }) {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    loadAssets().then(() => { if (active) setReady(true); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Editor unavailable"); });
    return () => { active = false; };
  }, []);
  const language = path.endsWith(".py") ? "python" : "verilog";
  if (error) return <div className="editor-fallback"><p role="status">{error}</p><pre>{value}</pre></div>;
  if (!ready) return <div className="editor-fallback"><p className="micro-label">Loading local editor…</p><pre>{value}</pre></div>;
  if (diff && before !== undefined) return <DiffEditor height="100%" language={language} original={before} modified={value} originalModelPath={`before://${path}`} modifiedModelPath={`after://${path}`} theme="silicon-lab" beforeMount={theme} options={{ ...options, renderSideBySide: false, originalEditable: false, ariaLabel: `Read-only changes to ${path}` }} />;
  return <Editor height="100%" path={path} value={value} language={language} theme="silicon-lab" beforeMount={theme} options={{ ...options, ariaLabel: `Read-only ${path}` }} />;
}
