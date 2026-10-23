"use client";

import { Area, CartesianGrid, ComposedChart, LabelList, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Metric } from "@/lib/api";
import { number } from "./format";

export default function MetricsChart({ metrics }: { metrics: Metric[] }) {
  const areaMax = Math.max(1, ...metrics.map((metric) => metric.area_um2 ?? 0));
  const slack = metrics.flatMap((metric) => metric.wns_ns == null ? [] : [metric.wns_ns]);
  const slackMin = Math.min(-1, ...slack);
  const slackMax = Math.max(1, ...slack);
  return <div className="metrics-chart" data-testid="metrics-chart" data-point-count={metrics.length} role="img" aria-label={`Area and worst negative slack from ${metrics.length} real physical design runs`}>
    {metrics.length ? <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <ComposedChart data={metrics} margin={{ top: 24, right: 7, left: -12, bottom: 4 }} accessibilityLayer>
        <CartesianGrid stroke="#2A3943" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="flow_index" tick={{ fill: "#A7B6C6", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#53636F" }} tickFormatter={(value) => `Flow ${value}`} interval={0} />
        <YAxis yAxisId="area" domain={[0, Math.ceil(areaMax * 1.2 / 100) * 100]} width={56} tick={{ fill: "#A7B6C6", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#53636F" }} tickFormatter={(value: number) => number(value, 0)} />
        <YAxis yAxisId="slack" orientation="right" domain={[slackMin, slackMax]} width={30} tick={{ fill: "#A7B6C6", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#53636F" }} />
        <Tooltip contentStyle={{ background: "#131E26", border: "1px solid #40515E", borderRadius: 4, fontSize: 12 }} labelFormatter={(value) => `Flow ${value}`} formatter={(value, name) => [typeof value === "number" ? number(value, 3) : String(value), name]} />
        <ReferenceLine yAxisId="slack" y={0} stroke="#7E909F" strokeDasharray="4 3" />
        <Area yAxisId="area" type="linear" dataKey="area_um2" name="Area (µm²)" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.1} strokeWidth={2} dot={{ r: 3.5, fill: "var(--accent)", strokeWidth: 0 }} isAnimationActive={false} connectNulls={false}>
          <LabelList dataKey="area_um2" position="top" offset={8} fill="#A8EDE8" fontSize={11} formatter={(value) => typeof value === "number" ? number(value) : ""} />
        </Area>
        <Line yAxisId="slack" type="linear" dataKey="wns_ns" name="WNS (ns)" stroke="#C3CCD4" strokeWidth={2} dot={{ r: 3, fill: "#C3CCD4", strokeWidth: 0 }} isAnimationActive={false} connectNulls={false} />
      </ComposedChart>
    </ResponsiveContainer> : <p className="panel-empty">Physical metrics appear after the first flow completes.</p>}
  </div>;
}
