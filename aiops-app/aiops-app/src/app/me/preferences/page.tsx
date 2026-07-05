"use client";

/** /me/preferences — 我的偏好（W1）。
 *
 *  稿 1d 語彙的個人版：agent 從「我」的 plan 編輯行為學到的偏好
 *  （agent_knowledge，written_by=planner，API 本身即 caller-scoped —
 *  Java AgentKnowledgeService.findByUserId(caller)），可停用/刪除。
 *  2026-07-06 W1 波。
 */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

interface Pref {
  id: number;
  title: string;
  body: string;
  memo_class?: string;
  written_by?: string | null;
  active: boolean;
  created_at?: string;
}

const M = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

export default function MyPreferencesPage() {
  const t = useTranslations("me");
  const [items, setItems] = useState<Pref[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/agent-knowledge", { cache: "no-store" });
      const all: Pref[] = r.ok ? await r.json() : [];
      // W1 = planner 觀察 user 編輯寫入的偏好；API 已 caller-scoped
      setItems(all.filter((k) => k.written_by === "planner"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);

  const toggle = async (p: Pref) => {
    await fetch(`/api/agent-knowledge/${p.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: !p.active }),
    }).catch(() => {});
    await load();
  };
  const remove = async (p: Pref) => {
    if (!confirm(t("deleteConfirm"))) return;
    await fetch(`/api/agent-knowledge/${p.id}`, { method: "DELETE" }).catch(() => {});
    await load();
  };

  const howApply = (body: string) => {
    const idx = body.indexOf("**How to apply:**");
    return idx >= 0 ? body.slice(idx + 17).trim().split("\n")[0] : "";
  };

  return (
    <div style={{ padding: 24, maxWidth: 860, margin: "0 auto",
                  fontFamily: "system-ui, sans-serif", color: "#211f1c" }}>
      <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>{t("title")}</h1>
      <p style={{ margin: "6px 0 20px", color: "#8a877e", fontSize: 12.5, lineHeight: 1.7 }}>
        {t("subtitle")}
      </p>

      {loading && <div style={{ color: "#a09d95", fontSize: 12 }}>…</div>}
      {!loading && items.length === 0 && (
        <div style={{ padding: "28px 20px", border: "1px dashed #dcdad4", borderRadius: 10,
                      color: "#8a877e", fontSize: 12.5, lineHeight: 1.7, textAlign: "center" }}>
          {t("empty")}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((p) => (
          <div key={p.id} style={{ background: "#fff", border: "1px solid #ddd6fe",
                                   borderRadius: 10, overflow: "hidden",
                                   opacity: p.active ? 1 : 0.6 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "11px 14px",
                          borderBottom: "1px solid #f0edfb" }}>
              <span style={{ fontFamily: M, fontWeight: 700, fontSize: 12, color: "#6d28d9" }}>◆ #{p.id}</span>
              {p.memo_class && (
                <span style={{ fontSize: 9.5, fontWeight: 700, padding: "1px 6px", borderRadius: 3,
                               border: "1px solid #c4b5fd", color: "#6d28d9" }}>{p.memo_class}</span>
              )}
              <span style={{ fontSize: 9.5, fontWeight: 700, padding: "1px 7px", borderRadius: 999,
                             background: p.active ? "#eafaf3" : "#f1efe9",
                             color: p.active ? "#047857" : "#8a877e" }}>
                {p.active ? t("active") : t("disabled")}
              </span>
              <span style={{ flex: 1 }} />
              {p.created_at && (
                <span style={{ fontFamily: M, fontSize: 10, color: "#a09d95" }}>
                  {t("learnedAt")} {String(p.created_at).slice(0, 10)}
                </span>
              )}
            </div>
            <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.55 }}>{p.title}</div>
              {howApply(p.body) && (
                <div style={{ fontSize: 11.5, color: "#3d3a34", lineHeight: 1.65,
                              background: "#faf9f6", borderRadius: 6, padding: "8px 10px" }}>
                  {howApply(p.body)}
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: 8, padding: "9px 14px",
                          borderTop: "1px solid #f0edfb", background: "#fcfbf7" }}>
              <button onClick={() => void toggle(p)}
                      style={{ border: "1px solid #dcdad4", background: "#fff", color: "#55534d",
                               borderRadius: 6, fontSize: 11, padding: "4px 12px",
                               cursor: "pointer", fontFamily: "inherit" }}>
                {p.active ? t("disable") : t("enable")}
              </button>
              <button onClick={() => void remove(p)}
                      style={{ border: "1px solid #f0c1b8", background: "#fff", color: "#b42318",
                               borderRadius: 6, fontSize: 11, padding: "4px 12px",
                               cursor: "pointer", fontFamily: "inherit" }}>
                {t("delete")}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
