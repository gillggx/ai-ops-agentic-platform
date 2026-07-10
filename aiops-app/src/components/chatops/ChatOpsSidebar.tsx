"use client";

/**
 * ChatOpsSidebar (Phase B, design_handoff_operation_platform_v2).
 *
 * Conversation-history rail for the ChatOps presentation: "+ 新對話" on top,
 * sessions grouped 今天 / 昨天 / 更早, active conversation highlighted with
 * theme tokens. Sessions come from Java (agent_sessions, title = first user
 * message) via /api/agent/sessions.
 */
import { useCallback, useEffect, useState } from "react";

export interface SessionRow {
  session_id: string;
  title: string | null;
  updated_at: string;
  has_pipeline?: boolean;
}

function dayGroup(iso: string): "今天" | "昨天" | "更早" {
  const d = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (d >= startOfToday) return "今天";
  const startOfYesterday = new Date(startOfToday.getTime() - 86400_000);
  if (d >= startOfYesterday) return "昨天";
  return "更早";
}

function timeLabel(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 90) return "剛剛";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分鐘前`;
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function ChatOpsSidebar({ activeId, refreshTick, onSelect, onNew }: {
  activeId: string | null;
  /** bump to re-fetch the list (e.g. after a new session is created) */
  refreshTick: number;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
}) {
  const [rows, setRows] = useState<SessionRow[]>([]);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    fetch("/api/agent/sessions?limit=50", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((env) => {
        const list = (env?.data ?? env) as SessionRow[];
        setRows(Array.isArray(list) ? list.filter((s) => s.title) : []);
        setError(false);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);
  // Light polling keeps titles fresh while the user chats.
  useEffect(() => {
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const groups: Array<["今天" | "昨天" | "更早", SessionRow[]]> = [["今天", []], ["昨天", []], ["更早", []]];
  for (const r of rows) {
    const g = dayGroup(r.updated_at);
    groups.find(([k]) => k === g)![1].push(r);
  }

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
      <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 16px" }}>
        {error && (
          <div style={{ padding: "10px 8px", fontSize: 12, color: "#94a3b8" }}>
            對話清單載入失敗
          </div>
        )}
        {groups.map(([label, list]) => list.length > 0 && (
          <div key={label}>
            <div style={{
              padding: "12px 8px 4px", fontSize: 10.5, fontWeight: 700,
              color: "#94a3b8", letterSpacing: "0.5px",
            }}>{label}</div>
            {list.map((s) => {
              const active = s.session_id === activeId;
              return (
                <button
                  key={s.session_id}
                  onClick={() => onSelect(s.session_id)}
                  style={{
                    display: "block", width: "100%", textAlign: "left",
                    padding: "9px 10px", marginBottom: 2, borderRadius: 8,
                    border: "none", cursor: "pointer",
                    background: active ? "var(--pl, #DCEBE3)" : "transparent",
                  }}
                >
                  <div style={{
                    fontSize: 12.5, fontWeight: active ? 700 : 500,
                    color: active ? "var(--pd, #164436)" : "#334155",
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>
                    {s.title || "(未命名對話)"}
                  </div>
                  <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: 2 }}>
                    {timeLabel(s.updated_at)}
                    {s.has_pipeline ? " · 有 pipeline" : ""}
                  </div>
                </button>
              );
            })}
          </div>
        ))}
        {!error && rows.length === 0 && (
          <div style={{ padding: "16px 8px", fontSize: 12, color: "#94a3b8" }}>
            還沒有對話 — 按上面「+ 新對話」開始。
          </div>
        )}
      </div>
    </div>
  );
}
