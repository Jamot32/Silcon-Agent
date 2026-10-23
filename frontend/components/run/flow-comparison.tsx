import type { Metric } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { number } from "./format";

export function FlowComparison({ metrics, bestTag }: { metrics: Metric[]; bestTag: string | null }) {
  if (metrics.length === 0) return null;
  return <section className="instrument-panel flow-comparison" aria-labelledby="flow-comparison-title" data-testid="flow-comparison" data-point-count={metrics.length}>
    <header className="instrument-header"><h2 id="flow-comparison-title">Measured flow comparison</h2><span className="micro-label">{metrics.length} physical runs</span></header>
    <div className="metric-table-scroll"><table className="metric-table"><thead><tr><th>Flow</th><th>Area (µm²)</th><th>WNS (ns)</th><th>Reported power (mW)</th><th>Selection</th></tr></thead><tbody>
      {metrics.toSorted((a, b) => a.flow_index - b.flow_index).map((metric) => <tr key={metric.run_tag} data-selected={metric.run_tag === bestTag}>
        <td><span>Flow {metric.flow_index}</span><small>{metric.run_tag}</small></td><td>{number(metric.area_um2)}</td><td>{number(metric.wns_ns, 3)}</td><td>{number(metric.power_mw, 6)}</td><td>{metric.run_tag === bestTag ? <Badge variant="outline">Selected</Badge> : "—"}</td>
      </tr>)}
    </tbody></table></div>
    <p>Power is the flow-reported total from its last reported corner.</p>
  </section>;
}
