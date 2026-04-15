"use client";

/**
 * PipelineConsole — 9-stage collapsible cards for pipeline visibility.
 * Replaces flat log list in Console tab.
 */

import { useState } from "react";

export interface PipelineCard {
  stage: number;
  name: string;
  icon: string;
  status: "pending" | "running" | "complete" | "skipped" | "error";
  elapsed?: number;
  summary: string;
  detail?: Record<string, unknown>;
}

interface Props {
  cards: PipelineCard[];
  totalTime?: number;
  llmCalls?: number;
  totalTokens?: number;
  canSaveAsSkill?: boolean;
  saved?: boolean;
  onSaveAsSkill?: () => void;
}

const STATUS_STYLE: Record<string, { dot: string; bg: string }> = {
  pending:  { dot: "#a0aec0", bg: "transparent" },
  running:  { dot: "#d69e2e", bg: "transparent" },
  complete: { dot: "#38a169", bg: "transparent" },
  skipped:  { dot: "#a0aec0", bg: "transparent" },
  error:    { dot: "#e53e3e", bg: "#fff5f5" },
};

const STATUS_ICON: Record<string, string> = {
  pending: "⚪", running: "🔄", complete: "✅", skipped: "⏭️", error: "❌",
};

export function PipelineConsole({ cards, totalTime, llmCalls, totalTokens, canSaveAsSkill, saved, onSaveAsSkill }: Props) {
  if (cards.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>
        等待 pipeline 執行...
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {cards.map((card) => (
        <PipelineCardRow key={card.stage} card={card} />
      ))}

      {/* Bottom stats + Save button */}
      {totalTime != null && (
        <div style={{
          padding: "var(--sp-sm) var(--sp-md)", fontSize: "var(--fs-xs)", color: "#718096",
          borderTop: "1px solid #e2e8f0", background: "#f7f8fc",
          display: "flex", gap: "var(--sp-md)", alignItems: "center",
        }}>
          <span>Total: {totalTime.toFixed(1)}s</span>
          {llmCalls != null && <span>LLM: {llmCalls} calls</span>}
          {totalTokens != null && <span>Tokens: {(totalTokens / 1000).toFixed(1)}k</span>}
          <span style={{ flex: 1 }} />
          {canSaveAsSkill && !saved && (
            <button
              onClick={onSaveAsSkill}
              style={{
                padding: "3px 10px", fontSize: 11, fontWeight: 600,
                borderRadius: 4, border: "1px solid #3182ce",
                background: "#ebf8ff", color: "#2b6cb0", cursor: "pointer",
              }}
            >
              Save as Skill
            </button>
          )}
          {saved && (
            <span style={{ fontSize: 11, color: "#38a169", fontWeight: 600 }}>
              Saved
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function PipelineCardRow({ card }: { card: PipelineCard }) {
  const [expanded, setExpanded] = useState(card.status === "error");
  const style = STATUS_STYLE[card.status] ?? STATUS_STYLE.pending;

  return (
    <div style={{ background: style.bg, borderBottom: "1px solid #f0f0f0" }}>
      {/* Header — always visible */}
      <div
        onClick={() => card.detail && setExpanded(!expanded)}
        style={{
          padding: "var(--sp-sm) var(--sp-md)",
          display: "flex", alignItems: "center", gap: "var(--sp-sm)",
          cursor: card.detail ? "pointer" : "default",
          fontSize: "var(--fs-sm)",
        }}
      >
        {/* Stage dot */}
        <span style={{
          width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
          background: style.dot,
        }} />

        {/* Icon + Name */}
        <span style={{ width: 16, textAlign: "center", flexShrink: 0 }}>{card.icon}</span>
        <span style={{
          fontWeight: 600, color: card.status === "skipped" ? "#a0aec0" : "#2d3748",
          minWidth: 110,
        }}>
          {card.name}
        </span>

        {/* Summary */}
        <span style={{
          flex: 1, color: card.status === "error" ? "#e53e3e" : "#718096",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {card.summary}
        </span>

        {/* Status + Elapsed */}
        <span style={{ fontSize: 10, color: "#a0aec0", flexShrink: 0 }}>
          {STATUS_ICON[card.status]}
          {card.elapsed != null && card.elapsed > 0 ? ` ${card.elapsed}s` : ""}
        </span>

        {/* Expand indicator */}
        {card.detail && (
          <span style={{ fontSize: 9, color: "#a0aec0", flexShrink: 0 }}>
            {expanded ? "▼" : "▶"}
          </span>
        )}
      </div>

      {/* Detail — expanded */}
      {expanded && card.detail && (
        <div style={{
          padding: "4px 12px 8px 38px", fontSize: 11, color: "#4a5568",
          background: "#fafbfc", borderTop: "1px solid #f0f0f0",
        }}>
          {Object.entries(card.detail).map(([k, v]) => {
            if (k === "code" && typeof v === "string") {
              return (
                <div key={k} style={{ marginTop: 4 }}>
                  <div style={{ fontWeight: 600, color: "#718096", marginBottom: 2 }}>Code:</div>
                  <pre style={{
                    background: "#1a202c", color: "#e2e8f0", padding: 8,
                    borderRadius: 4, fontSize: 10, overflow: "auto",
                    maxHeight: 200, whiteSpace: "pre-wrap",
                  }}>
                    {String(v)}
                  </pre>
                </div>
              );
            }
            if (k === "results" && Array.isArray(v) && v.length > 0) {
              return (
                <div key={k} style={{ marginTop: 4 }}>
                  <div style={{ fontWeight: 600, color: "#718096", marginBottom: 2 }}>Results:</div>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
                    <thead>
                      <tr>
                        {Object.keys(v[0]).map(h => (
                          <th key={h} style={{ textAlign: "left", padding: "2px 6px", borderBottom: "1px solid #e2e8f0", color: "#718096" }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(v as Record<string, unknown>[]).slice(0, 10).map((row, i) => (
                        <tr key={i}>
                          {Object.values(row).map((val, j) => (
                            <td key={j} style={{ padding: "2px 6px", borderBottom: "1px solid #f0f0f0" }}>
                              {typeof val === "number" ? (Number.isInteger(val) ? val : val.toFixed(4)) : String(val ?? "—")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            }
            // Default: key = value
            const display = typeof v === "object" ? JSON.stringify(v) : String(v ?? "—");
            return (
              <div key={k} style={{ display: "flex", gap: 8, marginBottom: 2 }}>
                <span style={{ fontWeight: 600, color: "#718096", minWidth: 80 }}>{k}:</span>
                <span style={{ wordBreak: "break-all" }}>{display.slice(0, 200)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
