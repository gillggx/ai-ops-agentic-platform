"use client";

/**
 * PipelineResultsPanel — styled after auto-patrol's SkillOutputRenderer.
 *
 * Layout (top → bottom):
 *   1. Alert banner  — green/red/grey based on triggered
 *   2. Evidence table (only when triggered)
 *   3. Chart list   — ordered by `sequence`, each rendered via ChartDSLRenderer
 *                     when the spec is ChartDSL (SPC mode), otherwise Vega-Lite
 */

import { useState } from "react";
import type { PipelineResultSummary, NodeResult, PipelineChartSummary } from "@/lib/pipeline-builder/types";
import ChartRenderer from "./ChartRenderer";
import DataResultView from "@/components/common/DataResultView";

type ChartView = "stacked" | "grid" | "tabs";

interface Props {
  open: boolean;
  onClose: () => void;
  summary: PipelineResultSummary | null;
  /** Full node_results so we can render evidence table for the terminal logic node. */
  nodeResults: Record<string, NodeResult>;
  /** When provided, data tables get a 下載 CSV button (full data re-fetched server-side). */
  pipelineJson?: unknown;
}

export default function PipelineResultsPanel({ open, onClose, summary, nodeResults, pipelineJson }: Props) {
  const chartCount = summary?.charts.length ?? 0;
  // PR-F: view toggle — user override persists across runs of the panel
  const [userChartView, setUserChartView] = useState<ChartView | null>(null);
  const [activeTabIdx, setActiveTabIdx] = useState(0);

  if (!open || !summary) return null;

  const evidence = summary.evidence_node_id
    ? nodeResults[summary.evidence_node_id]?.preview?.evidence
    : undefined;
  const evidenceRows = (evidence as { rows?: Array<Record<string, unknown>> } | undefined)?.rows ?? [];

  // Default: 1 chart = stacked; ≥2 = grid. User can override.
  const effectiveView: ChartView = userChartView ?? (chartCount <= 1 ? "stacked" : "grid");
  const isWide = effectiveView === "grid" && chartCount >= 2;

  return (
    <div
      data-testid="pipeline-results-panel"
      style={{
        position: "fixed",
        right: 24,
        top: 80,
        // Wider so Vega-Lite right-side legends + Plotly scatter legends don't clip.
        // Caps at 95vw so we never push off screen on narrower monitors.
        width: isWide ? "min(1400px, 95vw)" : "min(960px, 95vw)",
        transition: "width 180ms ease",
        maxHeight: "calc(100vh - 120px)",
        background: "#fff",
        border: "1px solid #E2E8F0",
        borderRadius: 8,
        boxShadow: "0 12px 24px rgba(15,23,42,0.12)",
        zIndex: 150,
        display: "flex",
        flexDirection: "column",
        fontFamily: "Inter, system-ui, -apple-system, 'Noto Sans TC', sans-serif",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "10px 14px",
          borderBottom: "1px solid #E2E8F0",
          background: "#F8FAFC",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <span style={{ fontSize: 16 }}>📊</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#0F172A", flex: 1 }}>
          Pipeline Results
        </span>
        <button
          onClick={onClose}
          data-testid="pipeline-results-close"
          style={{ background: "none", border: "none", fontSize: 18, cursor: "pointer", color: "#94A3B8" }}
        >
          ×
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 14 }}>
        <AlertBanner summary={summary} />

        {/* Evidence table (only when triggered + has rows) */}
        {summary.triggered && evidenceRows.length > 0 && (
          <div data-testid="result-evidence-table" style={{ marginTop: 12 }}>
            <div style={sectionHeader}>佐證事件 ({evidenceRows.length} rows)</div>
            <div style={{ height: 280, display: "flex", flexDirection: "column" }}>
              <DataResultView
                result={evidenceRows}
                enableFullscreen={false}
                exportSpec={pipelineJson && summary.evidence_node_id
                  ? { pipelineJson, nodeId: summary.evidence_node_id } : null}
              />
            </div>
          </div>
        )}

        {/* PR-E1: Data views (block_data_view outputs) — ordered by sequence */}
        {(summary.data_views ?? []).length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={sectionHeader}>資料視圖 ({(summary.data_views ?? []).length})</div>
            {(summary.data_views ?? []).map((v, i) => (
              <div
                key={v.node_id}
                data-testid={`result-data-view-${v.node_id}`}
                style={{
                  border: "1px solid #E2E8F0",
                  borderRadius: 6,
                  marginBottom: 10,
                  background: "#fff",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    padding: "6px 12px",
                    fontSize: 12,
                    fontWeight: 600,
                    color: "#4A5568",
                    borderBottom: "1px solid #E2E8F0",
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    background: "#F8FAFC",
                  }}
                >
                  <span
                    style={{
                      background: "#EFF6FF",
                      color: "#1E40AF",
                      padding: "1px 7px",
                      borderRadius: 10,
                      fontSize: 10,
                      fontWeight: 700,
                    }}
                  >
                    View #{v.sequence ?? i + 1}
                  </span>
                  <span style={{ flex: 1 }}>{v.title}</span>
                  <span style={{ fontSize: 10, color: "#94A3B8", fontFamily: "ui-monospace,monospace" }}>
                    {v.rows.length} / {v.total_rows} rows
                  </span>
                </div>
                {v.description && (
                  <div style={{ padding: "6px 12px", fontSize: 11, color: "#64748B", borderBottom: "1px solid #F1F5F9" }}>
                    {v.description}
                  </div>
                )}
                <div style={{ height: 300, display: "flex", flexDirection: "column", padding: 10 }}>
                  <DataResultView
                    result={v.rows}
                    enableFullscreen={false}
                    emptyText="無資料"
                    totalRows={v.total_rows}
                    exportSpec={pipelineJson ? { pipelineJson, nodeId: v.node_id } : null}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Chart list — view toggle (stacked / grid / tabs) */}
        {summary.charts.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div style={{ ...sectionHeader, marginBottom: 0, flex: 1 }}>
                Charts ({summary.charts.length})
              </div>
              {summary.charts.length >= 2 && (
                <ViewToggle mode={effectiveView} onChange={(v) => { setUserChartView(v); setActiveTabIdx(0); }} />
              )}
            </div>

            {effectiveView === "stacked" && (
              <div>
                {summary.charts.map((c, i) => (
                  <ChartCard key={c.node_id} chart={c} indexFallback={i} />
                ))}
              </div>
            )}

            {effectiveView === "grid" && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(460px, 1fr))",
                  gap: 12,
                }}
              >
                {summary.charts.map((c, i) => (
                  <ChartCard key={c.node_id} chart={c} indexFallback={i} />
                ))}
              </div>
            )}

            {effectiveView === "tabs" && (
              <div>
                <div
                  style={{
                    display: "flex",
                    gap: 4,
                    marginBottom: 8,
                    borderBottom: "1px solid #E2E8F0",
                    flexWrap: "wrap",
                  }}
                >
                  {summary.charts.map((c, i) => {
                    const active = i === activeTabIdx;
                    return (
                      <button
                        key={c.node_id}
                        onClick={() => setActiveTabIdx(i)}
                        style={{
                          padding: "5px 10px",
                          fontSize: 11,
                          fontWeight: 600,
                          background: "transparent",
                          color: active ? "#4F46E5" : "#64748B",
                          border: "none",
                          borderBottom: `2px solid ${active ? "#4F46E5" : "transparent"}`,
                          cursor: "pointer",
                          letterSpacing: "0.02em",
                          marginBottom: -1,
                          maxWidth: 220,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={c.title ?? c.node_id}
                      >
                        #{c.sequence ?? i + 1} {c.title ?? c.node_id}
                      </button>
                    );
                  })}
                </div>
                {summary.charts[activeTabIdx] && (
                  <ChartCard
                    chart={summary.charts[activeTabIdx]}
                    indexFallback={activeTabIdx}
                  />
                )}
              </div>
            )}
          </div>
        )}

        {!summary.triggered
          && summary.charts.length === 0
          && (summary.data_views ?? []).length === 0 && (
          <div
            style={{
              marginTop: 14,
              padding: "24px 14px",
              textAlign: "center",
              fontSize: 11,
              color: "#94A3B8",
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              fontWeight: 600,
              background: "#F7F8FC",
              borderRadius: 6,
            }}
          >
            No outputs — add a data_view / chart / alert node
          </div>
        )}
      </div>
    </div>
  );
}

