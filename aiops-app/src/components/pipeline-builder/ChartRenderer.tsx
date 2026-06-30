"use client";

import { ChartDSLRenderer, type ChartDSL } from "@/components/operations/SkillOutputRenderer";
import { VegaLiteChart } from "@/components/contract/visualizations/VegaLiteChart";
import DataResultView from "@/components/common/DataResultView";

/**
 * ChartRenderer — dispatcher between chart stacks:
 *   - empty card (placeholder)
 *   - table     (HTML table)
 *   - ChartDSL  (block_chart SPC mode)   → SvgChartRenderer (via ChartDSLRenderer)
 *   - Vega-Lite (block_chart classic)    → SvgChartRenderer (via VegaLiteChart adapter)
 *
 * Decision:
 *   spec.__dsl === true OR has `rules` / `highlight`  → ChartDSL
 *   has $schema "vega-lite" OR mark+encoding         → Vega-Lite adapter
 */

interface Props {
  spec: unknown;
  height?: number;
}

function looksLikeVegaLite(s: unknown): boolean {
  if (!s || typeof s !== "object") return false;
  const obj = s as Record<string, unknown>;
  const schema = obj.$schema;
  if (typeof schema === "string" && schema.includes("vega-lite")) return true;
  return "mark" in obj && "encoding" in obj;
}

function looksLikeChartDSL(s: unknown): s is ChartDSL & { __dsl?: boolean } {
  if (!s || typeof s !== "object") return false;
  const obj = s as Record<string, unknown>;
  if (obj.__dsl === true) return true;
  if (Array.isArray(obj.rules) && typeof obj.x === "string" && Array.isArray(obj.y)) return true;
  // boxplot / heatmap carry type marker even without rules
  const t = obj.type;
  if (t === "boxplot" || t === "heatmap") return true;
  return false;
}

export default function ChartRenderer({ spec, height }: Props) {
  if (looksLikeEmpty(spec)) {
    const s = spec as { title?: string; message?: string };
    return (
      <div
        data-testid="chart-renderer-empty"
        style={{
          padding: 20,
          textAlign: "center",
          border: "1px dashed #CBD5E1",
          borderRadius: 4,
          background: "#F8FAFC",
          color: "#64748B",
          fontSize: 12,
          margin: 12,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: "#475569", marginBottom: 4 }}>
          {s.title || "No data"}
        </div>
        <div>{s.message || "上游無資料，圖無法繪製"}</div>
      </div>
    );
  }
  if (looksLikeTable(spec)) {
    return <TableRenderer spec={normalizeTableSpec(spec)} />;
  }
  if (looksLikeChartDSL(spec)) {
    return (
      <div data-testid="chart-renderer-dsl" style={{ padding: 8 }}>
        <ChartDSLRenderer chart={spec as ChartDSL} />
      </div>
    );
  }
  return <VegaChartRenderer spec={spec} height={height} />;
}

function looksLikeEmpty(s: unknown): boolean {
  if (!s || typeof s !== "object") return false;
  return (s as Record<string, unknown>).type === "empty";
}

interface TableSpec {
  type: "table" | "data_view";
  title?: string;
  columns: string[];
  data: Array<Record<string, unknown>>;
  total_rows?: number;
}

function looksLikeTable(s: unknown): boolean {
  if (!s || typeof s !== "object") return false;
  const obj = s as Record<string, unknown>;
  // block_data_view emits {type:"data_view", rows, columns}; block_chart's
  // table branch emits {type:"table", data, columns}. Accept both — rows
  // is aliased to data in the renderer below so TableRenderer is uniform.
  const isTableType = obj.type === "table" || obj.type === "data_view";
  if (!isTableType) return false;
  const cols = obj.columns;
  const rowsOrData = obj.data ?? obj.rows;
  return Array.isArray(cols) && Array.isArray(rowsOrData);
}

function normalizeTableSpec(s: unknown): TableSpec {
  const obj = s as Record<string, unknown>;
  // data_view uses `rows`; table uses `data`. Normalize so TableRenderer
  // can read `.data` regardless of source block.
  return {
    type: (obj.type === "data_view" ? "data_view" : "table") as TableSpec["type"],
    title: obj.title as string | undefined,
    columns: obj.columns as string[],
    data: (obj.data ?? obj.rows ?? []) as Array<Record<string, unknown>>,
    total_rows: obj.total_rows as number | undefined,
  };
}

function TableRenderer({ spec }: { spec: TableSpec }) {
  return (
    <div data-testid="chart-renderer-table" style={{ padding: 12 }}>
      {spec.title && (
        <div style={{ fontSize: 13, fontWeight: 600, color: "#0F172A", marginBottom: 6 }}>
          {spec.title}
          {spec.total_rows != null && spec.total_rows > spec.data.length && (
            <span style={{ marginLeft: 8, fontSize: 11, color: "#64748B", fontWeight: 400 }}>
              (顯示前 {spec.data.length} / 共 {spec.total_rows} 筆)
            </span>
          )}
        </div>
      )}
      <div style={{ height: 320, display: "flex", flexDirection: "column" }}>
        <DataResultView result={spec.data} enableFullscreen={false} emptyText="無資料" />
      </div>
    </div>
  );
}

function VegaChartRenderer({ spec }: Props) {
  if (!looksLikeVegaLite(spec)) {
    return (
      <div
        data-testid="chart-render-error"
        style={{
          padding: 12,
          color: "#B91C1C",
          background: "#FEF2F2",
          border: "1px solid #FECACA",
          borderRadius: 4,
          fontSize: 12,
        }}
      >
        不是有效的 Vega-Lite spec（缺 $schema 或 mark/encoding）
      </div>
    );
  }
  return (
    <div data-testid="chart-renderer" style={{ padding: 12 }}>
      <VegaLiteChart spec={spec as Record<string, unknown>} />
    </div>
  );
}

export { looksLikeVegaLite, looksLikeChartDSL };
