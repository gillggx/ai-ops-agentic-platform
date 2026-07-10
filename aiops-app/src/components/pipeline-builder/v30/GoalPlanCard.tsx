"use client";

import { useState } from "react";

export interface ExpectedOutput {
  kind?: string | null;
  value_desc?: string | null;
  criterion?: string | null;
  outcome_keys?: string[];
}

export interface PlanRemoval {
  node_id: string;
  reason?: string;
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
  /** v31.2 — modification plans may propose removing superseded nodes.
   *  Rendered as a red checklist; user unchecks to keep a node. */
  removals?: PlanRemoval[];
  /** Called when user clicks Confirm. Second arg = the removals the user
   *  left checked (undefined when the plan proposed none). */
  onConfirm: (phases: GoalPhase[], removals?: PlanRemoval[]) => void;
  /** Called when user clicks Cancel — backend treats as refused. */
  onCancel: () => void;
  /** When set, hide buttons and show a "(decided)" tag. */
  decided?: "confirmed" | "cancelled";
  /** v31.1 (2026-07-04): allow inline editing of each phase's goal text.
   *  onConfirm receives the EDITED phases; edits flow through the same
   *  interrupt contract into W1 planner memories. Default false keeps the
   *  original read-only behaviour. */
  editable?: boolean;
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
  removals,
  onConfirm,
  onCancel,
  decided,
  editable = false,
}: Props) {
  const [acting, setActing] = useState<false | "confirm" | "cancel">(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  // removals default CHECKED (the plan proposed them); uncheck = keep node.
  const [keepRemoval, setKeepRemoval] = useState<Record<string, boolean>>(
    () => Object.fromEntries((removals ?? []).map((r) => [r.node_id, true])),
  );

  const effectivePhases = (): GoalPhase[] =>
    phases.map((p) => {
      const t = edits[p.id];
      if (t == null || !t.trim() || t.trim() === p.goal) return p;
      return { ...p, goal: t.trim(), user_edited: true };
    });
  const nEdited = phases.filter(
    (p) => edits[p.id] != null && edits[p.id].trim() !== "" && edits[p.id].trim() !== p.goal,
  ).length;

  const handleConfirm = () => {
    setActing("confirm");
    const approved = removals?.length
      ? removals.filter((r) => keepRemoval[r.node_id])
      : undefined;
    onConfirm(editable ? effectivePhases() : phases, approved);
  };
  const handleCancel = () => {
    setActing("cancel");
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
              {editable && !decided ? (
                <textarea
                  value={edits[p.id] ?? p.goal}
                  onChange={(e) => setEdits((prev) => ({ ...prev, [p.id]: e.target.value }))}
                  rows={Math.min(3, Math.max(1, Math.ceil((edits[p.id] ?? p.goal).length / 46)))}
                  disabled={!!acting}
                  style={{
                    width: "100%", resize: "vertical", marginBottom: 3,
                    border: `1px solid ${edits[p.id] != null && edits[p.id].trim() !== p.goal ? "var(--p, #3b82f6)" : "#e2e8f0"}`,
                    borderRadius: 5, color: "#0f172a", fontSize: 13, padding: "4px 8px",
                    fontFamily: "inherit", lineHeight: 1.5, background: "#fff",
                  }}
                />
              ) : (
                <div style={{ color: "#0f172a", marginBottom: 3 }}>{p.goal}</div>
              )}
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
              {/* 記憶連動：user 編輯過的 phase 在確認後標記 W1 寫入（design
                  handoff 2026-07-04 — plan 卡與 Console 記憶效應區呼應）。 */}
              {decided === "confirmed" &&
                (p.user_edited ||
                  (edits[p.id] != null && edits[p.id].trim() !== "" && edits[p.id].trim() !== p.goal)) && (
                <div style={{ fontSize: 10.5, color: "#6d28d9", marginTop: 3 }}>
                  ◆ 你編輯了這行 → 已寫入 W1 偏好
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>

      {removals && removals.length > 0 && (
        <div style={{
          marginTop: 12, border: "1px solid #fecaca", background: "#fef2f2",
          borderRadius: 8, padding: "10px 12px",
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, color: "#991b1b",
            textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 6,
          }}>
            將移除（修改 plan · 可逐筆取消）
          </div>
          {removals.map((r) => (
            <label key={r.node_id} style={{
              display: "flex", gap: 8, alignItems: "flex-start",
              fontSize: 12.5, padding: "3px 0", cursor: decided ? "default" : "pointer",
              opacity: keepRemoval[r.node_id] ? 1 : 0.55,
            }}>
              <input
                type="checkbox"
                checked={!!keepRemoval[r.node_id]}
                disabled={!!decided || !!acting}
                onChange={(e) => setKeepRemoval((prev) => ({ ...prev, [r.node_id]: e.target.checked }))}
                style={{ marginTop: 3 }}
              />
              <span>
                <span style={{ fontFamily: "ui-monospace, Menlo, monospace", fontWeight: 700, color: "#991b1b" }}>
                  {r.node_id}
                </span>
                {r.reason && <span style={{ color: "#7f1d1d" }}> — {r.reason}</span>}
                {!keepRemoval[r.node_id] && <span style={{ color: "#64748b" }}>（保留，不移除）</span>}
              </span>
            </label>
          ))}
        </div>
      )}

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
              disabled={!!acting}
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
              disabled={!!acting}
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
              {acting === "confirm" ? "建構中…"
                : nEdited > 0 ? `確認（含 ${nEdited} 處修改），開始建構` : "確認，開始建構"}
            </button>
            {acting === "confirm" && (
              <span style={{ fontSize: 11, color: "#b45309", fontWeight: 600 }}>
                agent 建構中 — 進度顯示於下方 / 畫布
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}