function AlertBanner({ summary }: { summary: PipelineResultSummary }) {
  const triggered = summary.triggered;
  const hasLogic = Boolean(summary.evidence_node_id);
  const bg = triggered ? "#FED7D7" : hasLogic ? "#C6F6D5" : "#EDF2F7";
  const fg = triggered ? "#9B2C2C" : hasLogic ? "#276749" : "#4A5568";
  const icon = triggered ? "🚨" : hasLogic ? "✓" : "ℹ";
  const title = triggered ? "ALERT TRIGGERED" : hasLogic ? "NOT TRIGGERED" : "No Logic Node";
  const subtitle = hasLogic
    ? `${summary.evidence_rows} evidence row(s) from ${summary.evidence_node_id}`
    : "Pipeline contains no logic node (threshold / consecutive / weco)";

  return (
    <div
      data-testid="result-alert-card"
      style={{
        padding: "12px 14px",
        borderRadius: 8,
        background: bg,
        color: fg,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <span style={{ fontSize: 24 }}>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 700, fontSize: 13, letterSpacing: "0.04em", textTransform: "uppercase" }}>
          {title}
        </div>
        <div style={{ fontSize: 12, marginTop: 2, opacity: 0.9 }}>{subtitle}</div>
      </div>
    </div>
  );
}

