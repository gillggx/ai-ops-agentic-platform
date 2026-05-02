"use client";

/**
 * ChartExplorer — interactive chart explorer for Generative UI.
 *
 * Receives flat data from backend (via SSE) and renders charts via the SVG
 * chart engine. Switching between datasets (SPC/APC/DC/...) and changing
 * filters happens client-side without API calls — all data is cached in
 * FlatDataContext.
 *
 * Plotly was removed in P2-1: every chart is now a ChartSpec passed to
 * SvgChartRenderer. The dual-axis overlay uses LineChart's `y_secondary`.
 */

import { useState, useMemo } from "react";
import SvgChartRenderer from "@/components/pipeline-builder/charts/SvgChartRenderer";
import type { FlatDataMetadata, UIConfig } from "@/context/FlatDataContext";

// ── Types ────────────────────────────────────────────────────────────────────

interface Props {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  flatData: Record<string, any[]>;
  metadata: FlatDataMetadata;
  uiConfig?: UIConfig | null;
  onClose?: () => void;
}

const DATASET_LABELS: Record<string, string> = {
  spc_data: "SPC",
  apc_data: "APC",
  dc_data: "DC",
  recipe_data: "Recipe",
  fdc_data: "FDC",
  ec_data: "EC",
};

const CHART_CONFIGS: Record<string, { x: string; y: string; group?: string; title: string }> = {
  spc_data: { x: "eventTime", y: "value", group: "chart_type", title: "SPC" },
  apc_data: { x: "eventTime", y: "value", group: "param_name", title: "APC" },
  dc_data: { x: "eventTime", y: "value", group: "sensor_name", title: "DC" },
  recipe_data: { x: "eventTime", y: "value", group: "param_name", title: "Recipe" },
  fdc_data: { x: "eventTime", y: "confidence", group: "classification", title: "FDC" },
  ec_data: { x: "eventTime", y: "value", group: "constant_name", title: "EC" },
};

// ── Component ────────────────────────────────────────────────────────────────

