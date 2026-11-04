// Defaults for the New design form, kept in this browser only; the server never stores them.
// `expert` adds the REVIEW checkpoint option: the orchestrator waits for edits to its drafted spec and build settings.
export interface RunDefaults { clock: number; fit: boolean; expert: boolean }

export const factoryDefaults: RunDefaults = { clock: 50, fit: false, expert: false };
const key = "silicon-agent.run-defaults";

// Same clock bounds as the API's Targets.clock_mhz; anything unreadable falls back field by field.
export function parseRunDefaults(raw: string | null): RunDefaults {
  let value: unknown;
  try { value = raw ? JSON.parse(raw) : null; } catch { value = null; }
  const stored = value && typeof value === "object" ? value as Partial<Record<keyof RunDefaults, unknown>> : {};
  const clock = typeof stored.clock === "number" && Number.isFinite(stored.clock) && stored.clock >= 1 && stored.clock <= 1000 ? stored.clock : factoryDefaults.clock;
  return { clock, fit: typeof stored.fit === "boolean" ? stored.fit : factoryDefaults.fit, expert: typeof stored.expert === "boolean" ? stored.expert : factoryDefaults.expert };
}

// Storage can be blocked (private mode, site settings); fall back to the factory defaults instead of crashing.
export const loadRunDefaults = () => { try { return parseRunDefaults(window.localStorage.getItem(key)); } catch { return factoryDefaults; } };
export function saveRunDefaults(defaults: RunDefaults): boolean {
  try {
    window.localStorage.setItem(key, JSON.stringify(defaults));
    return true;
  } catch {
    return false;
  }
}
