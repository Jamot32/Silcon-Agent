"use client";

import { useEffect, useState } from "react";
import { getJson, type Check, type Health, type Preset, type Recording } from "@/lib/api";

const initialSpec = "An 8-bit up/down counter with enable, synchronous load, and active-low reset.";
const shortNames: Record<string, string> = {
  counter: "Counter", pwm: "PWM", uart_tx: "UART TX", uart: "UART TX", alu: "4-bit ALU", traffic_light: "Traffic light",
};

function checkLabel(check: Check | undefined, fallback: string) {
  if (!check) return fallback;
  if (check.status === "ok") return "Ready";
  if (check.status === "not_configured") return "Not configured";
  if (check.status === "not_verified" || check.status === "not_checked") return "Not verified";
  if (check.status === "unavailable" || check.status === "error") return "Unavailable";
  return check.status.replaceAll("_", " ");
}

export function NewDesign() {
  const [spec, setSpec] = useState(initialSpec);
  const [clock, setClock] = useState("50");
  const [fit, setFit] = useState(false);
  const [health, setHealth] = useState<Health>();
  const [apiState, setApiState] = useState("Checking");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetsError, setPresetsError] = useState(false);
  const [recordings, setRecordings] = useState<Recording[] | null>(null);
  const [recordingsError, setRecordingsError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const results = await Promise.allSettled([
        getJson<Health>("/api/health", controller.signal),
        getJson<Preset[]>("/api/presets", controller.signal),
        getJson<Recording[]>("/api/recordings", controller.signal),
      ]);
      if (controller.signal.aborted) return;
      const [healthResult, presetsResult, recordingsResult] = results;
      if (healthResult.status === "fulfilled") {
        setHealth(healthResult.value);
        setApiState("Ready");
      } else setApiState("Unavailable");
      if (presetsResult.status === "fulfilled") setPresets(presetsResult.value);
      else setPresetsError(true);
      if (recordingsResult.status === "fulfilled") setRecordings(recordingsResult.value);
      else setRecordingsError(true);
    }
    void load();
    return () => controller.abort();
  }, []);

  const checks = [
    { name: "API", label: apiState, detail: apiState === "Ready" ? "Backend API is reachable." : undefined, ready: apiState === "Ready" },
    { name: "Database", label: checkLabel(health?.checks.database, "Checking"), detail: health?.checks.database.detail, ready: health?.checks.database.status === "ok" },
    { name: "EDA", label: checkLabel(health?.checks.eda, "Not verified"), detail: health?.checks.eda.detail, ready: health?.checks.eda.status === "ok" },
    { name: "Model", label: checkLabel(health?.checks.llm, "Not configured"), detail: health?.checks.llm.detail, ready: health?.checks.llm.status === "ok" },
  ];

  return (
    <>
      <div className="design-grid">
        <section className="panel design-panel" aria-labelledby="design-title">
          <h2 id="design-title">Design specification</h2>
          <form onSubmit={(event) => event.preventDefault()}>
            <label className="sr-only" htmlFor="design-spec">Describe your chip</label>
            <textarea id="design-spec" value={spec} onChange={(event) => setSpec(event.target.value)} spellCheck={false} />
            <div className="preset-row" aria-label="Example chip specifications">
              {presets.map((preset) => (
                <button key={preset.id} type="button" className="preset-button" onClick={() => setSpec(preset.spec_text)}>
                  {shortNames[preset.id] ?? preset.name}
                </button>
              ))}
              {presetsError ? <span className="muted small">Presets could not be loaded.</span> : null}
            </div>
            <div className="target-row">
              <div className="clock-field">
                <label htmlFor="target-clock">Target clock (MHz)</label>
                <input id="target-clock" type="number" min="1" max="1000" value={clock} onChange={(event) => setClock(event.target.value)} />
              </div>
              <label className="checkbox-label">
                <input type="checkbox" checked={fit} onChange={(event) => setFit(event.target.checked)} />
                <span>Fit in one Tiny Tapeout tile</span>
              </label>
            </div>
            <div className="build-row">
              <button className="build-button" type="submit" disabled aria-describedby="build-explanation">Build my chip</button>
              <p id="build-explanation">Live builds unlock after the EDA toolchain is verified.</p>
            </div>
          </form>
        </section>
        <section className="panel toolchain-panel" aria-labelledby="toolchain-title">
          <h2 id="toolchain-title">Toolchain</h2>
          <dl className="checks" aria-live="polite">
            {checks.map((check) => (
              <div className="check-row" key={check.name}>
                <dt>{check.name}</dt>
                <dd title={check.detail} className={check.ready ? "check-value ready" : "check-value"}>{check.label}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
      <section className="panel recordings-panel" aria-labelledby="recordings-title">
        <h2 id="recordings-title">Recorded runs</h2>
        <div className="empty-state" aria-live="polite">
          {recordingsError ? (
            <><h3>Recordings could not be loaded.</h3><p>Check the API connection and reload this page.</p></>
          ) : recordings === null ? (
            <><h3>Checking recorded runs…</h3><p>Only recordings from real tool runs appear here.</p></>
          ) : recordings.length === 0 ? (
            <><h3>No real recordings yet.</h3><p>Replay will appear here after a real tool run is recorded.</p></>
          ) : (
            <><h3>{recordings.length} recorded run{recordings.length === 1 ? "" : "s"} available.</h3><p>Replay controls unlock after the recorded-run workflow is verified.</p></>
          )}
        </div>
      </section>
    </>
  );
}
