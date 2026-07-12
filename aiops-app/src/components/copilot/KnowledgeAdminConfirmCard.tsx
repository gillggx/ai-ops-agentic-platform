"use client";

/**
 * KnowledgeAdminConfirmCard (2026-07-12) — agent 提議刪除/停用一條規則/知識；
 * 使用者按確認後由瀏覽器以本人 JWT 執行（標準 write-confirm 模型）。
 */
import { useState } from "react";

export interface KnowledgeAdminData {
  action: "delete" | "deactivate";
  knowledge_id: number;
  title?: string | null;
  /** 跨裝置一致：處理結果隨 rich history 同步。 */
  resolved?: "done" | "cancelled";
}

export function KnowledgeAdminConfirmCard({ data, onResolved }: {
  data: KnowledgeAdminData;
  onResolved?: (state: "done" | "cancelled") => void;
}) {
  const [state, setState] = useState<"idle" | "working" | "done" | "cancelled" | "error">(data.resolved ?? "idle");
  const [msg, setMsg] = useState("");
  const label = data.action === "delete" ? "刪除規則" : "停用規則";

  const confirm = async () => {
    setState("working"); setMsg("");
    try {
      const base = `/api/agent-knowledge/${data.knowledge_id}`;
      const res = data.action === "delete"
        ? await fetch(base, { method: "DELETE" })
        : await fetch(base, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ active: false }),
          });
      if (!res.ok) {
        const env = await res.json().catch(() => ({}));
        throw new Error(env?.error?.message || `HTTP ${res.status}`);
      }
      setState("done");
      onResolved?.("done");
    } catch (e) {
      setState("error"); setMsg(e instanceof Error ? e.message : "失敗");
    }
  };

  if (state === "done") {
    return <div style={box}><div style={{ padding: "11px 15px", fontSize: 12.5, color: "#166534", background: "#f0fdf4" }}>
      已完成：{label} — #{data.knowledge_id}{data.title ? `「${data.title}」` : ""}</div></div>;
  }
  if (state === "cancelled") {
    return <div style={box}><div style={{ padding: "10px 15px", fontSize: 12, color: "#94a3b8" }}>已取消。</div></div>;
  }

  return (
    <div style={box}>
      <div style={{ padding: "11px 15px", borderBottom: "1px solid #EEF2F6", background: "var(--pn, #F8FAFC)" }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>{label} — 需要你確認</div>
        <div style={{ fontSize: 11.5, color: "#64748B", marginTop: 2 }}>
          對象：<b>#{data.knowledge_id}</b>{data.title ? `「${data.title}」` : ""}
          {data.action === "delete" ? "（不可逆）" : "（停用後可在手冊頁重新啟用）"}
        </div>
      </div>
      {msg && <div style={{ padding: "8px 15px 0", fontSize: 12, color: "#B91C1C" }}>{msg}</div>}
      <div style={{ padding: "10px 15px", borderTop: "1px solid #EEF2F6", display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={() => { setState("cancelled"); onResolved?.("cancelled"); }} disabled={state === "working"}
          style={{ fontSize: 12.5, padding: "7px 14px", borderRadius: 8, border: "1px solid #E2E8F0",
                   background: "#fff", color: "#475569", cursor: "pointer" }}>取消</button>
        <button onClick={() => void confirm()} disabled={state === "working"}
          style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "none",
                   background: data.action === "delete" ? "#b91c1c" : "var(--p, #2b6cb0)",
                   color: "#fff", fontWeight: 700, cursor: "pointer" }}>
          {state === "working" ? "執行中…" : "確認執行"}
        </button>
      </div>
    </div>
  );
}

const box: React.CSSProperties = { maxWidth: 420, border: "1px solid #E2E8F0", borderRadius: 12, overflow: "hidden", background: "#fff" };
