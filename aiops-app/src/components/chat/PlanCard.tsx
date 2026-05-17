"use client";

/**
 * v30.17i PlanCard — structured render of goal_plan_proposed for chat mode.
 *
 * Previously chat mode showed the plan as a plain text bubble
 * ("📋 Plan: ... | 📊 N 個 phase: • p1 [raw_data] ..."), so users had
 * to read multi-line text to see what was happening. PlanCard renders
 * the same data as a card with per-phase status badges that update
 * live as phase_completed / phase_revise_started events arrive.
 */

import type { CSSProperties } from "react";

export type PhaseStatus =
  | "pending"
  | "running"        // phase in progress (after goal_plan_confirmed, before completed)
  | "completed"
  | "revising"       // hit max_rounds, currently rethinking
  | "revising_retry"
  | "failed"
  | "handover_take_over"
  | "handover_drop";

export interface PhaseEntry {
  id: string;
  goal: string;
  expected: string;          // raw_data / transform / chart / etc.
  status: PhaseStatus;
  auto_injected?: boolean;
  rationale?: string;
  reason?: string;
}

export interface PlanData {
  summary: string;
  phases: PhaseEntry[];
  confirmed?: boolean;       // toggled true on goal_plan_confirmed event
}

interface Props {
  plan: PlanData;
}

const STATUS_STYLE: Record<PhaseStatus, { badge: string; bg: string; fg: string }> = {
  pending:           { badge: "—",    bg: "#1a202c", fg: "#4a5568" },
  running:           { badge: "•••",  bg: "#1a365d", fg: "#90cdf4" },
  completed:         { badge: "✓",    bg: "#1c4532", fg: "#68d391" },
  revising:          { badge: "⏸",    bg: "#5f370e", fg: "#f6ad55" },
  revising_retry:    { badge: "↻",    bg: "#5f370e", fg: "#f6ad55" },
  failed:            { badge: "✗",    bg: "#63171b", fg: "#fc8181" },
  handover_take_over:{ badge: "↳",    bg: "#22543d", fg: "#9ae6b4" },
  handover_drop:     { badge: "✗",    bg: "#63171b", fg: "#fc8181" },
};

const EXPECTED_LABEL: Record<string, string> = {
  raw_data:  "原始",
  transform: "轉換",
  verdict:   "判定",
  chart:     "圖表",
  table:     "表格",
  scalar:    "數值",
  alarm:     "告警",
};

export function PlanCard({ plan }: Props) {
  const containerStyle: CSSProperties = {
    width: "100%",
    background: "#0d1117",
    border: "1px solid #2d3748",
    borderRadius: 8,
    padding: 12,
    fontSize: 12,
    color: "#e2e8f0",
  };

  return (
    <div style={containerStyle}>
      <div style={{
        fontSize: 11, color: "#90cdf4", fontWeight: 600, marginBottom: 8,
        display: "flex", justifyContent: "space-between", alignItems: "center",
      }}>
        <span>📋 Plan {plan.confirmed ? "(building)" : "(proposed)"}</span>
        <span style={{ color: "#4a5568" }}>{plan.phases.length} phase</span>
      </div>
      <div style={{ marginBottom: 8, lineHeight: 1.5 }}>{plan.summary}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {plan.phases.map((p) => {
          const sty = STATUS_STYLE[p.status] ?? STATUS_STYLE.pending;
          const expLabel = EXPECTED_LABEL[p.expected] ?? p.expected;
          return (
            <div key={p.id} style={{
              display: "flex", alignItems: "flex-start", gap: 8,
              padding: "6px 8px",
              background: sty.bg,
              borderRadius: 4,
            }}>
              <span style={{
                width: 22, height: 22, flexShrink: 0,
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                background: "rgba(0,0,0,0.3)", borderRadius: 4,
                color: sty.fg, fontWeight: 700, fontSize: 12,
              }}>{sty.badge}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
                  <span style={{ color: sty.fg, fontWeight: 600 }}>{p.id}</span>
                  <span style={{
                    fontSize: 10, color: "#a0aec0",
                    padding: "1px 5px", background: "rgba(255,255,255,0.05)",
                    borderRadius: 3,
                  }}>{expLabel}</span>
                  {p.auto_injected && (
                    <span style={{
                      fontSize: 10, color: "#d6bcfa",
                      padding: "1px 5px", background: "rgba(159,122,234,0.15)",
                      borderRadius: 3,
                    }}>auto</span>
                  )}
                </div>
                <div style={{ marginTop: 2, color: "#cbd5e0", lineHeight: 1.4 }}>
                  {p.goal}
                </div>
                {p.rationale && p.status === "completed" && (
                  <div style={{ marginTop: 3, fontSize: 11, color: "#9ae6b4", fontStyle: "italic" }}>
                    → {p.rationale}
                  </div>
                )}
                {p.reason && (p.status === "revising" || p.status === "failed") && (
                  <div style={{ marginTop: 3, fontSize: 11, color: "#fbb98a", fontStyle: "italic" }}>
                    ⚠ {p.reason}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
