"use client";

/**
 * PlanConfirmCard (v31, 2026-07-04) — chat-mode goal-plan confirm gate.
 *
 * Chat builds now pause at goal_plan_confirm_gate exactly like the Pipeline
 * Builder: the user sees the P1..PN plan, can edit each phase's goal text,
 * then confirms or cancels. Edits flow through the same interrupt contract
 * as builder mode, so they also feed W1 planner memories.
 *
 * Parent (ChatPanel) owns the POST to /api/agent/chat/intent-respond with
 * {plan_decision:{confirmed, phases}} and drains the resumed build stream
 * through its normal SSE handler (live plan card + ops + charts).
 */

import { useState } from "react";

export interface PlanPhase {
  id: string;
  goal: string;
  expected?: string;
}

interface Props {
  planSummary?: string;
  phases: PlanPhase[];
  /** Parent posts the decision; resolves when the resumed stream ends. */
  onDecide: (confirmed: boolean, phases: PlanPhase[]) => Promise<void>;
}

export function PlanConfirmCard({ planSummary, phases, onDecide }: Props) {
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"confirm" | "cancel" | null>(null);

  const currentPhases = (): PlanPhase[] =>
    phases.map((p) => ({ ...p, goal: (edited[p.id] ?? p.goal).trim() || p.goal }));

  const decide = async (confirmed: boolean) => {
    setBusy(confirmed ? "confirm" : "cancel");
    try { await onDecide(confirmed, currentPhases()); }
    finally { setBusy(null); }
  };

  const nEdited = phases.filter((p) => edited[p.id] != null && edited[p.id].trim() !== p.goal).length;

  return (
    <div style={{
      border: "1px solid #2c5282", borderRadius: 8, background: "#1a2332",
      padding: "12px 14px", fontSize: 12.5, color: "#cbd5e0",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ fontWeight: 700, color: "#90cdf4", fontSize: 13 }}>建構計畫確認</span>
        <span style={{ fontSize: 10.5, color: "#718096" }}>
          與 Pipeline Builder 相同的 plan gate — 可直接改每個 phase 的目標文字
        </span>
      </div>
      {planSummary && (
        <div style={{ color: "#a0aec0", marginBottom: 8, fontSize: 12 }}>{planSummary}</div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
        {phases.map((p, i) => (
          <div key={p.id} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <span style={{
              flexShrink: 0, marginTop: 5, fontSize: 10.5, fontFamily: "monospace",
              color: "#63b3ed", minWidth: 26,
            }}>{p.id || `p${i + 1}`}</span>
            <textarea
              value={edited[p.id] ?? p.goal}
              onChange={(e) => setEdited((prev) => ({ ...prev, [p.id]: e.target.value }))}
              rows={Math.min(3, Math.max(1, Math.ceil((edited[p.id] ?? p.goal).length / 42)))}
              disabled={busy !== null}
              style={{
                flex: 1, resize: "vertical", background: "#0f1722",
                border: `1px solid ${edited[p.id] != null && edited[p.id].trim() !== p.goal ? "#63b3ed" : "#2d3748"}`,
                borderRadius: 5, color: "#e2e8f0", fontSize: 12, padding: "5px 8px",
                fontFamily: "inherit", lineHeight: 1.5,
              }}
            />
            {p.expected && (
              <span style={{
                flexShrink: 0, marginTop: 5, fontSize: 10, color: "#718096",
                border: "1px solid #2d3748", borderRadius: 4, padding: "1px 6px",
              }}>{p.expected}</span>
            )}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button
          onClick={() => void decide(true)}
          disabled={busy !== null}
          style={{
            padding: "6px 16px", borderRadius: 5, fontSize: 12.5, fontWeight: 700,
            cursor: busy ? "not-allowed" : "pointer", border: "none",
            background: busy ? "#2d3748" : "#2b6cb0", color: "#fff",
          }}>
          {busy === "confirm" ? "建構中…" : nEdited > 0 ? `確認（含 ${nEdited} 處修改）開始建構` : "確認，開始建構"}
        </button>
        <button
          onClick={() => void decide(false)}
          disabled={busy !== null}
          style={{
            padding: "6px 14px", borderRadius: 5, fontSize: 12.5,
            cursor: busy ? "not-allowed" : "pointer",
            background: "transparent", color: "#fc8181", border: "1px solid #742a2a",
          }}>
          {busy === "cancel" ? "取消中…" : "取消"}
        </button>
        <span style={{ fontSize: 10.5, color: "#4a5568" }}>確認前不會動到 canvas</span>
      </div>
    </div>
  );
}
