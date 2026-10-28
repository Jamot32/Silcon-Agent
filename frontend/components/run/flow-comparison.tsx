import type { Metric } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { number } from "./format";
import { Panel } from "./panel";

export function FlowComparison({ metrics, bestTag }: { metrics: Metric[]; bestTag: string | null }) {
  if (metrics.length === 0) return null;
  return <Panel id="flow-comparison-title" title="Measured flow comparison" aside={<span className="text-xs text-muted-foreground">{metrics.length} physical runs</span>} data-testid="flow-comparison" data-point-count={metrics.length}>
    <div className="px-4 pt-2"><Table className="text-xs"><TableHeader><TableRow><TableHead className="text-muted-foreground">Flow</TableHead><TableHead className="text-muted-foreground">Area (µm²)</TableHead><TableHead className="text-muted-foreground">WNS (ns)</TableHead><TableHead className="text-muted-foreground">Reported power (mW)</TableHead><TableHead className="text-muted-foreground">Selection</TableHead></TableRow></TableHeader><TableBody>
      {metrics.toSorted((a, b) => a.flow_index - b.flow_index).map((metric) => <TableRow key={metric.run_tag} data-selected={metric.run_tag === bestTag} className="data-[selected=true]:bg-primary/10">
        <TableCell><span className="font-medium">Flow {metric.flow_index}</span><small className="ml-2 font-mono text-[10px] text-muted-foreground">{metric.run_tag}</small></TableCell><TableCell className="tabular-nums">{number(metric.area_um2)}</TableCell><TableCell className="tabular-nums">{number(metric.wns_ns, 3)}</TableCell><TableCell className="tabular-nums">{number(metric.power_mw, 6)}</TableCell><TableCell>{metric.run_tag === bestTag ? <Badge variant="outline" className="border-primary/40 text-primary">Selected</Badge> : "—"}</TableCell>
      </TableRow>)}
    </TableBody></Table></div>
    <p className="px-4 pt-2 pb-3 text-xs text-muted-foreground">Power is the flow-reported total from its last reported corner.</p>
  </Panel>;
}
