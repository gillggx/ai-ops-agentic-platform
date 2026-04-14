"use client";

/**
 * ChartExplorer — interactive chart explorer for Generative UI.
 *
 * Receives flat data from backend (via SSE) and renders interactive Plotly charts.
 * User can switch between datasets (SPC/APC/DC/...) and change filters
 * without any API calls — all data is cached in FlatDataContext.
 */

import { useState, useMemo } from "react";
import dynamic from "next/dynamic";
import type { FlatDataMetadata, UIConfig } from "@/context/FlatDataContext";

// Lazy-load Plotly
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Plot = dynamic(async () => {
  const Plotly = await import("plotly.js-dist-min");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const factory = (await import("react-plotly.js/factory")).default as (p: any) => React.ComponentType<any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return { default: factory((Plotly as any).default ?? Plotly) };
}, { ssr: false, loading: () => <div style={{ padding: 16, textAlign: "center", color: "#a0aec0" }}>Loading chart...</div> });

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

  // Single trace (one group at a time)
  const traces = useMemo(() => {
    const xs = displayData.map((r) => r[config.x]);
    const ys = displayData.map((r) => r[config.y]);
    // SPC = green line, others = blue
    const lineColor = activeDataset === "spc_data" ? "#48bb78" : "#4299e1";
    return [{
      x: xs, y: ys,
      name: effectiveFilterValue || config.y,
      type: "scatter" as const,
      mode: "lines+markers" as const,
      line: { color: lineColor, width: 2 },
      marker: { size: 4, color: lineColor },
    }];
  }, [displayData, config, effectiveFilterValue, activeDataset]);

  // SPC control lines — UCL/LCL orange, CL gray dotted
  const shapes = useMemo(() => {
    if (activeDataset !== "spc_data" || !displayData.length) return [];
    const ucl = displayData[0]?.ucl;
    const lcl = displayData[0]?.lcl;
    const vals = displayData.map((r) => r.value).filter((v: unknown) => typeof v === "number") as number[];
    const cl = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const s: any[] = [];
    if (ucl != null) s.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: ucl, y1: ucl, line: { color: "#ed8936", width: 1.5, dash: "dash" } });
    if (lcl != null) s.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: lcl, y1: lcl, line: { color: "#ed8936", width: 1.5, dash: "dash" } });
    if (cl) s.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: cl, y1: cl, line: { color: "#718096", width: 1, dash: "dot" } });
    return s;
  }, [activeDataset, displayData]);

  // OOC highlights for SPC — red circles
  const oocTrace = useMemo(() => {
    if (activeDataset !== "spc_data") return null;
    const oocPoints = displayData.filter((r) => r.is_ooc);
    if (!oocPoints.length) return null;
    return {
      x: oocPoints.map((r) => r[config.x]),
      y: oocPoints.map((r) => r[config.y]),
      type: "scatter" as const,
      mode: "markers" as const,
      name: "OOC",
      marker: { color: "#e53e3e", size: 10, symbol: "circle-open", line: { width: 2, color: "#e53e3e" } },
    };
  }, [activeDataset, displayData, config]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const allTraces: any[] = [...traces, ...(oocTrace ? [oocTrace] : [])];

  return (
    <div style={{ background: "#fff", borderRadius: 8, border: "1px solid #e2e8f0", overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 16px", borderBottom: "1px solid #e2e8f0", background: "#f7f8fc",
      }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: "#1a202c" }}>
          Data Explorer
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "#718096" }}>
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
        {/* Overlay tab — only if >= 2 datasets */}
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
              {/* No "All" — one at a time */}
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
              {/* No "All" — one at a time */}
              {[...new Set((flatData[overlayRight.dataset] ?? []).map((r: Record<string,unknown>) => String(r[CHART_CONFIGS[overlayRight.dataset]?.group ?? ""] ?? "")))].filter(Boolean).sort().map(v =>
                <option key={v} value={v}>{v}</option>
              )}
            </select>
          </div>
          {(() => {
            const leftCfg = CHART_CONFIGS[overlayLeft.dataset] ?? { x: "eventTime", y: "value" };
            const rightCfg = CHART_CONFIGS[overlayRight.dataset] ?? { x: "eventTime", y: "value" };
            let leftData = flatData[overlayLeft.dataset] ?? [];
            let rightData = flatData[overlayRight.dataset] ?? [];

            // Get effective filter values (default to first available group value)
            const leftGroupField = leftCfg.group ?? (CHART_CONFIGS[overlayLeft.dataset]?.group ?? "");
            const rightGroupField = rightCfg.group ?? (CHART_CONFIGS[overlayRight.dataset]?.group ?? "");
            const leftGroupVals = leftGroupField ? [...new Set(leftData.map((r: Record<string,unknown>) => String(r[leftGroupField] ?? "")))].filter(Boolean).sort() : [];
            const rightGroupVals = rightGroupField ? [...new Set(rightData.map((r: Record<string,unknown>) => String(r[rightGroupField] ?? "")))].filter(Boolean).sort() : [];
            const effectiveLeftFilter = overlayLeft.filterVal || leftGroupVals[0] || "";
            const effectiveRightFilter = overlayRight.filterVal || rightGroupVals[0] || "";

            // Always filter to one group
            if (leftGroupField && effectiveLeftFilter)
              leftData = leftData.filter((r: Record<string,unknown>) => String(r[leftGroupField]) === effectiveLeftFilter);
            if (rightGroupField && effectiveRightFilter)
              rightData = rightData.filter((r: Record<string,unknown>) => String(r[rightGroupField]) === effectiveRightFilter);

            const leftLabel = effectiveLeftFilter || DATASET_LABELS[overlayLeft.dataset] || overlayLeft.dataset;
            const rightLabel = effectiveRightFilter || DATASET_LABELS[overlayRight.dataset] || overlayRight.dataset;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const overlayTraces: any[] = [
              { x: leftData.map((r: Record<string,unknown>) => r[leftCfg.x]), y: leftData.map((r: Record<string,unknown>) => r[leftCfg.y]),
                name: leftLabel, type: "scatter", mode: "lines+markers",
                line: { color: "#4299e1", width: 1.5 }, marker: { size: 4 }, yaxis: "y" },
              { x: rightData.map((r: Record<string,unknown>) => r[rightCfg.x]), y: rightData.map((r: Record<string,unknown>) => r[rightCfg.y]),
                name: rightLabel, type: "scatter", mode: "lines+markers",
                line: { color: "#ed8936", width: 1.5 }, marker: { size: 4 }, yaxis: "y2" },
            ];
            return (
              <Plot
                data={overlayTraces}
                layout={{
                  autosize: true, height: 350,
                  margin: { l: 60, r: 60, t: 30, b: 50 },
                  paper_bgcolor: "transparent", plot_bgcolor: "#fafbfc",
                  font: { family: "Inter, sans-serif", size: 11 },
                  showlegend: true, legend: { orientation: "h" as const, y: -0.2 },
                  xaxis: { title: "eventTime", gridcolor: "#e2e8f0" },
                  yaxis: { title: leftLabel, titlefont: { color: "#4299e1" }, tickfont: { color: "#4299e1" }, gridcolor: "#e2e8f0" },
                  yaxis2: { title: rightLabel, titlefont: { color: "#ed8936" }, tickfont: { color: "#ed8936" }, overlaying: "y" as const, side: "right" as const },
                }}
                config={{ responsive: true, displayModeBar: false }}
                style={{ width: "100%" }}
                useResizeHandler
              />
            );
          })()}
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
          {/* Add chart button */}
          <button
            onClick={() => {
              // Add next available group value that's not already shown
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

      {/* Chart (single dataset mode) */}
      {!overlayMode && displayData.length > 0 ? (
        <Plot
          data={allTraces}
          layout={{
            autosize: true,
            height: 320,
            margin: { l: 50, r: 20, t: 30, b: 50 },
            paper_bgcolor: "transparent",
            plot_bgcolor: "#fafbfc",
            font: { family: "Inter, sans-serif", size: 11 },
            showlegend: allTraces.length > 1 && allTraces.length <= 8,
            legend: { orientation: "h" as const, y: -0.2 },
            xaxis: { title: config.x, gridcolor: "#e2e8f0" },
            yaxis: { title: config.y, gridcolor: "#e2e8f0" },
            shapes,
            annotations: activeDataset === "spc_data" && displayData.length > 0 ? [
              ...(displayData[0]?.ucl != null ? [{ xref: "paper" as const, yref: "y" as const, x: 1, y: displayData[0].ucl, text: `UCL ${displayData[0].ucl}`, font: { size: 9, color: "#ed8936" }, showarrow: false, xanchor: "right" as const }] : []),
              ...(displayData[0]?.lcl != null ? [{ xref: "paper" as const, yref: "y" as const, x: 1, y: displayData[0].lcl, text: `LCL ${displayData[0].lcl}`, font: { size: 9, color: "#ed8936" }, showarrow: false, xanchor: "right" as const }] : []),
            ] : [],
          }}
          config={{ responsive: true, displayModeBar: false }}
          style={{ width: "100%" }}
          useResizeHandler
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
        const lineColor = activeDataset === "spc_data" ? "#48bb78" : "#4299e1";
        const ecXs = ecData.map((r) => r[config.x]);
        const ecYs = ecData.map((r) => r[config.y]);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const ecTraces: any[] = [{
          x: ecXs, y: ecYs, name: ecFilter,
          type: "scatter", mode: "lines+markers",
          line: { color: lineColor, width: 2 }, marker: { size: 4, color: lineColor },
        }];
        // OOC for SPC
        if (activeDataset === "spc_data") {
          const ooc = ecData.filter((r) => r.is_ooc);
          if (ooc.length) ecTraces.push({
            x: ooc.map((r) => r[config.x]), y: ooc.map((r) => r[config.y]),
            type: "scatter", mode: "markers", name: "OOC",
            marker: { color: "#e53e3e", size: 10, symbol: "circle-open", line: { width: 2, color: "#e53e3e" } },
          });
        }
        // SPC control lines
        const ucl = ecData[0]?.ucl;
        const lcl = ecData[0]?.lcl;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const ecShapes: any[] = [];
        if (activeDataset === "spc_data") {
          if (ucl != null) ecShapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: ucl, y1: ucl, line: { color: "#ed8936", width: 1.5, dash: "dash" } });
          if (lcl != null) ecShapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: lcl, y1: lcl, line: { color: "#ed8936", width: 1.5, dash: "dash" } });
        }
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
            <Plot
              data={ecTraces}
              layout={{
                autosize: true, height: 220,
                margin: { l: 50, r: 20, t: 8, b: 40 },
                paper_bgcolor: "transparent", plot_bgcolor: "#fafbfc",
                font: { family: "Inter, sans-serif", size: 10 },
                showlegend: false,
                xaxis: { gridcolor: "#e2e8f0" },
                yaxis: { gridcolor: "#e2e8f0" },
                shapes: ecShapes,
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: "100%" }}
              useResizeHandler
            />
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
                    // Truncate eventTime for readability
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
