"use client";

import type { GoalPhase } from "./GoalPlanCard";

export type PhaseStatus = "pending" | "in_progress" | "completed" | "failed" | "paused";

export interface PhaseRuntime {
  status: PhaseStatus;
  round?: number;       // current ReAct round (1..max)
  maxRound?: number;    // typically 8
  lastAction?: string;  // most recent tool name
  lastActionResult?: string;
  failReason?: string;
  rationale?: string;   // when completed
  // v30.1 (2026-05-16): set by phase_completed event when verifier
  // auto-completed (vs LLM phase_complete signal). Triggers the
  // "auto" badge so user knows it wasn't an LLM declaration.
  autoCompleted?: boolean;
  // When this phase was completed as part of a fast-forward (one block
  // covering >=2 phases), the trigger phase id is recorded so we can
  // group them visually.
  fastForwardedBy?: string;  // node id that covered this phase
  fastForwardedByBlock?: string;  // block_id for human readability
}

interface Props {
  phases: GoalPhase[];
  /** Map phase id -> runtime info. Pending phases can be omitted. */
  runtime: Record<string, PhaseRuntime>;
}

/**
 * v30 phase timeline — vertical, one row per phase. Color-coded status.
 * Updates in real-time from SSE events.
 */
export default function PhaseTimeline({ phases, runtime }: Props) {
  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid #e2e8f0",
        borderRadius: 10,
        padding: "12px 14px",
        margin: "10px 0",
        fontSize: 12.5,
        lineHeight: 1.5,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: "#475569",
          textTransform: "uppercase",
          letterSpacing: 0.6,
          marginBottom: 8,
        }}
      >
        Phase progress ({Object.values(runtime).filter((r) => r.status === "completed").length}/{phases.length} done)
      </div>
      <ol style={{ margin: 0, paddingLeft: 0, listStyle: "none" }}>
        {phases.map((p, i) => {
          const rt = runtime[p.id] || { status: "pending" as PhaseStatus };
          return (
            <PhaseRow key={p.id} index={i + 1} phase={p} runtime={rt} />
          );
        })}
      </ol>
    </div>
  );
}

const STATUS_STYLE: Record<PhaseStatus, { bg: string; fg: string; icon: string; label: string }> = {
  pending:     { bg: "#f1f5f9", fg: "#64748b", icon: ".",  label: "等待" },
  in_progress: { bg: "#dbeafe", fg: "#1e40af", icon: ">",  label: "進行中" },
  completed:   { bg: "#d1fae5", fg: "#065f46", icon: "[OK]", label: "完成" },
  failed:      { bg: "#fee2e2", fg: "#991b1b", icon: "[X]",  label: "失敗" },
  paused:      { bg: "#fef3c7", fg: "#92400e", icon: "[..]", label: "暫停" },
};

function PhaseRow({
  index,
  phase,
  runtime,
}: {
  index: number;
  phase: GoalPhase;
  runtime: PhaseRuntime;
}) {
  const st = STATUS_STYLE[runtime.status];
  return (
    <li
      style={{
        display: "flex",
        gap: 12,
        padding: "8px 0",
        borderBottom: "1px solid #f1f5f9",
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          flexShrink: 0,
          borderRadius: 6,
          background: st.bg,
          color: st.fg,
          fontSize: 14,
          fontWeight: 700,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
        title={st.label}
      >
        {runtime.status === "completed" || runtime.status === "failed"
          ? st.icon
          : index}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            color: "#0f172a",
            fontWeight: runtime.status === "in_progress" ? 600 : 400,
          }}
        >
          {phase.goal}
        </div>
        <div
          style={{
            display: "flex",
            gap: 10,
            alignItems: "center",
            marginTop: 2,
            fontSize: 11,
            color: "#64748b",
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              padding: "1px 6px",
              borderRadius: 3,
              background: st.bg,
              color: st.fg,
              fontWeight: 600,
            }}
          >
            {st.label}
          </span>
          {runtime.round != null && runtime.maxRound != null && (
            <span>
              round {runtime.round}/{runtime.maxRound}
            </span>
          )}
          {runtime.lastAction && (
            <span>
              last: <code style={{ color: "#475569" }}>{runtime.lastAction}</code>
              {runtime.lastActionResult && (
                <span style={{ color: "#94a3b8" }}>
                  {" "}
                  → {runtime.lastActionResult.slice(0, 60)}
                </span>
              )}
            </span>
          )}
          {runtime.autoCompleted && runtime.status === "completed" && (
            <span
              style={{
                padding: "1px 6px",
                borderRadius: 3,
                background: "#fef3c7",
                color: "#92400e",
                fontWeight: 600,
                fontSize: 10.5,
              }}
              title="由 server verifier 自動偵測完成（非 LLM 主動 declare）"
            >
              auto
            </span>
          )}
          {runtime.fastForwardedByBlock && runtime.status === "completed" && (
            <span
              style={{
                padding: "1px 6px",
                borderRadius: 3,
                background: "#ede9fe",
                color: "#5b21b6",
                fontWeight: 600,
                fontSize: 10.5,
              }}
              title={`由 ${runtime.fastForwardedBy ?? "?"} [${runtime.fastForwardedByBlock}] 一個 block 涵蓋多 phase`}
            >
              ff: {runtime.fastForwardedByBlock}
            </span>
          )}
          {runtime.rationale && runtime.status === "completed" && (
            <span style={{ color: "#15803d" }}>
              {runtime.rationale.slice(0, 100)}
            </span>
          )}
          {runtime.failReason && runtime.status === "failed" && (
            <span style={{ color: "#991b1b" }}>{runtime.failReason}</span>
          )}
        </div>
      </div>
    </li>
  );
}
