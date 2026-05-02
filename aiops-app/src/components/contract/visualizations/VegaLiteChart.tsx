"use client";

/**
 * VegaLiteChart — Vega-Lite spec adapter to the SVG chart engine.
 *
 * The runtime Vega/Vega-Lite dependency is gone. We translate the most common
 * shape produced by the orchestrator (`_build_spc_contract` in
 * python_ai_sidecar/agent_orchestrator_v2/helpers.py): layered SPC chart with
 * line + colored points + UCL/LCL/CL rules. Single-mark line/bar/point specs
 * also map cleanly. Anything else falls back to a placeholder card.
 */

import SvgChartRenderer from "@/components/pipeline-builder/charts/SvgChartRenderer";

interface Props {
  spec: Record<string, unknown>;
}

interface Layer {
  mark?: unknown;
  encoding?: Record<string, unknown>;
}

function getMarkType(mark: unknown): string | null {
  if (typeof mark === "string") return mark;
  if (mark && typeof mark === "object" && typeof (mark as { type?: unknown }).type === "string") {
    return (mark as { type: string }).type;
  }
  return null;
}

function getEncField(enc: Record<string, unknown> | undefined, key: string): string | undefined {
  const ch = enc?.[key] as { field?: unknown } | undefined;
  return typeof ch?.field === "string" ? ch.field : undefined;
}

function getEncDatum(enc: Record<string, unknown> | undefined, key: string): number | undefined {
  const ch = enc?.[key] as { datum?: unknown } | undefined;
  const v = Number(ch?.datum);
  return Number.isFinite(v) ? v : undefined;
}

function getMarkColor(mark: unknown): string | undefined {
  if (mark && typeof mark === "object" && typeof (mark as { color?: unknown }).color === "string") {
    return (mark as { color: string }).color;
  }
  return undefined;
}

function ruleStyleFromColor(color: string | undefined): "danger" | "center" | "warning" {
  if (!color) return "center";
  const c = color.toLowerCase();
  if (c.includes("e53e3e") || c.includes("#e5") || c.includes("red")) return "danger";
  if (c.includes("ed8936") || c.includes("orange") || c.includes("warn")) return "warning";
  return "center";
}

function vegaToChartSpec(spec: Record<string, unknown>): Record<string, unknown> | null {
  const dataObj = spec.data as { values?: unknown } | undefined;
  const values = Array.isArray(dataObj?.values) ? (dataObj!.values as Record<string, unknown>[]) : null;

  // ── Single-mark form ──────────────────────────────────────────────────
  if (!Array.isArray(spec.layer)) {
    const markType = getMarkType(spec.mark);
    const enc = spec.encoding as Record<string, unknown> | undefined;
    const xField = getEncField(enc, "x");
    const yField = getEncField(enc, "y");
    if (!values || !markType || !xField || !yField) return null;

    const chartType =
      markType === "line" ? "line" :
      markType === "bar" ? "bar" :
      markType === "point" || markType === "circle" || markType === "square" ? "scatter" :
      null;
    if (!chartType) return null;

    return {
      __dsl: true,
      type: chartType,
      data: values,
      x: xField,
      y: [yField],
    };
  }

  // ── Layered form (SPC chart pattern) ─────────────────────────────────
  if (!values) return null;
  const layers = spec.layer as Layer[];

  // Find the primary line layer
  const lineLayer = layers.find(l => getMarkType(l.mark) === "line");
  const pointLayer = layers.find(l => getMarkType(l.mark) === "point" || getMarkType(l.mark) === "circle");
  const ruleLayers = layers.filter(l => getMarkType(l.mark) === "rule");
  const primary = lineLayer ?? pointLayer;
  if (!primary) return null;

  const xField = getEncField(primary.encoding, "x");
  const yField = getEncField(primary.encoding, "y");
  if (!xField || !yField) return null;

  // Highlight: if point layer has a color encoding, mark the OOC group.
  const colorField = pointLayer ? getEncField(pointLayer.encoding, "color") : undefined;
  let highlight: { field: string; eq: unknown } | undefined;
  if (colorField) {
    // Common pattern: status field with PASS/OOC values; mark OOC points red.
    const sample = values.find(v => String(v[colorField]).toUpperCase() === "OOC");
    if (sample) {
      highlight = { field: colorField, eq: sample[colorField] };
    }
  }

  // Convert rule layers to ChartRule entries.
  const rules = ruleLayers
    .map((r, i) => {
      const v = getEncDatum(r.encoding, "y");
      if (v === undefined) return null;
      const color = getMarkColor(r.mark);
      const style = ruleStyleFromColor(color);
      // Best-effort label inference: order rules UCL/LCL/CL based on common pattern.
      const label = style === "center" ? "CL" : (i === 0 ? "UCL" : "LCL");
      return { value: v, label, style };
    })
    .filter((r): r is { value: number; label: string; style: "danger" | "center" | "warning" } => r !== null);

  const chartType = lineLayer ? "line" : "scatter";

  const out: Record<string, unknown> = {
    __dsl: true,
    type: chartType,
    data: values,
    x: xField,
    y: [yField],
  };
  if (rules.length > 0) out.rules = rules;
  if (highlight) out.highlight = highlight;
  return out;
}

export function VegaLiteChart({ spec }: Props) {
  const chartSpec = vegaToChartSpec(spec);
  if (!chartSpec) {
    return (
      <div style={{
        padding: 16, textAlign: "center",
        border: "1px dashed #fcd34d", borderRadius: 6,
        background: "#fffbeb", color: "#92400e", fontSize: 12,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>
          ⚠ Vega-Lite spec shape not supported by SVG engine
        </div>
        <div>此 visualization spec 暫無 SVG 對應；請改用內部 ChartSpec/ChartDSL 格式。</div>
      </div>
    );
  }
  return (
    <div className="pb-chart-card" style={{ minHeight: 200 }}>
      <SvgChartRenderer spec={chartSpec} height={280} />
    </div>
  );
}
