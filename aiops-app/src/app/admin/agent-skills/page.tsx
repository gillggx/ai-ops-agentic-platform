"use client";

/**
 * /admin/agent-skills — 標準 Skill 管理 (V82, 2026-07-10).
 *
 * A standard skill = a named instruction manual the Coordinator loads on
 * demand (when_to_use rides in its system-prompt index; body is fetched via
 * load_skill). The manuals are DATA: IT admin edits them here — no deploy.
 */
import { useCallback, useEffect, useState } from "react";

interface AgentSkill {
  id: number;
  name: string;
  when_to_use: string;
  body: string;
  enabled: boolean;
  updated_by: string | null;
  updated_at: string;
}

export default function AgentSkillsPage() {
  const [rows, setRows] = useState<AgentSkill[]>([]);
  const [sel, setSel] = useState<AgentSkill | null>(null);
  const [draftWhen, setDraftWhen] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [toast, setToast] = useState("");

  const load = useCallback(() => {
    fetch("/api/admin/agent-skills", { cache: "no-store" })
      .then((r) => r.json())
      .then((env) => setRows((env?.data ?? env) as AgentSkill[]))
      .catch(() => setToast("清單載入失敗"));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  const open = (s: AgentSkill) => { setSel(s); setDraftWhen(s.when_to_use); setDraftBody(s.body); setCreating(false); };

  const save = async () => {
    try {
      if (creating) {
        const r = await fetch("/api/admin/agent-skills", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: newName.trim(), when_to_use: draftWhen, body: draftBody, enabled: true }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      } else if (sel) {
        const r = await fetch(`/api/admin/agent-skills/${encodeURIComponent(sel.name)}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ when_to_use: draftWhen, body: draftBody }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      }
      setToast("已儲存 — agent 下一輪對話即生效");
      setSel(null); setCreating(false); load();
    } catch (e) {
      setToast(`儲存失敗：${e instanceof Error ? e.message : e}`);
    }
  };

  const toggle = async (s: AgentSkill) => {
    await fetch(`/api/admin/agent-skills/${encodeURIComponent(s.name)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !s.enabled }),
    }).catch(() => setToast("切換失敗"));
    load();
  };

  const editorOpen = creating || !!sel;
  return (
    <div style={{ padding: "20px 24px", maxWidth: 1080 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 4 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "#1a202c" }}>標準 Skill（agent 說明書）</h1>
        <button onClick={() => { setCreating(true); setSel(null); setNewName(""); setDraftWhen(""); setDraftBody("# 新 Skill\n\n## 工具與時機\n\n## 規範\n"); }}
          style={{ fontSize: 12.5, fontWeight: 700, padding: "6px 14px", borderRadius: 8, border: "none",
                   background: "var(--p, #2b6cb0)", color: "#fff", cursor: "pointer" }}>
          + 新增
        </button>
      </div>
      <p style={{ margin: "0 0 16px", fontSize: 12.5, color: "#64748b", maxWidth: 720 }}>
        每份 Skill = 教 agent「怎麼做某類事」的說明書。「使用時機」會進 agent 的目錄；命中時 agent 才載入全文照做。
        改完存檔即生效（不用部署）。這裡是標準 Skill —— pipeline 那種請到 Skill 庫（Domain Skill）。
      </p>

      <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--pn, #f8fafc)", textAlign: "left" }}>
              <th style={th}>名稱</th><th style={th}>使用時機</th><th style={th}>狀態</th><th style={th}>最後更新</th><th style={th} />
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} style={{ borderTop: "1px solid #f1f5f9" }}>
                <td style={{ ...td, fontFamily: "monospace", fontWeight: 600 }}>{s.name}</td>
                <td style={td}>{s.when_to_use}</td>
                <td style={td}>
                  <button onClick={() => toggle(s)} style={{
                    fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 10, cursor: "pointer",
                    border: "1px solid", ...(s.enabled
                      ? { background: "#e7f7ef", color: "#0f766e", borderColor: "#99e2c8" }
                      : { background: "#f8fafc", color: "#94a3b8", borderColor: "#e2e8f0" }),
                  }}>{s.enabled ? "啟用中" : "停用"}</button>
                </td>
                <td style={{ ...td, color: "#94a3b8", fontSize: 12 }}>
                  {s.updated_by ?? "—"} · {new Date(s.updated_at).toLocaleString("zh-TW", { hour12: false })}
                </td>
                <td style={td}>
                  <button onClick={() => open(s)} style={{
                    fontSize: 12, color: "var(--p, #2b6cb0)", background: "none",
                    border: "none", cursor: "pointer", fontWeight: 600,
                  }}>編輯</button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={5} style={{ ...td, color: "#94a3b8", textAlign: "center", padding: 24 }}>還沒有標準 Skill</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {editorOpen && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 70, background: "rgba(15,18,30,.45)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }} onClick={() => { setSel(null); setCreating(false); }}>
          <div onClick={(e) => e.stopPropagation()} style={{
            background: "#fff", borderRadius: 14, width: 760, maxWidth: "94vw", maxHeight: "88vh",
            display: "flex", flexDirection: "column", overflow: "hidden",
            boxShadow: "0 18px 48px rgba(0,0,0,.24)",
          }}>
            <div style={{ padding: "14px 20px", borderBottom: "1px solid #e2e8f0", fontWeight: 700, fontSize: 15 }}>
              {creating ? "新增標準 Skill" : `編輯：${sel?.name}`}
            </div>
            <div style={{ padding: "14px 20px", display: "flex", flexDirection: "column", gap: 12, overflowY: "auto" }}>
              {creating && (
                <label style={lbl}>名稱（英文-kebab，例：alarm-handling）
                  <input value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={64} style={inp} />
                </label>
              )}
              <label style={lbl}>使用時機（一句話，會進 agent 目錄）
                <input value={draftWhen} onChange={(e) => setDraftWhen(e.target.value)} maxLength={300} style={inp} />
              </label>
              <label style={lbl}>說明書全文（markdown — 工具用法 / 流程 / 規範 / 範例）
                <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)} rows={18}
                  style={{ ...inp, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12.5, lineHeight: 1.6, resize: "vertical" }} />
              </label>
            </div>
            <div style={{ padding: "12px 20px", borderTop: "1px solid #e2e8f0", display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button onClick={() => { setSel(null); setCreating(false); }} style={{
                fontSize: 12.5, padding: "8px 14px", borderRadius: 8,
                border: "1px solid #e2e8f0", background: "#fff", color: "#475569", cursor: "pointer",
              }}>取消</button>
              <button onClick={() => void save()}
                disabled={!draftWhen.trim() || !draftBody.trim() || (creating && !newName.trim())}
                style={{
                  fontSize: 12.5, fontWeight: 700, padding: "8px 18px", borderRadius: 8, border: "none",
                  background: "var(--p, #2b6cb0)", color: "#fff", cursor: "pointer",
                }}>儲存</button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div style={{
          position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)",
          background: "#1a202c", color: "#fff", padding: "9px 16px", borderRadius: 9,
          fontSize: 13, zIndex: 80,
        }}>{toast}</div>
      )}
    </div>
  );
}

const th: React.CSSProperties = { padding: "9px 14px", fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.4px" };
const td: React.CSSProperties = { padding: "10px 14px", verticalAlign: "top" };
const lbl: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 5, fontSize: 11.5, fontWeight: 600, color: "#64748b" };
const inp: React.CSSProperties = { fontSize: 13.5, padding: "8px 11px", borderRadius: 8, border: "1px solid #e2e8f0", color: "#0f172a", outline: "none" };
