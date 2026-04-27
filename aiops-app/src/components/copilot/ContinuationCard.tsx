"use client";

import React from "react";

// SPEC_glassbox_continuation: when the Glass Box agent hits its turn budget
// without calling finish(), the sidecar pauses + emits a `continuation_request`
// SSE event with this shape. Any panel hosting an agent stream can render
// the card; the onPick callback owns the actual fetch / navigation.

export interface ContinuationOption {
  // 2026-04-27: dropped "stop" — at 60+ ops nobody picks "use partial",
  // so the card stays focused on the two productive paths.
  id: "continue" | "takeover";
  label: string;
  preview?: string;
  additional_turns?: number;
}

export interface ContinuationData {
  session_id: string;
  turns_used: number;
  ops_count: number;
  completed: string[];
  remaining: string[];
  estimate: number;
  options: ContinuationOption[];
  resolved?: boolean;  // flips to true once user picks; hides the buttons
}

interface Props {
  data: ContinuationData;
  onPick: (option: ContinuationOption) => void;
}

// Style mirrors ClarifyCard: light grey card, Q at top, list of buttons each
// with bold label + grey preview. Two short summary lines (done / remaining)
// kept compact so the buttons stay above the fold.
export function ContinuationCard({ data, onPick }: Props) {
  const disabled = !!data.resolved;
  return (
    <div style={{
      width: "100%",
      border: "1px solid #cbd5e0",
      borderRadius: 8,
      padding: "12px 14px",
      background: "#f7fafc",
      fontSize: 13,
      color: "#2d3748",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 600, marginBottom: 8 }}>
        <span>⏸</span>
        <span>已跑 {data.turns_used} 步、{data.ops_count} 個 ops，估計再 {data.estimate} 步可完成</span>
      </div>

      {(data.completed.length > 0 || data.remaining.length > 0) && (
        <div style={{ marginBottom: 10, fontSize: 12, color: "#4a5568" }}>
          {data.completed.length > 0 && (
            <div style={{ marginBottom: 4 }}>
              <span style={{ color: "#2f855a", fontWeight: 600 }}>已完成：</span>
              <span>{data.completed.join("、")}</span>
            </div>
          )}
          {data.remaining.length > 0 && (
            <div>
              <span style={{ color: "#c05621", fontWeight: 600 }}>還剩：</span>
              <span>{data.remaining.join("、")}</span>
            </div>
          )}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {data.options.map((opt) => (
          <button
            key={opt.id}
            disabled={disabled}
            onClick={() => onPick(opt)}
            style={{
              textAlign: "left",
              padding: "8px 10px",
              border: "1px solid #e2e8f0",
              borderRadius: 6,
              background: disabled ? "#edf2f7" : "#ffffff",
              cursor: disabled ? "default" : "pointer",
              opacity: disabled ? 0.6 : 1,
              fontSize: 13,
              color: "#2d3748",
            }}
          >
            <span style={{ fontWeight: 600 }}>{opt.label}</span>
            {opt.preview && (
              <span style={{ marginLeft: 8, color: "#718096", fontSize: 12 }}>
                {opt.preview}
              </span>
            )}
          </button>
        ))}
      </div>

      {disabled && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#a0aec0" }}>已選擇</div>
      )}
    </div>
  );
}