const sectionHeader: React.CSSProperties = {
  fontSize: 10,
  color: "#718096",
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  marginBottom: 6,
};

// ── PR-F: Chart view toggle + reusable card ────────────────────────────────

function ViewToggle({
  mode,
  onChange,
}: {
  mode: ChartView;
  onChange: (m: ChartView) => void;
}) {
  const options: Array<{ key: ChartView; label: string; title: string }> = [
    { key: "stacked", label: "☰ Stacked", title: "一張一張垂直堆疊" },
    { key: "grid",    label: "▦ Grid",    title: "2-col 格狀並排" },
    { key: "tabs",    label: "⧉ Tabs",    title: "切頁，一張一張看" },
  ];
  return (
    <div
      style={{
        display: "inline-flex",
        gap: 2,
        padding: 2,
        background: "#F1F5F9",
        border: "1px solid #E2E8F0",
        borderRadius: 5,
      }}
    >
      {options.map((opt) => {
        const active = mode === opt.key;
        return (
          <button
            key={opt.key}
            onClick={() => onChange(opt.key)}
            title={opt.title}
            data-testid={`chart-view-${opt.key}`}
            style={{
              padding: "3px 10px",
              fontSize: 10,
              fontWeight: 600,
              color: active ? "#1E293B" : "#64748B",
              background: active ? "#fff" : "transparent",
              border: "none",
              borderRadius: 3,
              cursor: "pointer",
              letterSpacing: "0.03em",
              boxShadow: active ? "0 1px 2px rgba(15,23,42,0.08)" : "none",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function ChartCard({
  chart,
  indexFallback,
}: {
  chart: PipelineChartSummary;
  indexFallback: number;
}) {
  return (
    <div
      data-testid={`result-chart-${chart.node_id}`}
      style={{
        border: "1px solid #E2E8F0",
        borderRadius: 6,
        marginBottom: 10,
        background: "#fff",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "6px 12px",
          fontSize: 12,
          fontWeight: 600,
          color: "#4A5568",
          borderBottom: "1px solid #E2E8F0",
          display: "flex",
          gap: 8,
          alignItems: "center",
          background: "#F8FAFC",
        }}
      >
        <span
          data-testid={`result-chart-seq-${chart.node_id}`}
          style={{
            background: "#EEF2FF",
            color: "#3730A3",
            padding: "1px 7px",
            borderRadius: 10,
            fontSize: 10,
            fontWeight: 700,
          }}
        >
          #{chart.sequence ?? indexFallback + 1}
        </span>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {chart.title ?? chart.node_id}
        </span>
      </div>
      <div style={{ padding: 0 }}>
        <ChartRenderer spec={chart.chart_spec} />
      </div>
    </div>
  );
}
