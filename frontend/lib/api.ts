export interface Check { status: string; detail: string }
export interface Health {
  status: "ok" | "degraded";
  checks: { database: Check; eda: Check; llm: Check };
  milestone: string;
  llm_provider: string;
}
export interface Preset { id: string; name: string; spec_text: string }
export interface Run { id: string; spec_text: string; status: string; stage: string; created_at: string }
export interface Recording { id: string; name: string }

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}
