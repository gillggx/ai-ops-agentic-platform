"use client";

/**
 * ChatOpsAgentRail (v3, 2026-07-13 per design mockup).
 *
 * 左欄結構（上而下）：
 *   1. + 新對話
 *   2. 最近運作 — 本人跨對話的背景工作（agent_tasks），點了跳回該對話
 *   3. 對話紀錄 — SessionList 常駐（近期 x/5 / 打包歷史）
 *   4. MY DRAFTS — 草稿清單
 * Console 自 v3 起移到右側深色面板（ChatOpsConsolePanel），不在 rail。
 */
import { useCallback, useEffect, useState } from "react";
import { SessionList } from "./SessionList";
import { DraftList } from "./DraftList";
import type { DraftCardData } from "./DraftCard";

interface RecentTask {
  task_id: string;
  status: string;               // running | finished | failed | interrupted
  goal?: string | null;
  created_at?: string;
  finished_at?: string | null;
  chat_session_id?: string | null;
}

function ago(iso?: string): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "剛剛";
  if (s < 3600) return `${Math.floor(s / 60)} 分鐘前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小時前`;
  return `${Math.floor(s / 86400)} 天前`;
}

const TASK_DOT: Record<string, string> = {
  running: "#39d98a", finished: "#0f9d6a", failed: "#e5484d", interrupted: "#c8841a",
};

export function ChatOpsAgentRail({ runPhase, onNew, onOpenSession, activeSessionId, onOpenDraft }: {
  runPhase: string;
  onNew: () => void;
  /** Session 管理 (2026-07-12)：預設開新 — 舊對話從「對話紀錄」進。 */
  onOpenSession: (sessionId: string) => void;
  activeSessionId: string | null;
  /** My Drafts (2026-07-12)：點草稿 → 草稿卡插入當前對話（B 案）。 */
  onOpenDraft: (d: DraftCardData) => void;
}) {
  const [tasks, setTasks] = useState<RecentTask[]>([]);

  const loadTasks = useCallback(() => {
    fetch("/api/agent/tasks/recent", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (Array.isArray(j?.tasks)) setTasks(j.tasks.slice(0, 4)); })
      .catch(() => { /* ambient */ });
  }, []);
  // 建構開始/結束時刷新 + 背景 60s 輪詢（狀態翻轉靠這個）。
  useEffect(() => { loadTasks(); }, [loadTasks, runPhase]);
  useEffect(() => {
    const t = setInterval(loadTasks, 60000);
    return () => clearInterval(t);
  }, [loadTasks]);

  return (
    <div style={{
      width: 264, minWidth: 264, flexShrink: 0,
      background: "var(--pn, #F8F6F0)", borderRight: "1px solid #e2e8f0",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <div style={{ padding: "12px 12px 4px", flexShrink: 0 }}>
        <button onClick={onNew} style={{
          width: "100%", padding: "9px 0", borderRadius: 9, border: "none",
          background: "var(--p, #1E5A44)", color: "#fff",
          fontSize: 13, fontWeight: 700, cursor: "pointer",
        }}>
          + 新對話
        </button>
      </div>

      {/* 最近運作 — 背景工作（V85 agent_tasks），點了回到該對話 */}
      <div style={{ padding: "8px 14px 2px", flexShrink: 0, display: "flex", alignItems: "center" }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: "#8b90a7", letterSpacing: ".05em" }}>最近運作</span>
        <span style={{ flex: 1 }} />
        <a href="/agent-activity" target="_blank" rel="noreferrer"
           style={{ fontSize: 10.5, color: "#8b90a7", textDecoration: "none" }}>全部 →</a>
      </div>
      <div style={{ padding: "2px 10px 6px", flexShrink: 0 }}>
        {tasks.length === 0 && (
          <div style={{ padding: "6px 4px", fontSize: 11.5, color: "#a0a4b5" }}>還沒有背景工作</div>
        )}
        {tasks.map((tk) => (
          <button key={tk.task_id}
            onClick={() => tk.chat_session_id && onOpenSession(tk.chat_session_id)}
            title={tk.goal ?? ""}
            style={{
              width: "100%", textAlign: "left", padding: "7px 8px", borderRadius: 9,
              border: "none", background: "transparent", cursor: tk.chat_session_id ? "pointer" : "default",
              display: "flex", gap: 8, alignItems: "flex-start",
            }}>
            <span style={{
              width: 7, height: 7, borderRadius: "50%", marginTop: 5, flexShrink: 0,
              background: TASK_DOT[tk.status] ?? "#a0a4b5",
            }} />
            <span style={{ minWidth: 0 }}>
              <span style={{
                display: "block", fontSize: 12, fontWeight: 600, color: "#1a1d29",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>{(tk.goal ?? "（未命名工作）").slice(0, 40)}</span>
              <span style={{ display: "block", fontSize: 10.5, color: "#8b90a7", fontFamily: "ui-monospace, Menlo, monospace" }}>
                {ago(tk.created_at)} ・ {tk.status === "running" ? "執行中" : tk.status}
              </span>
            </span>
          </button>
        ))}
      </div>

      {/* 對話紀錄 — 常駐（近期 x/5 / 打包歷史 x/10） */}
      <div style={{
        margin: "2px 10px 8px", padding: "10px 10px 6px", borderRadius: 12,
        background: "#fff", border: "1px solid #e2e8f0",
        flex: 1, minHeight: 120, display: "flex", flexDirection: "column", overflow: "hidden",
      }}>
        <SessionList activeId={activeSessionId} onOpen={onOpenSession} />
      </div>

      {/* My Drafts — 點草稿 → 草稿卡插入對話 */}
      <DraftList onOpenDraft={onOpenDraft} />
    </div>
  );
}