export function ChartExplorer({ flatData, metadata, uiConfig, onClose }: Props) {
  // Determine initial dataset from uiConfig or first available
  const isOverlay = uiConfig?.initial_view?.data_source === "overlay";
  const initialDs = isOverlay
    ? metadata.available_datasets[0] ?? "spc_data"
    : (uiConfig?.initial_view?.data_source ?? metadata.available_datasets[0] ?? "spc_data");

  const [activeDataset, setActiveDataset] = useState(initialDs);
  const [overlayMode, setOverlayMode] = useState(isOverlay);

  // Initialize filter from viz_hint if present
  const vizFilter = uiConfig?.initial_view?.filter as Record<string, string> | undefined;
  const initialFilterVal = vizFilter ? String(Object.values(vizFilter)[0] ?? "") : "";
  const [filterValue, setFilterValue] = useState<string>(initialFilterVal);

  // Multi-chart: array of additional chart panels (each with its own filter value)
  const [extraCharts, setExtraCharts] = useState<string[]>([]);
  // Chart type selector (line is default, histogram/box for distribution analysis, heatmap for correlation)
  const [chartType, setChartType] = useState<"line" | "scatter" | "histogram" | "box" | "heatmap">("line");

  // Overlay state
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const overlayHint = uiConfig?.initial_view as any;
  const [overlayLeft, setOverlayLeft] = useState({
    dataset: overlayHint?.left?.dataset ?? "spc_data",
    field: overlayHint?.left?.field ?? "value",
    filterKey: Object.keys(overlayHint?.left?.filter ?? {})[0] ?? "",
    filterVal: Object.values(overlayHint?.left?.filter ?? {})[0] as string ?? "",
  });
  const [overlayRight, setOverlayRight] = useState({
    dataset: overlayHint?.right?.dataset ?? "apc_data",
    field: overlayHint?.right?.field ?? "value",
    filterKey: Object.keys(overlayHint?.right?.filter ?? {})[0] ?? "",
    filterVal: Object.values(overlayHint?.right?.filter ?? {})[0] as string ?? "",
  });

  // Get current dataset
  const rawData = flatData[activeDataset] ?? [];
  const config = CHART_CONFIGS[activeDataset] ?? { x: "eventTime", y: "value", title: activeDataset };

  // Determine available filter options for current dataset
  const groupField = config.group;
  const groupValues = useMemo(() => {
    if (!groupField) return [];
    const vals = new Set<string>();
    for (const row of rawData) {
      const v = row[groupField];
      if (v != null) vals.add(String(v));
    }
    return [...vals].sort();
  }, [rawData, groupField]);

  // filteredData = rawData (no pre-filter — group selection handled by effectiveFilterValue)
  const filteredData = rawData;

  // Auto-select first group value if none selected (one at a time)
  const effectiveFilterValue = filterValue || (groupValues.length > 0 ? groupValues[0] : "");

  // Apply group filter (always one group at a time, never "All")
  const displayData = useMemo(() => {
    if (!groupField || !effectiveFilterValue) return filteredData;
    return filteredData.filter((r) => String(r[groupField]) === effectiveFilterValue);
  }, [filteredData, groupField, effectiveFilterValue]);

  // SPC: build rules + highlight from UCL/LCL/CL
  const spcRulesAndHighlight = useMemo(() => {
    if (activeDataset !== "spc_data" || !displayData.length) return { rules: [] as Array<Record<string, unknown>>, highlight: undefined };
    const ucl = displayData[0]?.ucl;
    const lcl = displayData[0]?.lcl;
    const vals = displayData.map((r) => r.value).filter((v: unknown) => typeof v === "number") as number[];
    const cl = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
    const rules: Array<Record<string, unknown>> = [];
    if (typeof ucl === "number") rules.push({ value: ucl, label: "UCL", style: "danger" });
    if (typeof lcl === "number") rules.push({ value: lcl, label: "LCL", style: "danger" });
    if (cl) rules.push({ value: cl, label: "CL", style: "center" });
    return {
      rules,
      highlight: { field: "is_ooc", eq: true } as Record<string, unknown>,
    };
  }, [activeDataset, displayData]);

  // Heatmap correlation matrix (compute_results or derived)
  const heatmapData = useMemo(() => {
    const cr = flatData["compute_results"];
    if (cr && Array.isArray(cr) && cr.length > 0 && cr[0]?.matrix && cr[0]?.params) {
      return { params: cr[0].params as string[], matrix: cr[0].matrix as number[][] };
    }
    if (!groupField || !rawData.length) return null;
    const groups = [...new Set(rawData.map((r) => String(r[groupField])))].sort().slice(0, 10);
    if (groups.length < 2) return null;
    const valuesByGroup: Record<string, number[]> = {};
    for (const g of groups) {
      valuesByGroup[g] = rawData
        .filter((r) => String(r[groupField]) === g)
        .map((r) => r[config.y])
        .filter((v: unknown) => typeof v === "number") as number[];
    }
    const n = groups.length;
    const matrix: number[][] = Array.from({ length: n }, () => Array(n).fill(0));
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const a = valuesByGroup[groups[i]], b = valuesByGroup[groups[j]];
        const len = Math.min(a.length, b.length);
        if (len < 3) { matrix[i][j] = 0; continue; }
        const ax = a.slice(0, len), bx = b.slice(0, len);
        const ma = ax.reduce((s, v) => s + v, 0) / len;
        const mb = bx.reduce((s, v) => s + v, 0) / len;
        let num = 0, da = 0, db = 0;
        for (let k = 0; k < len; k++) {
          const ai = ax[k] - ma, bi = bx[k] - mb;
          num += ai * bi; da += ai * ai; db += bi * bi;
        }
        const denom = Math.sqrt(da * db);
        matrix[i][j] = denom > 0 ? Math.round((num / denom) * 1000) / 1000 : 0;
      }
    }
    return { params: groups, matrix };
  }, [flatData, rawData, groupField, config]);

  return (
    <div style={{ background: "#fff", borderRadius: 8, border: "1px solid #e2e8f0", overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 16px", borderBottom: "1px solid #e2e8f0", background: "#f7f8fc",
      }}>
        <span style={{ fontSize: "var(--fs-lg)", fontWeight: 700, color: "#1a202c" }}>
          Data Explorer
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-sm)" }}>
          <span style={{ fontSize: "var(--fs-xs)", color: "#718096" }}>
            {metadata.total_events} events | {metadata.ooc_count} OOC ({metadata.ooc_rate}%)
          </span>
          {onClose && (
            <button onClick={onClose} style={{
              background: "none", border: "none", cursor: "pointer", color: "#a0aec0", fontSize: 16,
            }}>
              x
            </button>
          )}
        </div>
      </div>

      {/* Dataset Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0", background: "#fff" }}>
        {metadata.available_datasets.map((ds) => (
          <button
            key={ds}
            onClick={() => { setOverlayMode(false); setActiveDataset(ds); setFilterValue(""); setExtraCharts([]); }}
            style={{
              padding: "8px 16px", fontSize: 12,
              fontWeight: !overlayMode && activeDataset === ds ? 700 : 400,
              color: !overlayMode && activeDataset === ds ? "#2b6cb0" : "#718096", cursor: "pointer",
              borderBottom: !overlayMode && activeDataset === ds ? "2px solid #2b6cb0" : "2px solid transparent",
              background: "transparent", border: "none",
            }}
          >
            {DATASET_LABELS[ds] ?? ds}
          </button>
        ))}
        {metadata.available_datasets.length >= 2 && (
          <button
            onClick={() => setOverlayMode(true)}
            style={{
              padding: "8px 16px", fontSize: 12,
              fontWeight: overlayMode ? 700 : 400,
              color: overlayMode ? "#9f7aea" : "#718096", cursor: "pointer",
              borderBottom: overlayMode ? "2px solid #9f7aea" : "2px solid transparent",
              background: "transparent", border: "none",
            }}
          >
            +Overlay
          </button>
        )}
      </div>

      {/* ── Overlay Mode ── */}
      {overlayMode && (
        <div>
          <div style={{ display: "flex", gap: 12, padding: "10px 16px", borderBottom: "1px solid #f0f0f0", alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "#718096" }}>Left Y:</span>
            <select value={overlayLeft.dataset} onChange={(e) => setOverlayLeft(p => ({...p, dataset: e.target.value}))}
              style={{ fontSize: 11, padding: "3px 6px", borderRadius: 4, border: "1px solid #cbd5e0" }}>
              {metadata.available_datasets.map(ds => <option key={ds} value={ds}>{DATASET_LABELS[ds]}</option>)}
            </select>
            <select value={overlayLeft.filterVal} onChange={(e) => {
              const cfg = CHART_CONFIGS[overlayLeft.dataset];
              setOverlayLeft(p => ({...p, filterKey: cfg?.group ?? "", filterVal: e.target.value}));
            }} style={{ fontSize: 11, padding: "3px 6px", borderRadius: 4, border: "1px solid #cbd5e0" }}>
              {[...new Set((flatData[overlayLeft.dataset] ?? []).map((r: Record<string,unknown>) => String(r[CHART_CONFIGS[overlayLeft.dataset]?.group ?? ""] ?? "")))].filter(Boolean).sort().map(v =>
                <option key={v} value={v}>{v}</option>
              )}
            </select>
            <span style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginLeft: 8 }}>Right Y:</span>
            <select value={overlayRight.dataset} onChange={(e) => setOverlayRight(p => ({...p, dataset: e.target.value}))}
              style={{ fontSize: 11, padding: "3px 6px", borderRadius: 4, border: "1px solid #cbd5e0" }}>
              {metadata.available_datasets.map(ds => <option key={ds} value={ds}>{DATASET_LABELS[ds]}</option>)}
            </select>
            <select value={overlayRight.filterVal} onChange={(e) => {
              const cfg = CHART_CONFIGS[overlayRight.dataset];
              setOverlayRight(p => ({...p, filterKey: cfg?.group ?? "", filterVal: e.target.value}));
            }} style={{ fontSize: 11, padding: "3px 6px", borderRadius: 4, border: "1px solid #cbd5e0" }}>
              {[...new Set((flatData[overlayRight.dataset] ?? []).map((r: Record<string,unknown>) => String(r[CHART_CONFIGS[overlayRight.dataset]?.group ?? ""] ?? "")))].filter(Boolean).sort().map(v =>
                <option key={v} value={v}>{v}</option>
              )}
            </select>
          </div>
          <OverlayChart
            flatData={flatData}
            left={overlayLeft}
            right={overlayRight}
          />
        </div>
      )}

      {/* ── Single Dataset Mode ── */}
      {/* Filter Controls — one group at a time, no "All" */}
      {!overlayMode && groupField && groupValues.length > 1 && (
        <div style={{ display: "flex", gap: 8, padding: "8px 16px", borderBottom: "1px solid #f0f0f0", alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "#718096" }}>Filter:</span>
          <select
            value={effectiveFilterValue}
            onChange={(e) => { setFilterValue(e.target.value); }}
            style={{ fontSize: 11, padding: "3px 8px", borderRadius: 4, border: "1px solid #cbd5e0" }}
          >
            {groupValues.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
          <span style={{ fontSize: 11, color: "#a0aec0" }}>
            {displayData.length} rows
          </span>
          <button
            onClick={() => {
              const shown = new Set([effectiveFilterValue, ...extraCharts]);
              const next = groupValues.find(v => !shown.has(v));
              if (next) setExtraCharts(prev => [...prev, next]);
            }}
            disabled={extraCharts.length + 1 >= groupValues.length}
            style={{
              marginLeft: 8, padding: "2px 8px", fontSize: 11, borderRadius: 4,
              border: "1px solid #cbd5e0", background: "#fff", cursor: "pointer",
              color: extraCharts.length + 1 >= groupValues.length ? "#cbd5e0" : "#4299e1",
            }}
          >
            + Chart
          </button>
          {extraCharts.length > 0 && (
            <button
              onClick={() => setExtraCharts([])}
              style={{ padding: "2px 8px", fontSize: 11, borderRadius: 4, border: "1px solid #cbd5e0", background: "#fff", cursor: "pointer", color: "#e53e3e" }}
            >
              Clear
            </button>
          )}
        </div>
      )}

      {/* Chart Type Selector */}
      {!overlayMode && (
        <div style={{ display: "flex", gap: 4, padding: "6px 16px", borderBottom: "1px solid #f0f0f0" }}>
          {(["line", "scatter", "histogram", "box", ...(heatmapData ? ["heatmap" as const] : [])] as const).map((ct) => (
            <button
              key={ct}
              onClick={() => setChartType(ct)}
              style={{
                padding: "3px 10px", fontSize: 11, borderRadius: 4,
                border: chartType === ct ? "1px solid #2b6cb0" : "1px solid #e2e8f0",
                background: chartType === ct ? "#ebf8ff" : "#fff",
                color: chartType === ct ? "#2b6cb0" : "#718096",
                fontWeight: chartType === ct ? 600 : 400,
                cursor: "pointer",
              }}
            >
              {ct === "line" ? "Line" : ct === "scatter" ? "Scatter" : ct === "histogram" ? "Histogram" : ct === "box" ? "Box Plot" : "Heatmap"}
            </button>
          ))}
        </div>
      )}

      {/* Chart (single dataset mode) */}
      {!overlayMode && displayData.length > 0 ? (
        <SingleChart
          chartType={chartType}
          displayData={displayData}
          rawData={rawData}
          config={config}
          groupField={groupField}
          spcExtras={spcRulesAndHighlight}
          heatmapData={heatmapData}
        />
      ) : !overlayMode ? (
        <div style={{ padding: 40, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>
          No data for {DATASET_LABELS[activeDataset] ?? activeDataset}
        </div>
      ) : null}

      {/* Extra charts (from + button) */}
      {!overlayMode && extraCharts.map((ecFilter, ecIdx) => {
        const ecData = groupField
          ? filteredData.filter((r) => String(r[groupField]) === ecFilter)
          : [];
        if (!ecData.length) return null;
        const ucl = ecData[0]?.ucl;
        const lcl = ecData[0]?.lcl;
        const rules: Array<Record<string, unknown>> = [];
        if (activeDataset === "spc_data") {
          if (typeof ucl === "number") rules.push({ value: ucl, label: "UCL", style: "danger" });
          if (typeof lcl === "number") rules.push({ value: lcl, label: "LCL", style: "danger" });
        }
        const spec = {
          __dsl: true,
          type: "line",
          data: ecData,
          x: config.x,
          y: [config.y],
          rules,
          highlight: activeDataset === "spc_data" ? { field: "is_ooc", eq: true } : undefined,
        };
        return (
          <div key={ecIdx} style={{ borderTop: "1px solid #e2e8f0" }}>
            <div style={{ padding: "4px 16px", fontSize: 11, fontWeight: 600, color: "#718096", display: "flex", alignItems: "center", gap: 8 }}>
              <span>Filter:</span>
              <select
                value={ecFilter}
                onChange={(e) => setExtraCharts(prev => prev.map((v, i) => i === ecIdx ? e.target.value : v))}
                style={{ fontSize: 11, padding: "2px 6px", borderRadius: 4, border: "1px solid #cbd5e0" }}
              >
                {groupValues.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
              <span style={{ color: "#a0aec0" }}>{ecData.length} rows</span>
              <button onClick={() => setExtraCharts(prev => prev.filter((_, i) => i !== ecIdx))}
                style={{ marginLeft: "auto", border: "none", background: "none", color: "#e53e3e", cursor: "pointer", fontSize: 11 }}>x</button>
            </div>
            <div className="pb-chart-card" style={{ padding: 4 }}>
              <SvgChartRenderer spec={spec} height={220} />
            </div>
          </div>
        );
      })}

      {/* Data Table — collapsible, shows filtered data */}
      {!overlayMode && displayData.length > 0 && (
        <DataTableSection data={displayData} datasetName={`${DATASET_LABELS[activeDataset] ?? activeDataset} — ${effectiveFilterValue || "all"}`} />
      )}
    </div>
  );
}

// ── Single chart dispatcher (line / scatter / histogram / box / heatmap) ────

function SingleChart({
  chartType, displayData, rawData, config, groupField, spcExtras, heatmapData,
}: {
  chartType: "line" | "scatter" | "histogram" | "box" | "heatmap";
  displayData: Record<string, unknown>[];
  rawData: Record<string, unknown>[];
  config: { x: string; y: string; group?: string };
  groupField?: string;
  spcExtras: { rules: Array<Record<string, unknown>>; highlight?: Record<string, unknown> };
  heatmapData: { params: string[]; matrix: number[][] } | null;
}) {
  if (chartType === "histogram") {
    const numericCount = displayData.map((r) => r[config.y]).filter((v) => typeof v === "number").length;
    if (numericCount < 5) {
      return (
        <div style={{ padding: 40, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>
          Histogram requires at least 5 numeric data points
        </div>
      );
    }
    const spec = {
      __dsl: true,
      type: "histogram",
      data: displayData,
      x: config.y,
      y: [config.y],
    };
    return (
      <div className="pb-chart-card" style={{ padding: 8 }}>
        <SvgChartRenderer spec={spec} height={350} />
      </div>
    );
  }

  if (chartType === "box") {
    if (!groupField) {
      const spec = {
        __dsl: true,
        type: "box_plot",
        data: displayData.map(r => ({ group: "all", value: r[config.y] })),
        x: "group",
        y: ["value"],
        group_by: "group",
      };
      return (
        <div className="pb-chart-card" style={{ padding: 8 }}>
          <SvgChartRenderer spec={spec} height={350} />
        </div>
      );
    }
    const groups = [...new Set(rawData.map((r) => String(r[groupField])))].sort().slice(0, 10);
    const data: Array<Record<string, unknown>> = [];
    for (const g of groups) {
      for (const r of rawData) {
        if (String(r[groupField]) === g && typeof r[config.y] === "number") {
          data.push({ group: g, value: r[config.y] });
        }
      }
    }
    const spec = {
      __dsl: true,
      type: "box_plot",
      data,
      x: "group",
      y: ["value"],
      group_by: "group",
    };
    return (
      <div className="pb-chart-card" style={{ padding: 8 }}>
        <SvgChartRenderer spec={spec} height={350} />
      </div>
    );
  }

  if (chartType === "heatmap" && heatmapData) {
    // Long-form rows so HeatmapDendro renders a labelled matrix.
    const data: Array<Record<string, unknown>> = [];
    heatmapData.params.forEach((rp, ri) => {
      heatmapData.params.forEach((cp, ci) => {
        data.push({ row: rp, col: cp, value: heatmapData.matrix[ri][ci] });
      });
    });
    const spec = {
      __dsl: true,
      type: "heatmap",
      data,
      x: "col",
      y: ["row"],
      x_column: "col",
      y_column: "row",
      value_column: "value",
      cluster: false,
    };
    return (
      <div className="pb-chart-card" style={{ padding: 8 }}>
        <SvgChartRenderer spec={spec} height={400} />
      </div>
    );
  }

  // line / scatter
  const spec = {
    __dsl: true,
    type: chartType,
    data: displayData,
    x: config.x,
    y: [config.y],
    rules: spcExtras.rules,
    highlight: spcExtras.highlight,
  };
  return (
    <div className="pb-chart-card" style={{ padding: 8 }}>
      <SvgChartRenderer spec={spec} height={chartType === "scatter" ? 320 : 320} />
    </div>
  );
}

// ── Overlay (dual-axis line) ────────────────────────────────────────────────

function OverlayChart({
  flatData, left, right,
}: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  flatData: Record<string, any[]>;
  left: { dataset: string; field: string; filterKey: string; filterVal: string };
  right: { dataset: string; field: string; filterKey: string; filterVal: string };
}) {
  const leftCfg = CHART_CONFIGS[left.dataset] ?? { x: "eventTime", y: "value" };
  const rightCfg = CHART_CONFIGS[right.dataset] ?? { x: "eventTime", y: "value" };

  let leftData = flatData[left.dataset] ?? [];
  let rightData = flatData[right.dataset] ?? [];

  const leftGroupField = leftCfg.group ?? "";
  const rightGroupField = rightCfg.group ?? "";
  const leftGroupVals = leftGroupField
    ? [...new Set(leftData.map((r: Record<string, unknown>) => String(r[leftGroupField] ?? "")))].filter(Boolean).sort()
    : [];
  const rightGroupVals = rightGroupField
    ? [...new Set(rightData.map((r: Record<string, unknown>) => String(r[rightGroupField] ?? "")))].filter(Boolean).sort()
    : [];
  const effectiveLeftFilter = left.filterVal || leftGroupVals[0] || "";
  const effectiveRightFilter = right.filterVal || rightGroupVals[0] || "";

  if (leftGroupField && effectiveLeftFilter) {
    leftData = leftData.filter((r: Record<string, unknown>) => String(r[leftGroupField]) === effectiveLeftFilter);
  }
  if (rightGroupField && effectiveRightFilter) {
    rightData = rightData.filter((r: Record<string, unknown>) => String(r[rightGroupField]) === effectiveRightFilter);
  }

  const leftLabel = effectiveLeftFilter || DATASET_LABELS[left.dataset] || left.dataset;
  const rightLabel = effectiveRightFilter || DATASET_LABELS[right.dataset] || right.dataset;

  // Merge by eventTime — left primary, right secondary.
  const byTime = new Map<string, Record<string, unknown>>();
  for (const r of leftData) {
    const key = String(r[leftCfg.x] ?? "");
    if (!key) continue;
    byTime.set(key, { ...(byTime.get(key) ?? {}), [leftCfg.x]: r[leftCfg.x], [leftLabel]: r[leftCfg.y] });
  }
  for (const r of rightData) {
    const key = String(r[rightCfg.x] ?? "");
    if (!key) continue;
    byTime.set(key, { ...(byTime.get(key) ?? {}), [leftCfg.x]: r[rightCfg.x], [rightLabel]: r[rightCfg.y] });
  }
  const merged = [...byTime.values()].sort((a, b) =>
    String(a[leftCfg.x]).localeCompare(String(b[leftCfg.x]))
  );

  const spec = {
    __dsl: true,
    type: "line",
    data: merged,
    x: leftCfg.x,
    y: [leftLabel],
    y_secondary: [rightLabel],
  };

  return (
    <div className="pb-chart-card" style={{ padding: 8 }}>
      <SvgChartRenderer spec={spec} height={350} />
    </div>
  );
}

// ── Data Table Section (collapsible) ─────────────────────────────────────────

function DataTableSection({ data, datasetName }: { data: Record<string, unknown>[]; datasetName: string }) {
  const [expanded, setExpanded] = useState(false);
  const cols = Object.keys(data[0] ?? {});
  const displayRows = expanded ? data.slice(0, 100) : data.slice(0, 5);

  return (
    <div style={{ borderTop: "1px solid #e2e8f0" }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: "8px 16px", cursor: "pointer", fontSize: 12, fontWeight: 600,
          color: "#718096", display: "flex", justifyContent: "space-between", alignItems: "center",
          background: "#fafbfc",
        }}
      >
        <span>📋 {datasetName} Data ({data.length} rows)</span>
        <span style={{ fontSize: 10 }}>{expanded ? "▼ 收合" : "▶ 展開"}</span>
      </div>
      {(expanded || data.length <= 5) && (
        <div style={{ maxHeight: 300, overflowY: "auto", overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead>
              <tr>
                {cols.map((c) => (
                  <th key={c} style={{
                    background: "#f7fafc", padding: "4px 8px", textAlign: "left",
                    fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0",
                    whiteSpace: "nowrap", position: "sticky", top: 0,
                  }}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayRows.map((row, i) => (
                <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : "#f7fafc" }}>
                  {cols.map((c) => {
                    const v = row[c];
                    let display: string;
                    if (typeof v === "number") display = Number.isInteger(v) ? String(v) : v.toFixed(4);
                    else if (typeof v === "boolean") display = v ? "true" : "false";
                    else display = String(v ?? "—");
                    if (c === "eventTime" && typeof v === "string") display = v.slice(0, 19);
                    return (
                      <td key={c} style={{ padding: "3px 8px", borderBottom: "1px solid #edf2f7", whiteSpace: "nowrap" }}>
                        {display}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {data.length > displayRows.length && (
            <div style={{ padding: "4px 16px", fontSize: 10, color: "#a0aec0" }}>
              Showing {displayRows.length} of {data.length} rows
            </div>
          )}
        </div>
      )}
    </div>
  );
}
