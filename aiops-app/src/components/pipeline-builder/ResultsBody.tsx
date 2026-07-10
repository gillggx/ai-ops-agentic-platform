"use client";

/**
 * ResultsBody — layout-agnostic results renderer.
 *
 * Same content as PipelineResultsPanel (alert banner + evidence + data
 * views + charts) but **without** the floating wrapper. Use directly in
 * an inline container (e.g. v1.5 PipelineWorkspace), or wrap with the
 * floating shell (PipelineResultsPanel) for the manual Run Full path.
 */

import { useState } from "react";
import type { PipelineResultSummary, NodeResult, PipelineChartSummary } from "@/lib/pipeline-builder/types";
import ChartRenderer from "./ChartRenderer";
import DataResultView from "@/components/common/DataResultView";

type ChartView = "stacked" | "grid" | "tabs";

interface Props {
  summary: PipelineResultSummary;
  nodeResults: Record<string, NodeResult>;
  /** When provided, data-view tables get a 下載 CSV button (full data is
   *  re-fetched server-side; tables only ship ~100 rows). */
  pipelineJson?: unknown;
}

export default function ResultsBody({ summary, nodeResults, pipelineJson }: Props) {
  const chartCount = (summary.charts ?? []).length;
  // v30.17j defensive: in chat-mode build (Lite Canvas), summary may
  // arrive from pb_run_done without a charts field — guard all reads.
  const [userChartView, setUserChartView] = useState<ChartView | null>(null);
  const [activeTabIdx, setActiveTabIdx] = useState(0);

  const evidence = summary.evidence_node_id
    ? nodeResults[summary.evidence_node_id]?.preview?.evidence
    : undefined;
  const evidenceRows = (evidence as { rows?: Array<Record<string, unknown>> } | undefined)?.rows ?? [];

  const effectiveView: ChartView = userChartView ?? (chartCount <= 1 ? "stacked" : "grid");

  return (
    <div data-testid="results-body">
      <AlertBanner summary={summary} />

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
                  background: "var(--pn, #F8FAFC)",
                }}
              >
                <span
                  style={{
                    background: "var(--pl, #EFF6FF)",
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

      {(summary.charts ?? []).length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div style={{ ...sectionHeader, marginBottom: 0, flex: 1 }}>
              Charts ({(summary.charts ?? []).length})
            </div>
            {(summary.charts ?? []).length >= 2 && (
              <ViewToggle
                mode={effectiveView}
                onChange={(v) => { setUserChartView(v); setActiveTabIdx(0); }}
              />
            )}
          </div>

          {effectiveView === "stacked" && (
            <div>
              {(summary.charts ?? []).map((c, i) => (
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
              {(summary.charts ?? []).map((c, i) => (
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
                {(summary.charts ?? []).map((c, i) => {
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
                        color: active ? "var(--p, #4F46E5)" : "#64748B",
                        border: "none",
                        borderBottom: `2px solid ${active ? "var(--p, #4F46E5)" : "transparent"}`,
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
              {(summary.charts ?? [])[activeTabIdx] && (
                <ChartCard
                  chart={(summary.charts ?? [])[activeTabIdx]}
                  indexFallback={activeTabIdx}
                />
              )}
            </div>
          )}
        </div>
      )}

      {!summary.triggered
        && (summary.charts ?? []).length === 0
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
            background: "var(--pn, #F7F8FC)",
            borderRadius: 6,
          }}
        >
          No outputs — add a data_view / chart / alert node
        </div>
      )}
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
          background: "var(--pn, #F8FAFC)",
        }}
      >
        <span
          data-testid={`result-chart-seq-${chart.node_id}`}
          style={{
            background: "var(--pl, #EEF2FF)",
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
