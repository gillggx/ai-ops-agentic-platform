"use client";

/**
 * ChartIntentRenderer — converts _chart DSL objects into Vega-Lite specs
 * and renders them via the existing VegaLiteChart component.
 *
 * _chart DSL schema:
 *   type: "line" | "bar" | "scatter"
 *   title: string
 *   data: Record<string, unknown>[]   (rows from MCP)
 *   x: string                         (x-axis field)
 *   y: string[]                       (y-axis fields — multi-series)
 *   rules?: { value: number, label: string, style: "danger"|"warning"|"center" }[]
 *   highlight?: { field: string, eq: unknown }
 *   x_label?: string
 *   y_label?: string
 */

import { VegaLiteChart } from "@/components/contract/visualizations/VegaLiteChart";

// ── Types ──────────────────────────────────────────────────────────────────────

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

// ── Style mapping ──────────────────────────────────────────────────────────────

const RULE_COLORS: Record<string, string> = {
  danger:  "#e53e3e",
  warning: "#dd6b20",
  center:  "#718096",
};

const SERIES_COLORS = ["#4299e1", "#38a169", "#d69e2e", "#9f7aea", "#ed8936", "#e53e3e"];

// ── DSL → Vega-Lite transformer ────────────────────────────────────────────────

function intentToVegaLite(intent: ChartIntent): Record<string, unknown> {
  const { type, title, data, x, y, rules, highlight, x_label, y_label } = intent;

  const markType = type === "bar" ? "bar" : type === "scatter" ? "point" : "line";
  const mode = type === "scatter" ? undefined : "lines+markers";

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const layers: Record<string, unknown>[] = [];

  // Main data series (one layer per y field)
  for (let i = 0; i < y.length; i++) {
    const yField = y[i];
    const color = SERIES_COLORS[i % SERIES_COLORS.length];

    if (type === "line") {
      // Line layer
      layers.push({
        mark: { type: "line", color, strokeWidth: 1.5 },
        encoding: {
          x: { field: x, type: "ordinal", title: x_label ?? x, axis: { labelAngle: -60, labelFontSize: 7 } },
          y: { field: yField, type: "quantitative", title: y_label ?? yField, scale: { zero: false } },
        },
      });
      // Point overlay layer (with highlight coloring)
      if (highlight) {
        layers.push({
          mark: { type: "point", size: 50, filled: true },
          encoding: {
            x: { field: x, type: "ordinal" },
            y: { field: yField, type: "quantitative" },
            color: {
              condition: { test: `datum.${highlight.field} === '${highlight.eq}'`, value: "#e53e3e" },
              value: color,
            },
            tooltip: [
              { field: x, title: x_label ?? x },
              { field: yField, title: yField },
              ...(highlight ? [{ field: highlight.field, title: highlight.field }] : []),
            ],
          },
        });
      } else {
        layers.push({
          mark: { type: "point", size: 40, filled: true, color },
          encoding: {
            x: { field: x, type: "ordinal" },
            y: { field: yField, type: "quantitative" },
            tooltip: [
              { field: x, title: x_label ?? x },
              { field: yField, title: yField },
            ],
          },
        });
      }
    } else {
      // Bar or scatter — single layer per y
      layers.push({
        mark: { type: markType, ...(type === "scatter" ? { size: 60, filled: true } : {}), color },
        encoding: {
          x: {
            field: x,
            type: type === "bar" ? "nominal" : "ordinal",
            title: x_label ?? x,
            axis: { labelAngle: -45, labelFontSize: 8 },
          },
          y: { field: yField, type: "quantitative", title: y_label ?? yField, scale: { zero: false } },
          tooltip: [
            { field: x, title: x_label ?? x },
            { field: yField, title: yField },
          ],
        },
      });
    }
  }

  // Rule lines (UCL, LCL, CL, etc.)
  if (rules) {
    for (const rule of rules) {
      const ruleColor = RULE_COLORS[rule.style ?? "danger"] ?? "#e53e3e";
      const isDashed = rule.style === "center" ? [3, 3] : [6, 4];
      layers.push({
        mark: { type: "rule", color: ruleColor, strokeDash: isDashed, strokeWidth: 1.5 },
        encoding: { y: { datum: rule.value } },
      });
      // Label
      layers.push({
        mark: { type: "text", align: "right", dx: -2, fontSize: 9, color: ruleColor, fontWeight: "bold" },
        encoding: { y: { datum: rule.value }, text: { value: `${rule.label}=${rule.value}` }, x: { value: 0 } },
      });
    }
  }

  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    width: "container",
    height: 220,
    title: { text: title, fontSize: 12, anchor: "start" },
    data: { values: data },
    layer: layers,
  };
}

// ── Components ─────────────────────────────────────────────────────────────────

function SingleChart({ intent }: { intent: ChartIntent }) {
  if (!intent.data || !Array.isArray(intent.data) || intent.data.length === 0) {
    return (
      <div style={{ padding: 12, color: "#a0aec0", fontSize: 12 }}>
        {intent.title ?? "Chart"} — no data
      </div>
    );
  }
  const spec = intentToVegaLite(intent);
  return <VegaLiteChart spec={spec} />;
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
