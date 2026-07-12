"use client";

/**
 * SessionList (2026-07-12) — 對話紀錄清單，Gemini 式：搜尋 + 近期 + 改名/刪除。
 * 手機抽屜與桌機左欄「對話紀錄」共用。開啟舊對話走 AppShell.openChatSession
 * （rich history 還原 + 背景工作 reattach 機制已有）。
 */
import { useCallback, useEffect, useState } from "react";

export interface SessionRow {
  session_id: string;
  title: string | null;
  updated_at: string | null;
  has_pipeline: boolean;
}

function timeLabel(iso: string | null): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))} 分鐘前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`;
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function SessionList({ onOpen, activeId, dark = false }: {
  onOpen: (sessionId: string) => void;
  activeId?: string | null;
  /** 桌機左欄用淺色卡；手機抽屜白底。dark 目前保留。 */
  dark?: boolean;
}) {
  const [rows, setRows] = useState<SessionRow[]>([]);
  const [q, setQ] = useState("");
  const [menuFor, setMenuFor] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch("/api/agent/sessions?limit=50", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((env) => {
        const list = (env?.data ?? env) as SessionRow[];
        if (Array.isArray(list)) setRows(list);
      })
      .catch(() => { /* ambient */ });
  }, []);
  useEffect(() => { load(); }, [load]);

  const rename = async (row: SessionRow) => {
    const t = window.prompt("改名這個對話：", row.title ?? "");
    if (!t || !t.trim()) return;
    try {
      await fetch(`/api/agent/session/${encodeURIComponent(row.session_id)}/title`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: t.trim() }),
      });
    } finally { setMenuFor(null); load(); }
  };

  const remove = async (row: SessionRow) => {
    if (!window.confirm(`刪除「${(row.title ?? "此對話").slice(0, 30)}」？（含圖卡紀錄，不可復原）`)) return;
    try {
      await fetch(`/api/agent/session/${encodeURIComponent(row.session_id)}`, { method: "DELETE" });
    } finally { setMenuFor(null); load(); }
  };

  const shown = rows.filter((r) => !q || (r.title ?? "").toLowerCase().includes(q.toLowerCase()));
  const ink = dark ? "#e6eaee" : "#1a1d29";
  const sub = dark ? "#9aa1b5" : "#8b90a7";

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜尋對話…" style={{
        margin: "2px 0 8px", padding: "8px 11px", borderRadius: 10,
        border: "1px solid #e2e0d8", background: "#fff", fontSize: 16,
        color: "#1a1d29", outline: "none", width: "100%", boxSizing: "border-box",
      }} />
      <div style={{ overflowY: "auto", minHeight: 0 }}>
        {shown.map((r) => (
          <div key={r.session_id} style={{
            display: "flex", alignItems: "center", borderRadius: 9,
            background: r.session_id === activeId ? "rgba(30,90,68,0.08)" : "transparent",
          }}>
            <button onClick={() => onOpen(r.session_id)} style={{
              flex: 1, minWidth: 0, textAlign: "left", border: "none", background: "none",
              padding: "9px 10px", cursor: "pointer",
            }}>
              <div style={{
                fontSize: 13, fontWeight: 500, color: ink,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {r.title || "(未命名對話)"}
              </div>
              <div style={{ fontSize: 10.5, color: sub, marginTop: 1 }}>
                {timeLabel(r.updated_at)}{r.has_pipeline ? " ・ 有圖" : ""}
              </div>
            </button>
            <div style={{ position: "relative", flexShrink: 0 }}>
              <button onClick={() => setMenuFor(menuFor === r.session_id ? null : r.session_id)} style={{
                border: "none", background: "none", color: sub, cursor: "pointer",
                fontSize: 16, padding: "6px 8px",
              }}>⋯</button>
              {menuFor === r.session_id && (
                <div style={{
                  position: "absolute", right: 4, top: 26, zIndex: 30,
                  background: "#fff", border: "1px solid #e2e0d8", borderRadius: 10,
                  boxShadow: "0 8px 22px -10px rgba(20,23,60,.3)", overflow: "hidden",
                }}>
                  <button onClick={() => void rename(r)} style={menuBtn}>改名</button>
                  <button onClick={() => void remove(r)} style={{ ...menuBtn, color: "#B91C1C" }}>刪除</button>
                </div>
              )}
            </div>
          </div>
        ))}
        {shown.length === 0 && (
          <div style={{ padding: "14px 10px", fontSize: 12, color: sub }}>
            {q ? "沒有符合的對話" : "還沒有對話紀錄"}
          </div>
        )}
      </div>
    </div>
  );
}

const menuBtn: React.CSSProperties = {
  display: "block", width: "100%", textAlign: "left", border: "none",
  background: "none", padding: "9px 18px", fontSize: 13, color: "#1a1d29",
  cursor: "pointer", whiteSpace: "nowrap",
};
