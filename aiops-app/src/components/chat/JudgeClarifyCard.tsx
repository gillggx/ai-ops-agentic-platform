"use client";

/**
 * v30.17j JudgeClarifyCard — pause/ask card when phase_verifier detects
 * a data-source deficit (rows >= 1 but < user's count quantifier).
 *
 * Styled to match PlanRenderer (light theme, #f7f8fc bg, compact 12px)
 * so it sits naturally next to plan / macro plan cards in chat.
 */

import { useState } from "react";

export type JudgeAction = "continue" | "replan" | "cancel";

export interface JudgeClarifyData {
  phase_id: string;
  requested_n: number;
  actual_rows: number;
  ratio: number;       // 0.0 — 1.0
  value_desc: string;
  block_id: string;
  resolved?: JudgeAction;
}

interface Props {
  data: JudgeClarifyData;
  onPick: (action: JudgeAction) => void | Promise<void>;
}

const ACTION_LABEL: Record<JudgeAction, { label: string; color: string }> = {
  continue: { label: "繼續", color: "#38a169" },
  replan:   { label: "重來", color: "#2b6cb0" },
  cancel:   { label: "放棄", color: "#e53e3e" },
};

export function JudgeClarifyCard({ data, onPick }: Props) {
  const [picking, setPicking] = useState<JudgeAction | null>(null);
  const pct = Math.round((data.ratio ?? 0) * 100);

  // Resolved state — compact single-line summary, matches PlanRenderer "done" style
  if (data.resolved) {
    const meta = ACTION_LABEL[data.resolved];
    return (
      <div style={{
        marginBottom: 4, padding: "6px 12px",
        borderRadius: 8, border: "1px solid #e2e8f0",
        background: "#f7f8fc", fontSize: 12,
        color: "#718096",
      }}>
        <span style={{ marginRight: 6 }}>⚠</span>
        資料源不足 {data.phase_id} → <span style={{ color: meta.color, fontWeight: 600 }}>{meta.label}</span>
      </div>
    );
  }

  const handlePick = async (action: JudgeAction) => {
    if (picking) return;
    setPicking(action);
    try {
      await onPick(action);
    } finally {
      setPicking(null);
    }
  };

  return (
    <div style={{
      marginBottom: 4, padding: "8px 12px",
      borderRadius: 8, border: "1px solid #e2e8f0",
      background: "#f7f8fc", fontSize: 12,
    }}>
      {/* Header: matches PlanRenderer */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 6,
      }}>
        <span style={{ fontWeight: 600, color: "#1a202c" }}>
          ⚠ 資料源不足
        </span>
        <span style={{ fontSize: 10, color: "#718096" }}>
          {data.phase_id} · {data.actual_rows}/{data.requested_n} ({pct}%)
        </span>
      </div>

      {/* Compact info — one line */}
      <div style={{
        marginBottom: 8, color: "#4a5568", lineHeight: 1.5,
      }}>
        <span style={{ color: "#a0aec0" }}>{data.block_id}</span>
        <span style={{ marginLeft: 6 }}>
          只回 <span style={{ color: "#e53e3e", fontWeight: 600 }}>{data.actual_rows}</span> 筆
        </span>
        <span style={{ marginLeft: 6, color: "#a0aec0" }}>
          ({data.value_desc.length > 40 ? data.value_desc.slice(0, 40) + "…" : data.value_desc})
        </span>
      </div>

      {/* Buttons row — compact, matches existing chat buttons */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {(Object.keys(ACTION_LABEL) as JudgeAction[]).map((act) => {
          const meta = ACTION_LABEL[act];
          const isPicking = picking === act;
          const isDisabled = picking !== null && !isPicking;
          return (
            <button
              key={act}
              type="button"
              disabled={isDisabled}
              onClick={() => handlePick(act)}
              style={{
                padding: "4px 10px",
                background: isDisabled ? "#edf2f7" : "#fff",
                border: `1px solid ${meta.color}`,
                borderRadius: 4,
                color: isDisabled ? "#a0aec0" : meta.color,
                fontSize: 11,
                fontWeight: 600,
                cursor: isDisabled ? "not-allowed" : "pointer",
              }}
            >
              {isPicking ? "…" : meta.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
