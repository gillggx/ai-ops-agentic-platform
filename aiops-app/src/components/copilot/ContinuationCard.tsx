"use client";

import React from "react";

// SPEC_glassbox_continuation: when the Glass Box agent hits its turn budget
// without calling finish(), the sidecar pauses + emits a `continuation_request`
// SSE event with this shape. Any panel hosting an agent stream can render
// the card; the onPick callback owns the actual fetch / navigation.

export interface ContinuationOption {
  id: "continue" | "takeover" | "stop";
  label: string;
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

export function ContinuationCard({ data, onPick }: Props) {
  const disabled = !!data.resolved;
  return (
    <div style={{
      width: "100%",
      border: "1px solid #f6ad55",
      borderRadius: 8,
      padding: "12px 14px",
      background: "#fffaf0",
      fontSize: 13,
      color: "#2d3748",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 600, marginBottom: 8 }}>
        <span>⏸</span>
        <span>已跑 {data.turns_used} 步、{data.ops_count} 個 ops，估計再 {data.estimate} 步可完成</span>
      </div>

      {data.completed.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <strong style={{ color: "#2f855a" }}>已完成：</strong>
          <ul style={{ margin: "2px 0 0 18px", padding: 0, fontSize: 12, color: "#4a5568" }}>
            {data.completed.map((c, i) => (
              <li key={i}>✓ {c}</li>
            ))}
          </ul>
        </div>
      )}

      {data.remaining.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <strong style={{ color: "#c05621" }}>還剩：</strong>
          <ul style={{ margin: "2px 0 0 18px", padding: 0, fontSize: 12, color: "#4a5568" }}>
            {data.remaining.map((r, i) => (
              <li key={i}>○ {r}</li>
            ))}
          </ul>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {data.options.map((opt) => {
          const isPrimary = opt.id === "continue";
          return (
            <button
              key={opt.id}
              disabled={disabled}
              onClick={() => onPick(opt)}
              style={{
                textAlign: "left",
                padding: "8px 10px",
                border: isPrimary ? "1px solid #ed8936" : "1px solid #e2e8f0",
                borderRadius: 6,
                background: disabled ? "#edf2f7" : isPrimary ? "#feebc8" : "#ffffff",
                cursor: disabled ? "default" : "pointer",
                opacity: disabled ? 0.6 : 1,
                fontSize: 13,
                color: "#2d3748",
                fontWeight: isPrimary ? 600 : 400,
              }}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {disabled && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#a0aec0" }}>已選擇</div>
      )}
    </div>
  );
}
