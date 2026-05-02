"use client";

/**
 * ChartIntentRenderer — Stage 4 cleanup. Routes chart_intent rows from MCP
 * tool calls through the new SVG engine. The DSL is already a near-perfect
 * subset of ChartSpec, so the conversion is just `__dsl: true` + a couple
 * of optional field renames.
 *
 * _chart DSL schema:
 *   type:       "line" | "bar" | "scatter"
 *   title:      string
 *   data:       Record<string, unknown>[]   (rows from MCP)
 *   x:          string                      (x-axis field)
 *   y:          string[]                    (y-axis fields — multi-series)
 *   rules?:     { value, label, style? }[]
 *   highlight?: { field, eq }
 *   x_label?, y_label?:  axis title overrides (currently unused by SVG engine)
 */

import { SvgChartRenderer } from "@/components/pipeline-builder/charts";
import "@/styles/chart-tokens.css";

interface ChartRule {
  value: number;
  label: string;
  style?: "danger" | "warning" | "center";
}

interface ChartHighlight {
  field: string;
  eq: unknown;
}

export interface ChartIntent {
  type: "line" | "bar" | "scatter";
  title: string;
  data: Record<string, unknown>[];
  x: string;
  y: string[];
  rules?: ChartRule[];
  highlight?: ChartHighlight;
  x_label?: string;
  y_label?: string;
}

function intentToChartSpec(intent: ChartIntent): Record<string, unknown> {
  return {
    __dsl: true,
    type: intent.type,
    title: intent.title,
    data: intent.data,
    x: intent.x,
    y: intent.y,
    ...(intent.rules ? { rules: intent.rules } : {}),
    ...(intent.highlight ? { highlight: intent.highlight } : {}),
  };
}

function SingleChart({ intent }: { intent: ChartIntent }) {
  if (!intent.data || !Array.isArray(intent.data) || intent.data.length === 0) {
    return (
      <div style={{ padding: 12, color: "#a0aec0", fontSize: 12 }}>
        {intent.title ?? "Chart"} — no data
      </div>
    );
  }
  return <SvgChartRenderer spec={intentToChartSpec(intent)} height={240} />;
}

export function ChartIntentRenderer({ charts }: { charts: ChartIntent[] }) {
  if (!charts || charts.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {charts.map((chart, i) => (
        <div key={i} style={{ background: "white", borderRadius: 8, overflow: "hidden" }}>
          <SingleChart intent={chart} />
        </div>
      ))}
    </div>
  );
}
