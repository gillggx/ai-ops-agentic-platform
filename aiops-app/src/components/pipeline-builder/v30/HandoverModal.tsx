"use client";

import { useState } from "react";

export type HandoverChoice = "edit_goal" | "take_over" | "backlog" | "abort";

interface Props {
  failedPhaseId: string;
  reason: string;
  triedSummary?: string[];
  missingCapabilities?: string[];
  onChoose: (choice: HandoverChoice, newGoal?: string) => void;
}

/**
 * v30 handover modal — appears when a phase fails after revise. User picks
 * one of 4 options. POC focuses on take_over and abort; edit_goal supplies
 * a new goal text; backlog logs missing_capabilities to /tmp/v30_backlog.jsonl.
 */
export default function HandoverModal({
  failedPhaseId,
  reason,
  triedSummary,
  missingCapabilities,
  onChoose,
}: Props) {
  const [showEditGoal, setShowEditGoal] = useState(false);
  const [newGoal, setNewGoal] = useState("");
  const [acting, setActing] = useState<HandoverChoice | null>(null);

  const handle = (choice: HandoverChoice, goal?: string) => {
    setActing(choice);
    onChoose(choice, goal);
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.55)",
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 12,
          width: "100%",
          maxWidth: 560,
          padding: "20px 22px",
          boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
          fontSize: 13.5,
          lineHeight: 1.55,
        }}
      >
        <div style={{ fontSize: 11, fontWeight: 700, color: "#991b1b", letterSpacing: 0.6 }}>
          BUILD PAUSED — phase failed
        </div>
        <h2 style={{ margin: "4px 0 12px", fontSize: 17, color: "#0f172a" }}>
          Phase <code>{failedPhaseId}</code> 做不到
        </h2>

        <div
          style={{
            background: "#fef2f2",
            border: "1px solid #fca5a5",
            borderRadius: 6,
            padding: "10px 12px",
            marginBottom: 12,
          }}
        >
          <div style={{ fontWeight: 600, color: "#991b1b", marginBottom: 4 }}>原因</div>
          <div style={{ color: "#7c2d12" }}>{reason}</div>
        </div>

        {missingCapabilities && missingCapabilities.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: "#475569",
                textTransform: "uppercase",
                letterSpacing: 0.6,
                marginBottom: 4,
              }}
            >
              缺乏的能力
            </div>
            <ul style={{ margin: 0, paddingLeft: 20, color: "#475569" }}>
              {missingCapabilities.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        )}

        {triedSummary && triedSummary.length > 0 && (
          <details style={{ marginBottom: 12 }}>
            <summary style={{ cursor: "pointer", fontSize: 11, color: "#64748b" }}>
              ▶ 嘗試紀錄 ({triedSummary.length} 個 actions)
            </summary>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 11, color: "#64748b" }}>
              {triedSummary.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </details>
        )}

        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: "#475569",
            textTransform: "uppercase",
            letterSpacing: 0.6,
            margin: "16px 0 8px",
          }}
        >
          請選下一步
        </div>

        {showEditGoal ? (
          <div style={{ marginBottom: 10 }}>
            <textarea
              value={newGoal}
              onChange={(e) => setNewGoal(e.target.value)}
              placeholder="重新描述這個 phase 的目標..."
              rows={3}
              style={{
                width: "100%",
                padding: 8,
                fontSize: 13,
                border: "1px solid #cbd5e1",
                borderRadius: 5,
                fontFamily: "inherit",
                resize: "vertical",
              }}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 8, justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={() => setShowEditGoal(false)}
                style={btnStyle("transparent", "#64748b", "#cbd5e1")}
              >
                返回
              </button>
              <button
                type="button"
                disabled={!newGoal.trim() || !!acting}
                onClick={() => handle("edit_goal", newGoal.trim())}
                style={btnStyle("#3b82f6", "#fff", "transparent")}
              >
                送出新目標再試
              </button>
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            <button
              type="button"
              disabled={!!acting}
              onClick={() => setShowEditGoal(true)}
              style={optionBtn()}
            >
              <strong>改寫 phase 目標</strong>
              <div style={optionBtnDesc()}>讓你重述要怎麼做，agent 用新目標再試一輪</div>
            </button>
            <button
              type="button"
              disabled={!!acting}
              onClick={() => handle("take_over")}
              style={optionBtn()}
            >
              <strong>我自己接手</strong>
              <div style={optionBtnDesc()}>結束 agent session，目前 canvas 留給你手動繼續</div>
            </button>
            <button
              type="button"
              disabled={!!acting}
              onClick={() => handle("backlog")}
              style={optionBtn()}
            >
              <strong>補一個 follow-up</strong>
              <div style={optionBtnDesc()}>把缺乏的能力記成 backlog，agent 升級後 retry；canvas 同 take_over 保留</div>
            </button>
            <button
              type="button"
              disabled={!!acting}
              onClick={() => handle("abort")}
              style={optionBtn("#fef2f2", "#991b1b")}
            >
              <strong>中止</strong>
              <div style={optionBtnDesc()}>全部清掉，重新開始</div>
            </button>
          </div>
        )}

        {acting && (
          <div style={{ marginTop: 10, fontSize: 11, color: "#64748b", textAlign: "center" }}>
            傳送中... ({acting})
          </div>
        )}
      </div>
    </div>
  );
}

function btnStyle(bg: string, fg: string, border: string): React.CSSProperties {
  return {
    background: bg,
    color: fg,
    border: border === "transparent" ? "none" : `1px solid ${border}`,
    borderRadius: 5,
    padding: "6px 12px",
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
  };
}

function optionBtn(bg = "#f8fafc", color = "#0f172a"): React.CSSProperties {
  return {
    background: bg,
    color,
    border: "1px solid #cbd5e1",
    borderRadius: 6,
    padding: "10px 14px",
    fontSize: 13,
    textAlign: "left",
    cursor: "pointer",
    transition: "background 0.15s",
  };
}

function optionBtnDesc(): React.CSSProperties {
  return {
    fontSize: 11,
    color: "#64748b",
    marginTop: 2,
    fontWeight: 400,
  };
}
