import type { Metric, Targets } from "@/lib/api";
import { number } from "./format";
import { Signoff } from "./run-inspection";

type Status = "Met" | "Missed" | "Unknown" | "No target" | "Unverified";
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function TargetStatus({ value }: { value: Status }) {
  return <span className={value === "Met" ? "pass-text" : value === "Missed" ? "fail-text" : "muted"}>{value}</span>;
}

export function ResultMeasurements({ metric, targets, tapeoutReady }: { metric?: Metric; targets: Targets; tapeoutReady: boolean }) {
  const clockKnown = finite(metric?.clock_mhz) && finite(metric?.wns_ns);
  const clockStatus: Status = targets.clock_mhz == null ? "No target" : !clockKnown ? "Unknown" : metric!.wns_ns >= 0 && metric!.clock_mhz >= targets.clock_mhz ? "Met" : "Missed";
  const slackStatus: Status = !finite(metric?.wns_ns) ? "Unknown" : metric.wns_ns >= 0 ? "Met" : "Missed";
  const areaStatus: Status = targets.max_area_um2 == null ? "No target" : !finite(metric?.area_um2) ? "Unknown" : metric.area_um2 <= targets.max_area_um2 ? "Met" : "Missed";
  const fitStatus: Status = targets.fit == null ? "No target" : tapeoutReady ? "Met" : "Unverified";
  const clean = metric?.drc_ok === true && metric?.lvs_ok === true;
  const failed = metric?.drc_ok === false || metric?.lvs_ok === false;
  return <section className="instrument-panel result-measurements" aria-labelledby="result-measurements-title">
    <h2 id="result-measurements-title">Targets and measurements</h2>
    <div className="metric-table-scroll"><table className="result-target-table" data-testid="result-targets"><thead><tr><th><span className="sr-only">Measurement</span></th><th>Target</th><th>Measured</th><th>Status</th></tr></thead><tbody>
      <tr><th scope="row" title="Clock is the configured physical-flow target; passing WNS confirms timing at that target.">Clock</th><td>{targets.clock_mhz == null ? "Not specified" : `${number(targets.clock_mhz)} MHz`}</td><td>{finite(metric?.clock_mhz) ? `${number(metric.clock_mhz)} MHz` : "—"}</td><td><TargetStatus value={clockStatus} /></td></tr>
      <tr><th scope="row">WNS</th><td>≥ 0 ns</td><td>{finite(metric?.wns_ns) ? `${number(metric.wns_ns, 3)} ns` : "—"}</td><td><TargetStatus value={slackStatus} /></td></tr>
      <tr><th scope="row">Max area</th><td>{targets.max_area_um2 == null ? "Not specified" : `${number(targets.max_area_um2)} µm²`}</td><td>{finite(metric?.area_um2) ? `${number(metric.area_um2)} µm²` : "—"}</td><td><TargetStatus value={areaStatus} /></td></tr>
      <tr><th scope="row">Tiny Tapeout tile</th><td>{targets.fit === "tt_1x1_tile" ? "1 Tiny Tapeout tile" : "Not specified"}</td><td>{targets.fit == null ? "—" : tapeoutReady ? "Verified" : "Wrapper integration unverified"}</td><td><TargetStatus value={fitStatus} /></td></tr>
    </tbody></table></div>
    <dl className="result-measured-list"><div><dt>Cell count</dt><dd>{number(metric?.cell_count, 0)}</dd></div><div><dt title="Flow-reported total power from the last reported process corner.">Reported power</dt><dd>{metric?.power_mw == null ? "—" : `${number(metric.power_mw, 6)} mW`}</dd></div></dl>
    <section className="result-signoff" data-testid="result-signoff" aria-labelledby="result-signoff-title"><h2 id="result-signoff-title">Signoff</h2><dl className="result-measured-list"><div><dt>DRC</dt><dd><Signoff value={metric?.drc_ok} /></dd></div><div><dt>LVS</dt><dd><Signoff value={metric?.lvs_ok} /></dd></div></dl>
      <p>{clean ? "Block signoff is clean." : failed ? "Block signoff failed." : "Block signoff is incomplete."}{!tapeoutReady ? " Tiny Tapeout wrapper and shuttle integration require separate verification." : ""}</p>
    </section>
  </section>;
}
