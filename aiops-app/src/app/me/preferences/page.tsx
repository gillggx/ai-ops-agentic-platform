"use client";

/**
 * /me/preferences — 我的偏好（2026-07-13 user 裁決：偏好自 /agent-knowledge
 * 手冊分離，歸戶到使用者設定區；Topbar 帳號選單「我的偏好」原本是死連結）。
 *
 * 儲存仍在 agent_knowledge（memo_class='preference'）— 不開新表：V75 治理、
 * uses 計數、embedding 底座共用；分的是介面不是資料。
 * 對話說「記住…」確認後也會出現在這裡。
 */
import { useCallback, useEffect, useState } from "react";

interface Pref {
  id: number;
  title: string;
  body: string;
  applies_to?: string | null;
  uses?: number;
  last_used_at?: string | null;
  created_at?: string;
  memo_class?: string | null;
}

const APPLIES_LABEL: Record<string, string> = {
  plan: "建圖時", execute: "回答呈現", both: "都適用",
};

export default function MyPreferencesPage() {
  const [prefs, setPrefs] = useState<Pref[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Pref | "new" | null>(null);
  const [msg, setMsg] = useState("");

  const load = useCallback(() => {
    fetch("/api/agent-knowledge", { cache: "no-store" })
      .then((r) => r.json())
      .then((j) => {
        const rows = (j?.data ?? []) as Pref[];
        setPrefs(rows.filter((k) => k.memo_class === "preference"));
      })
      .catch(() => setMsg("載入失敗"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (p: Partial<Pref>, id?: number) => {
    setMsg("");
    try {
      const res = id
        ? await fetch(`/api/agent-knowledge/${id}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: p.title, body: p.body }),
          })
        : await fetch("/api/agent-knowledge", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              scope_type: "global", title: p.title, body: p.body, priority: "med",
              memo_class: "preference", applies_to: p.applies_to ?? "both",
            }),
          });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setEditing(null); load();
    } catch (e) { setMsg(e instanceof Error ? e.message : "儲存失敗"); }
  };

  const del = async (id: number) => {
    if (!confirm("刪除這條偏好？agent 之後不會再套用它。")) return;
    await fetch(`/api/agent-knowledge/${id}`, { method: "DELETE" }).catch(() => {});
    load();
  };

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: "28px 20px 60px",
                  fontFamily: "'Noto Sans TC', system-ui, sans-serif", color: "#1a1d29" }}>
      <h1 style={{ fontSize: 20, fontWeight: 800, margin: 0 }}>我的偏好</h1>
      <p style={{ fontSize: 13, color: "#5b6070", margin: "6px 0 20px", lineHeight: 1.7 }}>
        Agent 每次對話都會帶著這些偏好（索引行是它想起這件事的線索）。
        在對話裡說「記住：…」確認後也會加到這裡；直接問它「你記得我什麼」可以隨時對帳。
      </p>

      {msg && <div style={{ color: "#B91C1C", fontSize: 12.5, marginBottom: 10 }}>{msg}</div>}
      {loading && <div style={{ color: "#8b90a7", fontSize: 13 }}>載入中…</div>}
      {!loading && prefs.length === 0 && (
        <div style={{ padding: "26px 18px", border: "1px dashed #d5d9e2", borderRadius: 12,
                      color: "#8b90a7", fontSize: 13, textAlign: "center" }}>
          還沒有偏好——在對話說「記住：我都看 7 天」試試，或按下面「新增偏好」。
        </div>
      )}

      {prefs.map((p) => (
        <div key={p.id} style={{ border: "1px solid #e2e8f0", borderRadius: 12,
                                 background: "#fff", padding: "13px 16px", marginBottom: 10 }}>
          {editing !== null && editing !== "new" && editing.id === p.id ? (
            <EditForm value={editing} onCancel={() => setEditing(null)}
                      onSave={(v) => void save(v, p.id)} />
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontSize: 13.5, fontWeight: 700, flex: 1 }}>{p.title}</span>
                <span style={{ fontSize: 10.5, fontWeight: 700, color: "var(--pd, #14402F)",
                               background: "var(--pl, #E4EEE7)", padding: "1px 8px", borderRadius: 9 }}>
                  {APPLIES_LABEL[p.applies_to ?? "both"] ?? "都適用"}
                </span>
              </div>
              <div style={{ fontSize: 12.5, color: "#5b6070", marginTop: 5, lineHeight: 1.65,
                            whiteSpace: "pre-wrap" }}>{p.body}</div>
              <div style={{ display: "flex", alignItems: "center", marginTop: 9 }}>
                <span style={{ fontSize: 10.5, color: "#a0a4b5", fontFamily: "ui-monospace, monospace" }}>
                  #{p.id} ・ 被想起 {p.uses ?? 0} 次
                </span>
                <span style={{ flex: 1 }} />
                <button onClick={() => setEditing(p)} style={btn(false)}>編輯</button>
                <button onClick={() => void del(p.id)} style={{ ...btn(false), color: "#B91C1C", marginLeft: 6 }}>刪除</button>
              </div>
            </>
          )}
        </div>
      ))}

      {editing === "new" ? (
        <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, background: "#fff",
                      padding: "13px 16px" }}>
          <EditForm value={{ id: 0, title: "", body: "", applies_to: "both" }}
                    onCancel={() => setEditing(null)} onSave={(v) => void save(v)} />
        </div>
      ) : (
        <button onClick={() => setEditing("new")} style={{ ...btn(true), marginTop: 4 }}>
          ＋ 新增偏好
        </button>
      )}
    </div>
  );
}

function EditForm({ value, onSave, onCancel }: {
  value: Pref; onSave: (v: Partial<Pref>) => void; onCancel: () => void;
}) {
  const [title, setTitle] = useState(value.title);
  const [body, setBody] = useState(value.body);
  const [appliesTo, setAppliesTo] = useState(value.applies_to ?? "both");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <label style={lbl}>索引行（什麼情境該想起這件事）
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={80} style={inp} />
      </label>
      <label style={lbl}>完整內容
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3}
                  maxLength={2000} style={{ ...inp, resize: "vertical", fontFamily: "inherit" }} />
      </label>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: "#64748B" }}>適用</span>
        {(["both", "plan", "execute"] as const).map((k) => (
          <button key={k} onClick={() => setAppliesTo(k)} style={{
            fontSize: 11.5, padding: "4px 10px", borderRadius: 12, cursor: "pointer",
            border: appliesTo === k ? "1px solid var(--p, #1E5A44)" : "1px solid #E2E8F0",
            background: appliesTo === k ? "var(--pl, #E4EEE7)" : "#fff",
            color: appliesTo === k ? "var(--pd, #14402F)" : "#475569",
            fontWeight: appliesTo === k ? 700 : 400,
          }}>{APPLIES_LABEL[k]}</button>
        ))}
        <span style={{ flex: 1 }} />
        <button onClick={onCancel} style={btn(false)}>取消</button>
        <button onClick={() => title.trim() && body.trim()
          && onSave({ title: title.trim(), body: body.trim(), applies_to: appliesTo })}
          style={{ ...btn(true), marginLeft: 6 }}>儲存</button>
      </div>
    </div>
  );
}

const lbl: React.CSSProperties = { fontSize: 11, fontWeight: 700, color: "#64748B" };
const inp: React.CSSProperties = {
  width: "100%", marginTop: 3, padding: "7px 10px", borderRadius: 8,
  border: "1px solid #E2E8F0", fontSize: 13, boxSizing: "border-box",
};
function btn(primary: boolean): React.CSSProperties {
  return {
    fontSize: 12, fontWeight: 700, padding: "6px 14px", borderRadius: 8, cursor: "pointer",
    border: primary ? "none" : "1px solid #E2E8F0",
    background: primary ? "var(--p, #1E5A44)" : "#fff",
    color: primary ? "#fff" : "#475569",
  };
}
