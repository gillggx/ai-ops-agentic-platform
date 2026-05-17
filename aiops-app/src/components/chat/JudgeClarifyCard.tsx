"use client";

/**
 * v30.17j JudgeClarifyCard — pause/ask card when phase_verifier detects
 * a data-source deficit (rows >= 1 but significantly below user's count
 * quantifier in value_desc).
 *
 * Example: user asks "最近 100 筆 xbar 趨勢", simulator returns 7 rows
 * (data ceiling). Without this card the build either rejects (waste 16
 * rounds of LLM retry) or silently passes (user surprised). The card
 * gives 3 explicit choices.
 *
 * On click → caller posts /chat/intent-respond with judge_decision body
 * → sidecar resumes the graph.
 */

import { useState, type CSSProperties } from "react";

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

const ACTION_LABEL: Record<JudgeAction, { label: string; hint: string; color: string }> = {
  continue: {
    label: "用現有資料繼續",
    hint: "讓 build 走完看結果",
    color: "#38a169",
  },
  replan: {
    label: "重新規劃放寬條件",
    hint: "改成「可取得的最大量」",
    color: "#3182ce",
  },
  cancel: {
    label: "取消",
    hint: "停止本次 build",
    color: "#e53e3e",
  },
};

export function JudgeClarifyCard({ data, onPick }: Props) {
  const [picking, setPicking] = useState<JudgeAction | null>(null);

  const pct = Math.round((data.ratio ?? 0) * 100);
  const containerStyle: CSSProperties = {
    width: "100%",
    background: "#0d1117",
    border: "1px solid #f6ad55",
    borderRadius: 8,
    padding: 14,
    fontSize: 12,
    color: "#e2e8f0",
  };

  if (data.resolved) {
    const meta = ACTION_LABEL[data.resolved];
    return (
      <div style={{
        ...containerStyle,
        border: "1px solid #2d3748",
        color: "#718096",
        fontStyle: "italic",
      }}>
        判決：{meta.label} ({data.phase_id})
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
    <div style={containerStyle}>
      <div style={{
        fontSize: 11, color: "#f6ad55", fontWeight: 600, marginBottom: 8,
      }}>
        ⚠ 資料源不足 — 需要你的判斷 ({data.phase_id})
      </div>
      <div style={{ marginBottom: 10, lineHeight: 1.6 }}>
        要求：<span style={{ color: "#fbb98a" }}>{data.value_desc}</span><br />
        實際取得：<span style={{ color: "#fc8181", fontWeight: 600 }}>
          {data.actual_rows} 筆
        </span>{" "}
        ／ 預期 {data.requested_n} 筆 ({pct}%)
      </div>
      <div style={{
        fontSize: 11, color: "#a0aec0", marginBottom: 10,
        padding: "6px 8px", background: "rgba(255,255,255,0.03)",
        borderRadius: 4,
      }}>
        資料源 (block <code style={{ color: "#fbb98a" }}>{data.block_id}</code>) 已盡力取，
        是它的上限。pipeline 無法生出更多資料。
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
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
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 12px",
                background: isDisabled ? "#1a202c" : "#1a365d",
                border: `1px solid ${meta.color}`,
                borderRadius: 4,
                color: isDisabled ? "#4a5568" : "#e2e8f0",
                fontSize: 12,
                cursor: isDisabled ? "not-allowed" : "pointer",
                textAlign: "left",
              }}
            >
              <span style={{
                color: meta.color, fontWeight: 700, minWidth: 90,
              }}>
                {isPicking ? "處理中…" : meta.label}
              </span>
              <span style={{ color: "#718096", fontSize: 11 }}>
                {meta.hint}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
