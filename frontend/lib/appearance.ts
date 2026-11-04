// Four appearance modes: light or dark scheme × monochrome or brand-color provider logos.
// Kept in this browser only. <html> carries `dark` and `colorful` classes; CSS variants key off them.
export type Scheme = "dark" | "light";
export type Palette = "mono" | "color";
export interface Appearance { scheme: Scheme; palette: Palette }

export const defaultAppearance: Appearance = { scheme: "dark", palette: "mono" };
export const appearanceKey = "silicon-agent.appearance";

export function parseAppearance(raw: string | null): Appearance {
  let value: unknown;
  try { value = raw ? JSON.parse(raw) : null; } catch { value = null; }
  const stored = value && typeof value === "object" ? value as Partial<Record<keyof Appearance, unknown>> : {};
  return {
    scheme: stored.scheme === "light" || stored.scheme === "dark" ? stored.scheme : defaultAppearance.scheme,
    palette: stored.palette === "color" || stored.palette === "mono" ? stored.palette : defaultAppearance.palette,
  };
}

export function applyAppearance(root: { classList: DOMTokenList }, appearance: Appearance) {
  root.classList.toggle("dark", appearance.scheme === "dark");
  root.classList.toggle("colorful", appearance.palette === "color");
}

// Inline <head> script: applies the stored mode before first paint so light mode never flashes dark.
// Mirrors parseAppearance/applyAppearance; storage failures keep the server-rendered dark monochrome default.
export const appearanceScript = `try{var a=JSON.parse(localStorage.getItem(${JSON.stringify(appearanceKey)})||"null")||{},c=document.documentElement.classList;if(a.scheme==="light")c.remove("dark");if(a.palette==="color")c.add("colorful")}catch(e){}`;

// Applies immediately; returns false when storage is blocked (the mode still holds for this page view).
export function saveAppearance(appearance: Appearance): boolean {
  applyAppearance(document.documentElement, appearance);
  try {
    window.localStorage.setItem(appearanceKey, JSON.stringify(appearance));
    return true;
  } catch {
    return false;
  }
}

export function readAppearance(root: { classList: DOMTokenList }): Appearance {
  return { scheme: root.classList.contains("dark") ? "dark" : "light", palette: root.classList.contains("colorful") ? "color" : "mono" };
}
