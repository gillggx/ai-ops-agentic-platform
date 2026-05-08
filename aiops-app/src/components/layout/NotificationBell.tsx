"use client";

/**
 * Phase 9-C — bell-icon notification widget. Polls /api/notifications/inbox
 * every 30s and shows an unread badge + dropdown with recent items.
 *
 * Each row payload is JSON {title, body, rule_id, run_id?, chart_id?};
 * clicking a row marks it read + (future: deep-links to the run's chart).
 */

import { useCallback, useEffect, useState } from "react";

interface InboxItem {
  id: number;
  ruleId: number | null;
  payload: string;
  readAt: string | null;
  createdAt: string;
}

interface ParsedPayload {
  title?: string;
  body?: string;
  rule_id?: number;
  run_id?: number;
  chart_id?: number;
}

const POLL_MS = 30_000;

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);

  const fetchInbox = useCallback(async () => {
    try {
      const res = await fetch(`/api/notifications/inbox?limit=20`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) return;
      const payload = body.data ?? body;
      setItems(payload.items ?? []);
      setUnread(Number(payload.unreadCount ?? 0));
    } catch {
      // silent — bell is best-effort
    }
  }, []);

  useEffect(() => {
    fetchInbox();
    const t = setInterval(fetchInbox, POLL_MS);
    return () => clearInterval(t);
  }, [fetchInbox]);

  const markRead = async (id: number) => {
    setLoading(true);
    try {
      await fetch(`/api/notifications/${id}/read`, { method: "POST" });
      await fetchInbox();
    } finally {
      setLoading(false);
    }
  };

  const markAllRead = async () => {
    setLoading(true);
    try {
      await fetch(`/api/notifications/read-all`, { method: "POST" });
      await fetchInbox();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          position: "relative",
          background: "none",
          border: "1px solid #e2e8f0",
          borderRadius: 6,
          padding: "6px 10px",
          fontSize: 16,
          cursor: "pointer",
          color: unread > 0 ? "#dc2626" : "#475569",
        }}
        title={unread > 0 ? `${unread} 則未讀通知` : "通知"}
      >
        🔔
        {unread > 0 && (
          <span style={{
            position: "absolute",
            top: -3, right: -3,
            background: "#dc2626",
            color: "#fff",
            borderRadius: 10,
            minWidth: 16, height: 16,
            padding: "0 4px",
            fontSize: 10, fontWeight: 700,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 99 }} />
          <div style={dropdownStyle}>
            <div style={{
              padding: "10px 14px",
              borderBottom: "1px solid #f1f5f9",
              display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "#0f172a" }}>
                通知 {unread > 0 && <span style={{ color: "#dc2626" }}>· {unread} 則未讀</span>}
              </span>
              {unread > 0 && (
                <button
                  onClick={markAllRead}
                  disabled={loading}
                  style={{ background: "none", border: "none", color: "#3b82f6", fontSize: 11, cursor: "pointer" }}
                >
                  全部標記已讀
                </button>
              )}
            </div>

            {items.length === 0 ? (
              <div style={{ padding: 24, textAlign: "center", color: "#94a3b8", fontSize: 12 }}>
                目前沒有通知
              </div>
            ) : (
              <div style={{ maxHeight: 360, overflowY: "auto" }}>
                {items.map((it) => {
                  const p = parsePayload(it.payload);
                  const isUnread = !it.readAt;
                  return (
                    <div
                      key={it.id}
                      onClick={() => isUnread && markRead(it.id)}
                      style={{
                        padding: "10px 14px",
                        borderBottom: "1px solid #f8fafc",
                        cursor: isUnread ? "pointer" : "default",
                        background: isUnread ? "#f0f9ff" : "#fff",
                      }}
                    >
                      <div style={{
                        display: "flex", alignItems: "center", gap: 6,
                        fontSize: 12, fontWeight: 600, color: "#1e293b",
                      }}>
                        {isUnread && <span style={{ width: 6, height: 6, borderRadius: 3, background: "#3b82f6" }} />}
                        {p.title ?? "通知"}
                      </div>
                      {p.body && (
                        <div style={{ fontSize: 11, color: "#475569", marginTop: 4, lineHeight: 1.5 }}>
                          {p.body}
                        </div>
                      )}
                      <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 4 }}>
                        {new Date(it.createdAt).toLocaleString("zh-TW", { hour12: false })}
                        {p.rule_id != null && (
                          <a href={`/rules`} style={{ marginLeft: 8, color: "#3b82f6", textDecoration: "none" }}>
                            管理規則
                          </a>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function parsePayload(raw: string): ParsedPayload {
  try {
    return JSON.parse(raw) as ParsedPayload;
  } catch {
    return { title: "(payload parse error)", body: raw.slice(0, 120) };
  }
}

const dropdownStyle: React.CSSProperties = {
  position: "absolute",
  top: "calc(100% + 6px)",
  right: 0,
  zIndex: 100,
  minWidth: 320,
  maxWidth: 380,
  background: "#fff",
  border: "1px solid #e2e8f0",
  borderRadius: 6,
  boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
  overflow: "hidden",
};
