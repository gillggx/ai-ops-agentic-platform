"use client";

import { useState } from "react";

export interface ExpectedOutput {
  kind?: string | null;
  value_desc?: string | null;
  criterion?: string | null;
  outcome_keys?: string[];
}

export interface GoalPhase {
  id: string;
  goal: string;
  expected: "raw_data" | "transform" | "verdict" | "chart" | "table" | "scalar" | "alarm";
  expected_output?: ExpectedOutput | null;
  why?: string | null;
  user_edited?: boolean;
}

interface Props {
  planSummary: string;
  phases: GoalPhase[];
  /** Called when user clicks Confirm. Sends original phases (no edit in POC). */
  onConfirm: (phases: GoalPhase[]) => void;
  /** Called when user clicks Cancel — backend treats as refused. */
  onCancel: () => void;
  /** When set, hide buttons and show a "(decided)" tag. */
  decided?: "confirmed" | "cancelled";
}

const expectedLabel: Record<GoalPhase["expected"], string> = {
  raw_data: "原始資料",
  transform: "中繼資料",
  verdict: "判定結果",
  chart: "圖表",
  table: "表格",
  scalar: "純數字",
  alarm: "告警觸發",
};

const expectedColor: Record<GoalPhase["expected"], string> = {
  raw_data: "#3b82f6",
  transform: "#94a3b8",
  verdict: "#f97316",
  chart: "#22c55e",
  table: "#a855f7",
  scalar: "#06b6d4",
  alarm: "#dc2626",
};

/**
 * v30 Goal Plan card — shows the LLM-emitted phases. POC: read-only confirm.
 * Edit / delete / add UI deferred to v30 phase B-2.
 */
export default function GoalPlanCard({
  planSummary,
  phases,
  onConfirm,
  onCancel,
  decided,
}: Props) {
  const [acting, setActing] = useState(false);

  const handleConfirm = () => {
    setActing(true);
    onConfirm(phases);
  };
  const handleCancel = () => {
    setActing(true);
    onCancel();
  };

  return (
    <div
      style={{
        background: "#fff",
        border: "1.5px solid #cbd5e1",
        borderRadius: 10,
        padding: "14px 16px",
        margin: "10px 0",
        maxWidth: "100%",
        fontSize: 13,
        lineHeight: 1.55,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: "#475569",
          textTransform: "uppercase",
          letterSpacing: 0.6,
          marginBottom: 6,
        }}
      >
        Build plan ({phases.length} phases)
      </div>
      <div style={{ fontWeight: 600, marginBottom: 12 }}>{planSummary}</div>

      <ol style={{ margin: 0, paddingLeft: 0, listStyle: "none" }}>
        {phases.map((p, i) => (
          <li
            key={p.id}
            style={{
              display: "flex",
              gap: 10,
              padding: "8px 0",
              borderBottom: i < phases.length - 1 ? "1px solid #f1f5f9" : "none",
            }}
          >
            <div
              style={{
                width: 24,
                height: 24,
                flexShrink: 0,
                borderRadius: 4,
                background: "#f1f5f9",
                color: "#475569",
                fontSize: 11,
                fontWeight: 700,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {i + 1}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ color: "#0f172a", marginBottom: 3 }}>{p.goal}</div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    padding: "2px 8px",
                    borderRadius: 3,
                    background: `${expectedColor[p.expected]}20`,
                    color: expectedColor[p.expected],
                    letterSpacing: 0.4,
                  }}
                >
                  {expectedLabel[p.expected]}
                </span>
                {p.why && (
                  <span style={{ fontSize: 11, color: "#64748b" }}>{p.why}</span>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>

      <div
        style={{
          marginTop: 14,
          display: "flex",
          gap: 8,
          alignItems: "center",
          justifyContent: "flex-end",
        }}
      >
        {decided ? (
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: decided === "confirmed" ? "#15803d" : "#991b1b",
              padding: "4px 10px",
              background: decided === "confirmed" ? "#f0fdf4" : "#fef2f2",
              border: `1px solid ${decided === "confirmed" ? "#86efac" : "#fca5a5"}`,
              borderRadius: 4,
            }}
          >
            {decided === "confirmed" ? "已確認，agent 開始建構" : "已取消"}
          </span>
        ) : (
          <>
            <button
              type="button"
              onClick={handleCancel}
              disabled={acting}
              style={{
                background: "transparent",
                color: acting ? "#94a3b8" : "#b91c1c",
                border: `1px solid ${acting ? "#e2e8f0" : "#fca5a5"}`,
                borderRadius: 5,
                padding: "6px 12px",
                fontSize: 12,
                fontWeight: 500,
                cursor: acting ? "not-allowed" : "pointer",
              }}
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={acting}
              style={{
                background: acting ? "#cbd5e1" : "#16a34a",
                color: "#fff",
                border: "none",
                borderRadius: 5,
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: 600,
                cursor: acting ? "not-allowed" : "pointer",
              }}
            >
              確認，開始建構
            </button>
          </>
        )}
      </div>
    </div>
  );
}
