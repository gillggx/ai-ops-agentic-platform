"use client";

/**
 * DataExplorerPanel — renders in center main area (same position as AnalysisPanel).
 * Shows: Query Summary (top) + ChartExplorer (bottom).
 */

import { ChartExplorer } from "@/components/copilot/ChartExplorer";
import type { DataExplorerState } from "@/context/AppContext";

interface Props {
  state: DataExplorerState;
  onClose: () => void;
}

export function DataExplorerPanel({ state, onClose }: Props) {
  const { flatData, metadata, uiConfig, queryInfo } = state;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#f7f8fc" }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 20px", background: "#fff", borderBottom: "1px solid #e2e8f0",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "#1a202c" }}>Data Explorer</span>
          <span style={{
            fontSize: 11, padding: "2px 8px", borderRadius: 10,
            background: "#ebf4ff", color: "#2b6cb0", fontWeight: 600,
          }}>
            Interactive
          </span>
        </div>
        <button onClick={onClose} style={{
          padding: "4px 12px", fontSize: 12, borderRadius: 4,
          border: "1px solid #cbd5e0", background: "#fff", cursor: "pointer", color: "#4a5568",
        }}>
          X 結束探索
        </button>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {/* Query Summary */}
        {queryInfo && (
          <div style={{
            background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8,
            padding: "14px 20px", marginBottom: 16,
          }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#718096", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.5px" }}>
              Query Summary
            </div>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13, color: "#2d3748" }}>
              <div>
                <span style={{ color: "#718096" }}>MCP: </span>
                <span style={{ fontWeight: 600, fontFamily: "monospace" }}>{queryInfo.mcp}</span>
              </div>
              {Object.entries(queryInfo.params).map(([k, v]) => (
                <div key={k}>
                  <span style={{ color: "#718096" }}>{k}: </span>
                  <span style={{ fontWeight: 600 }}>{String(v)}</span>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 8, fontSize: 12, color: "#4a5568" }}>
              {queryInfo.resultSummary}
            </div>
          </div>
        )}

        {/* Stats Bar */}
        {metadata && (
          <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
            <StatCard label="Total Events" value={String(metadata.total_events ?? 0)} />
            <StatCard label="OOC Count" value={String(metadata.ooc_count ?? 0)} color="#e53e3e" />
            <StatCard label="OOC Rate" value={`${metadata.ooc_rate ?? 0}%`} color="#dd6b20" />
            <StatCard label="Datasets" value={String(metadata.available_datasets?.length ?? 0)} color="#2b6cb0" />
          </div>
        )}

        {/* ChartExplorer */}
        {flatData && metadata && (
          <ChartExplorer
            flatData={flatData}
            metadata={metadata}
            uiConfig={uiConfig}
          />
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      flex: 1, background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8,
      padding: "10px 16px",
    }}>
      <div style={{ fontSize: 10, color: "#718096", textTransform: "uppercase", letterSpacing: "0.5px" }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color: color ?? "#1a202c", marginTop: 2 }}>
        {value}
      </div>
    </div>
  );
}
