"use client";

/**
 * ChatOpsAgentRail (2026-07-10, per user feedback).
 *
 * The ChatOps left rail is NOT a chat-history list —「我不是在跟 LLM 聊天」。
 * It shows what the agent is DOING: the live run status of the current
 * conversation plus the platform agent's recent operations (episodes).
 */
import { useCallback, useEffect, useState } from "react";

interface EpisodeRow {
  episode_key: string;
  instruction: string | null;
  status: string | null;
  step_count: number;
  started_at: string | null;
}

const PHASE_LABEL: Record<string, { text: string; color: string; bg: string }> = {
  idle:         { text: "待命",   color: "#64748b", bg: "transparent" },
  building:     { text: "建構中", color: "var(--pd, #164436)", bg: "var(--pl, #DCEBE3)" },
  running:      { text: "執行中", color: "var(--pd, #164436)", bg: "var(--pl, #DCEBE3)" },
  done:         { text: "完成",   color: "#0f766e", bg: "#e7f7ef" },
  error:        { text: "失敗",   color: "#b91c1c", bg: "#fdf0ee" },
  build_failed: { text: "建構失敗", color: "#b91c1c", bg: "#fdf0ee" },
};

function timeLabel(iso: string | null): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 90) return "剛剛";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分鐘前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`;
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function ChatOpsAgentRail({ runPhase, goal, onNew }: {
  runPhase: string;
  goal: string | null;
  onNew: () => void;
}) {
  const [rows, setRows] = useState<EpisodeRow[]>([]);

  const load = useCallback(() => {
    fetch("/api/agent-activity/episodes?limit=15", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((env) => {
        const list = (env?.data ?? env) as EpisodeRow[];
        setRows(Array.isArray(list) ? list : []);
      })
      .catch(() => { /* rail is ambient — fail silent */ });
  }, []);
  useEffect(() => { load(); const id = setInterval(load, 15_000); return () => clearInterval(id); }, [load]);

  const phase = PHASE_LABEL[runPhase] ?? PHASE_LABEL.idle;
  return (
    <div style={{
      width: 250, minWidth: 250, flexShrink: 0,
      background: "var(--pn, #F8F6F0)", borderRight: "1px solid #e2e8f0",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <div style={{ padding: "12px 12px 8px", flexShrink: 0 }}>
        <button onClick={onNew} style={{
          width: "100%", padding: "9px 0", borderRadius: 9, border: "none",
          background: "var(--p, #1E5A44)", color: "#fff",
          fontSize: 13, fontWeight: 700, cursor: "pointer",
        }}>
          + 新對話
        </button>
      </div>

      {/* 進行中 — this conversation's live run */}
      <div style={{ padding: "8px 12px 4px", fontSize: 10.5, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.5px" }}>
        進行中
      </div>
      <div style={{ margin: "0 10px", padding: "9px 11px", borderRadius: 8, background: "#fff", border: "1px solid #e2e8f0" }}>
        <span style={{
          display: "inline-block", fontSize: 11, fontWeight: 700, padding: "1px 8px",
          borderRadius: 10, color: phase.color, background: phase.bg,
          border: runPhase === "idle" ? "1px solid #e2e8f0" : "none",
        }}>{phase.text}</span>
        <div style={{ fontSize: 11.5, color: "#475569", marginTop: 5, lineHeight: 1.5 }}>
          {goal ? goal : runPhase === "idle" ? "沒有進行中的建構" : ""}
        </div>
      </div>

      {/* 最近運作 — platform agent episodes */}
      <div style={{ padding: "14px 12px 4px", fontSize: 10.5, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.5px" }}>
        最近運作
        <a href="/agent-activity" target="_blank" rel="noreferrer"
           style={{ float: "right", fontWeight: 600, color: "var(--p, #1E5A44)", textDecoration: "none" }}>
          全部 →
        </a>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 16px" }}>
        {rows.map((r) => {
          const ok = (r.status ?? "").includes("finish") || r.status === "success";
          const fail = (r.status ?? "").includes("fail") || (r.status ?? "").includes("error");
          return (
            <a key={r.episode_key} href={`/agent-activity`} target="_blank" rel="noreferrer" style={{
              display: "block", padding: "8px 10px", marginBottom: 2, borderRadius: 8,
              textDecoration: "none",
            }}>
              <div style={{
                fontSize: 12, fontWeight: 500, color: "#334155",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {r.instruction || "(未記錄指令)"}
              </div>
              <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: 2, display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{
                  width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                  background: fail ? "#e5484d" : ok ? "#0f9d6a" : "#f5b942",
                }} />
                {timeLabel(r.started_at)} · {r.step_count} steps · {r.status ?? "?"}
              </div>
            </a>
          );
        })}
        {rows.length === 0 && (
          <div style={{ padding: "10px 10px", fontSize: 12, color: "#94a3b8" }}>還沒有運作紀錄</div>
        )}
      </div>
    </div>
  );
}
