"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Global listener for cowork UI-handoffs (V63, the "B" auto-popup path).
 *
 * Subscribes to the SSE stream; when cowork creates a handoff, a banner auto-
 * appears so the user can jump straight into our GUI to review / confirm —
 * without having to click the link cowork pasted (that link is the "A" fallback).
 * EventSource sends the session cookie, so the /api proxy authenticates it.
 */

type Pending = { id: string; kind: string; target_ref?: string; action?: string };

const KIND_COPY: Record<string, string> = {
  review_rule: "已建好一條 Rule，請審核",
  confirm_delete: "請確認刪除一條 Rule",
  confirm_disable: "請確認停用一條 Rule",
  confirm_activate: "請確認啟用一條 Rule",
  view_detail: "有內容要給你看",
};

export default function HandoffListener() {
  const router = useRouter();
  const [pending, setPending] = useState<Pending | null>(null);

  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;
    try {
      es = new EventSource("/api/handoffs/stream");
      es.addEventListener("handoff", (e) => {
        try {
          const d = JSON.parse((e as MessageEvent).data) as Pending;
          if (d?.id) setPending(d);
        } catch { /* ignore malformed */ }
      });
      es.onerror = () => { if (closed && es) es.close(); };
    } catch { /* SSE unsupported / unauthorized — silently skip */ }
    return () => { closed = true; es?.close(); };
  }, []);

  if (!pending) return null;
  const label = KIND_COPY[pending.kind] ?? "cowork 有一個待處理項目";

  return (
    <div style={{ position: "fixed", right: 20, bottom: 20, zIndex: 9999, width: 320,
      background: "#0f1e3d", color: "#fff", borderRadius: 12, padding: "14px 16px",
      boxShadow: "0 8px 24px rgba(0,0,0,.25)", fontFamily: "-apple-system,Segoe UI,Roboto,sans-serif" }}>
      <div style={{ fontSize: 11, color: "#7cc0ff", fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 4 }}>cowork</div>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>{label}{pending.target_ref ? ` (${pending.target_ref})` : ""}</div>
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={() => { const id = pending.id; setPending(null); router.push(`/handoff/${id}`); }}
          style={{ flex: 1, padding: "8px 0", borderRadius: 8, border: "none", background: "#2563eb", color: "#fff", fontWeight: 700, fontSize: 13, cursor: "pointer" }}>
          開啟
        </button>
        <button onClick={() => setPending(null)}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #33415c", background: "transparent", color: "#c3d4f0", fontSize: 13, cursor: "pointer" }}>
          稍後
        </button>
      </div>
    </div>
  );
}
