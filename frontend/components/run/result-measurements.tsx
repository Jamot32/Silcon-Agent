import type { Metric, Targets } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { number } from "./format";
import { Signoff } from "./run-inspection";

type Status = "Met" | "Missed" | "Unknown" | "No target" | "Unverified";
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function TargetStatus({ value }: { value: Status }) {
  return <Badge variant="secondary" className={value === "Met" ? "bg-success/15 text-success" : value === "Missed" ? "bg-destructive/15 text-destructive" : "text-muted-foreground"}>{value}</Badge>;
}

export function ResultMeasurements({ metric, targets, tapeoutReady }: { metric?: Metric; targets: Targets; tapeoutReady: boolean }) {
  const clockKnown = finite(metric?.clock_mhz) && finite(metric?.wns_ns);
  const clockStatus: Status = targets.clock_mhz == null ? "No target" : !clockKnown ? "Unknown" : metric!.wns_ns >= 0 && metric!.clock_mhz >= targets.clock_mhz ? "Met" : "Missed";
  const slackStatus: Status = !finite(metric?.wns_ns) ? "Unknown" : metric.wns_ns >= 0 ? "Met" : "Missed";
  const areaStatus: Status = targets.max_area_um2 == null ? "No target" : !finite(metric?.area_um2) ? "Unknown" : metric.area_um2 <= targets.max_area_um2 ? "Met" : "Missed";
  const fitStatus: Status = targets.fit == null ? "No target" : tapeoutReady ? "Met" : "Unverified";
  const clean = metric?.drc_ok === true && metric?.lvs_ok === true;
  const failed = metric?.drc_ok === false || metric?.lvs_ok === false;
  return <Card role="region" aria-labelledby="result-measurements-title">
    <CardHeader><CardTitle id="result-measurements-title" role="heading" aria-level={2} className="text-lg">Targets and measurements</CardTitle></CardHeader>
    <CardContent className="space-y-5">
    <Table data-testid="result-targets"><TableHeader><TableRow><TableHead className="h-9 text-muted-foreground"><span className="sr-only">Measurement</span></TableHead><TableHead className="h-9 text-muted-foreground">Target</TableHead><TableHead className="h-9 text-muted-foreground">Measured</TableHead><TableHead className="h-9 text-muted-foreground">Status</TableHead></TableRow></TableHeader><TableBody>
      <TableRow><TableHead scope="row" className="font-medium whitespace-normal" title="Clock is the configured physical-flow target; passing WNS confirms timing at that target.">Clock</TableHead><TableCell>{targets.clock_mhz == null ? "Not specified" : `${number(targets.clock_mhz)} MHz`}</TableCell><TableCell>{finite(metric?.clock_mhz) ? `${number(metric.clock_mhz)} MHz` : "—"}</TableCell><TableCell><TargetStatus value={clockStatus} /></TableCell></TableRow>
      <TableRow><TableHead scope="row" className="font-medium whitespace-normal">WNS</TableHead><TableCell>≥ 0 ns</TableCell><TableCell>{finite(metric?.wns_ns) ? `${number(metric.wns_ns, 3)} ns` : "—"}</TableCell><TableCell><TargetStatus value={slackStatus} /></TableCell></TableRow>
      <TableRow><TableHead scope="row" className="font-medium whitespace-normal">Max area</TableHead><TableCell>{targets.max_area_um2 == null ? "Not specified" : `${number(targets.max_area_um2)} µm²`}</TableCell><TableCell>{finite(metric?.area_um2) ? `${number(metric.area_um2)} µm²` : "—"}</TableCell><TableCell><TargetStatus value={areaStatus} /></TableCell></TableRow>
      <TableRow><TableHead scope="row" className="font-medium whitespace-normal">Tiny Tapeout tile</TableHead><TableCell className="whitespace-normal">{targets.fit === "tt_1x1_tile" ? "1 Tiny Tapeout tile" : "Not specified"}</TableCell><TableCell className="whitespace-normal">{targets.fit == null ? "—" : tapeoutReady ? "Verified" : "Wrapper integration unverified"}</TableCell><TableCell><TargetStatus value={fitStatus} /></TableCell></TableRow>
    </TableBody></Table>
    <dl className="divide-y rounded-lg border text-sm"><div className="flex items-center justify-between gap-4 px-3 py-2.5"><dt className="text-muted-foreground">Cell count</dt><dd className="tabular-nums">{number(metric?.cell_count, 0)}</dd></div><div className="flex items-center justify-between gap-4 px-3 py-2.5"><dt className="text-muted-foreground" title="Flow-reported total power from the last reported process corner.">Reported power</dt><dd className="tabular-nums">{metric?.power_mw == null ? "—" : `${number(metric.power_mw, 6)} mW`}</dd></div></dl>
    <section className="space-y-3" data-testid="result-signoff" aria-labelledby="result-signoff-title"><h2 id="result-signoff-title" className="text-base font-medium">Signoff</h2><dl className="divide-y rounded-lg border text-sm"><div className="flex items-center justify-between gap-4 px-3 py-2.5"><dt className="text-muted-foreground">DRC</dt><dd><Signoff value={metric?.drc_ok} /></dd></div><div className="flex items-center justify-between gap-4 px-3 py-2.5"><dt className="text-muted-foreground">LVS</dt><dd><Signoff value={metric?.lvs_ok} /></dd></div></dl>
      <p className="text-sm leading-relaxed text-muted-foreground">{clean ? "Block signoff is clean." : failed ? "Block signoff failed." : "Block signoff is incomplete."}{!tapeoutReady ? " Tiny Tapeout wrapper and shuttle integration require separate verification." : ""}</p>
    </section>
    </CardContent>
  </Card>;
}
