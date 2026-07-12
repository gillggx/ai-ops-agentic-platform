"use client";

/**
 * SkillAdminConfirmCard (domain-skill-management, 2026-07-10).
 * Agent proposes deactivate / delete / rename on a Domain Skill; the browser
 * performs the call under the user's JWT only on 確認 — standard write-confirm.
 */
import { useState } from "react";

export interface SkillAdminData {
  action: "deactivate" | "delete" | "rename";
  slug: string;
  new_name?: string | null;
  new_description?: string | null;
  /** 跨裝置一致 (2026-07-12)：處理結果寫回訊息資料，隨 rich history 同步 —
   *  另一台裝置還原時卡片顯示已處理，不會再被按一次（刪除類不可逆）。 */
  resolved?: "done" | "cancelled";
}

const LABEL: Record<SkillAdminData["action"], string> = {
  deactivate: "停用 Domain Skill",
  delete: "刪除 Domain Skill",
  rename: "修改 Domain Skill 名稱/描述",
};

export function SkillAdminConfirmCard({ data, onResolved }: {
  data: SkillAdminData;
  onResolved?: (state: "done" | "cancelled") => void;
}) {
  const [name, setName] = useState(data.new_name ?? "");
  const [desc, setDesc] = useState(data.new_description ?? "");
  const [state, setState] = useState<"idle" | "working" | "done" | "cancelled" | "error">(data.resolved ?? "idle");
  const [msg, setMsg] = useState("");
  const resolve = (s: "done" | "cancelled") => { setState(s); onResolved?.(s); };

  const confirm = async () => {
    setState("working"); setMsg("");
    try {
      const base = `/api/skills-v2/${encodeURIComponent(data.slug)}`;
      let res: Response;
      if (data.action === "deactivate") {
        res = await fetch(`${base}/activate`, { method: "DELETE" });
      } else if (data.action === "delete") {
        res = await fetch(base, { method: "DELETE" });
      } else {
        if (!name.trim() && !desc.trim()) throw new Error("名稱或描述至少填一項");
        const body: Record<string, string> = {};
        if (name.trim()) body.name = name.trim();
        if (desc.trim()) body.nl = desc.trim();
        res = await fetch(base, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      }
      if (!res.ok) {
        const env = await res.json().catch(() => ({}));
        throw new Error(env?.error?.message || `HTTP ${res.status}`);
      }
      resolve("done");
    } catch (e) {
      setState("error"); setMsg(e instanceof Error ? e.message : "失敗");
    }
  };

  if (state === "done") {
    return <div style={box}><div style={{ padding: "11px 15px", fontSize: 12.5, color: "#166534", background: "#f0fdf4" }}>
      已完成：{LABEL[data.action]} — {data.slug}</div></div>;
  }
  if (state === "cancelled") {
    return <div style={box}><div style={{ padding: "10px 15px", fontSize: 12, color: "#94a3b8" }}>已取消。</div></div>;
  }

  return (
    <div style={box}>
      <div style={{ padding: "11px 15px", borderBottom: "1px solid #EEF2F6", background: "var(--pn, #F8FAFC)" }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>{LABEL[data.action]} — 需要你確認</div>
        <div style={{ fontSize: 11.5, color: "#64748B", marginTop: 2 }}>
          對象：<b style={{ fontFamily: "monospace" }}>{data.slug}</b>
          {data.action === "delete" ? "（不可逆，自動化會一併停止）" : ""}
        </div>
      </div>
      {data.action === "rename" && (
        <div style={{ padding: "12px 15px", display: "flex", flexDirection: "column", gap: 8 }}>
          <label style={lbl}>新名稱
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} style={inp} />
          </label>
          <label style={lbl}>新描述
            <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={2} style={{ ...inp, resize: "vertical" }} />
          </label>
        </div>
      )}
      {msg && <div style={{ padding: "8px 15px 0", fontSize: 12, color: "#B91C1C" }}>{msg}</div>}
      <div style={{ padding: "10px 15px", borderTop: "1px solid #EEF2F6", display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={() => resolve("cancelled")} disabled={state === "working"}
          style={{ fontSize: 12.5, padding: "7px 14px", borderRadius: 8, border: "1px solid #E2E8F0",
                   background: "#fff", color: "#475569", cursor: "pointer" }}>取消</button>
        <button onClick={confirm} disabled={state === "working"}
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
const lbl: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 4, fontSize: 11, fontWeight: 600, color: "#64748B" };
const inp: React.CSSProperties = { fontSize: 13, padding: "7px 10px", borderRadius: 7, border: "1px solid #E2E8F0", color: "#0f172a", outline: "none" };
