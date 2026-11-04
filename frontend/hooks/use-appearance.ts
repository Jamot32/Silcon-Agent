import { useSyncExternalStore } from "react";
import { defaultAppearance, readAppearance, type Appearance } from "@/lib/appearance";

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

// Cached by class string so useSyncExternalStore sees a stable snapshot between changes.
let cached: { key: string; value: Appearance } | undefined;
function snapshot(): Appearance {
  const key = document.documentElement.className;
  if (cached?.key !== key) cached = { key, value: readAppearance(document.documentElement) };
  return cached.value;
}

// The <html> classes are the single source of truth; the server render assumes the default.
export function useAppearance(): Appearance {
  return useSyncExternalStore(subscribe, snapshot, () => defaultAppearance);
}
