"use client";

/**
 * DraftList (My Drafts, 2026-07-12) — 桌機左欄 / 手機抽屜共用的草稿清單。
 * 點一筆 → 草稿卡插入當前對話（B 案）。
 */
import { useCallback, useEffect, useState } from "react";
import type { DraftCardData } from "./DraftCard";

interface DraftRow {
  id: number; name: string; nl: string; kind: string;
  node_count: number; edge_count: number; marked: boolean; created_at: string | null;
}

function timeLabel(iso: string | null): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))} 分鐘前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`;
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function DraftList({ onOpenDraft }: {
  onOpenDraft: (d: DraftCardData) => void;
}) {
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [used, setUsed] = useState(0);
  const [limit, setLimit] = useState(10);

  const load = useCallback(() => {
    fetch("/api/chat-drafts", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((env) => {
        const d = env?.data ?? env;
        if (Array.isArray(d?.drafts)) {
          setRows(d.drafts as DraftRow[]);
          setUsed(d.used ?? d.drafts.length);
          setLimit(d.limit ?? 10);
        }
      })
      .catch(() => { /* ambient */ });
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t); }, [load]);

  return (
    <>
      <div style={{
        padding: "12px 12px 4px", fontSize: 10.5, fontWeight: 700,
        color: "#94a3b8", letterSpacing: "0.5px", display: "flex",
      }}>
        MY DRAFTS ・ {used}/{limit}
        <span style={{ flex: 1 }} />
        <a href="/drafts" target="_blank" rel="noreferrer"
           style={{ fontWeight: 600, color: "var(--p, #1E5A44)", textDecoration: "none" }}>
          草稿頁 →
        </a>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 14px" }}>
        {rows.map((d) => (
          <button key={d.id} onClick={() => onOpenDraft({
            id: d.id, name: d.name, nl: d.nl, kind: d.kind,
            node_count: d.node_count, edge_count: d.edge_count, created_at: d.created_at,
          })} style={{
            display: "block", width: "100%", textAlign: "left", border: "none",
            background: "none", padding: "8px 10px", cursor: "pointer", borderRadius: 8,
          }}>
            <div style={{
              fontSize: 12, fontWeight: 600, color: "#334155",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {d.marked ? "◆ " : ""}{d.name || d.nl || "(未命名草稿)"}
            </div>
            <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: 2, fontFamily: "ui-monospace, monospace" }}>
              {d.node_count} nodes ・ {timeLabel(d.created_at)}
            </div>
          </button>
        ))}
        {rows.length === 0 && (
          <div style={{ padding: "8px 10px", fontSize: 12, color: "#94a3b8" }}>
            還沒有草稿 — 對話建圖後會自動暫存到這裡
          </div>
        )}
      </div>
    </>
  );
}
