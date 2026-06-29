"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * /handoff/[id] — the landing for a cowork-created UI handoff (V63).
 *
 * cowork (via MCP) never executes dangerous actions; it creates a handoff and
 * hands the user this URL (link = "A"; the app-shell SSE listener auto-opens it
 * = "B"). Here the human reviews / confirms in our real GUI:
 *   review_rule / view_detail  -> redirect to the existing rule / detail page
 *   confirm_delete|disable|activate -> impact + a real confirm button; only on
 *     confirm does the platform run the action (POST /resolve), under this user.
 */

type Handoff = {
  id: string;
  kind: string;
  target_ref?: string;
  action?: string;
  payload?: string;
  status: string;
};

const ACTION_COPY: Record<string, { verb: string; tone: string }> = {
  confirm_delete: { verb: "刪除", tone: "#b42318" },
  confirm_disable: { verb: "停用", tone: "#b54708" },
  confirm_activate: { verb: "啟用上線", tone: "#067647" },
  // skills_v2 critical actions proposed by cowork (confirm here, runs under your auth)
  confirm_skill_delete: { verb: "刪除 Skill", tone: "#b42318" },
  confirm_skill_activate: { verb: "啟用 Skill", tone: "#067647" },
  confirm_skill_automate: { verb: "設定自動化", tone: "#b54708" },
  confirm_skill_bind: { verb: "綁定 / 覆蓋 pipeline", tone: "#b54708" },
};

export default function HandoffPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [h, setH] = useState<Handoff | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch(`/api/handoffs/${id}`, { cache: "no-store" });
        const d = await r.json();
        const rec = (d?.data ?? d) as Handoff;
        if (!alive) return;
        if (!r.ok || !rec?.kind) {
          setErr(d?.error?.message || `載入失敗 (HTTP ${r.status})`);
          return;
        }
        // review_rule -> render the rule review (Playbook) inline below, standalone
        // (bare layout, no app shell). view_detail still redirects to its detail page.
        if (rec.kind === "view_detail" && rec.target_ref) {
          router.replace(/^\d+$/.test(rec.target_ref) ? `/pipeline-view/${rec.target_ref}` : `/skills/${rec.target_ref}`);
          return;
        }
        setH(rec);
      } catch (e) {
        if (alive) setErr(`載入失敗：${String(e)}`);
      }
    })();
    return () => { alive = false; };
  }, [id, router]);

  async function act(kind: "resolve" | "cancel") {
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`/api/handoffs/${id}/${kind}`, { method: "POST" });
      const d = await r.json();
      if (!r.ok) { setErr(d?.error?.message || `操作失敗 (HTTP ${r.status})`); return; }
      setDone(kind === "resolve" ? "已執行完成。" : "已取消。");
    } catch (e) {
      setErr(`操作失敗：${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const wrap: React.CSSProperties = { maxWidth: 560, margin: "60px auto", padding: "0 20px", fontFamily: "-apple-system,Segoe UI,Roboto,sans-serif", color: "#1f2933" };
  const card: React.CSSProperties = { background: "#fff", border: "1px solid #e5e7eb", borderRadius: 14, padding: "24px 26px", boxShadow: "0 1px 3px rgba(0,0,0,.06)" };

  if (err) return <div style={wrap}><div style={{ ...card, background: "#fef3f2", borderColor: "#fecaca", color: "#b42318" }}>{err}</div></div>;
  if (!h) return <div style={wrap}><div style={card}>載入中…</div></div>;

  // review_rule — v2 (skills-v2-refactor): Playbook component sunset; redirect
  // to the new Editor page for inline review. Cowork users get a slightly
  // worse "shell visible" UX but the review action is still 1 click away.
  if (h.kind === "review_rule" && h.target_ref) {
    if (typeof window !== "undefined") {
      router.replace(`/skills/${encodeURIComponent(h.target_ref)}`);
    }
    return <div style={wrap}><div style={card}>Redirecting…</div></div>;
  }

  const copy = ACTION_COPY[h.kind] ?? { verb: "執行", tone: "#1d4ed8" };
  let impact = "";
  try { impact = (JSON.parse(h.payload || "{}").impact as string) || ""; } catch { /* noop */ }

  if (done) {
    return <div style={wrap}><div style={card}>
      <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>{done}</div>
      <div style={{ color: "#6b7280", fontSize: 14 }}>你可以關閉此頁。</div>
    </div></div>;
  }

  return (
    <div style={wrap}>
      <div style={card}>
        <div style={{ fontSize: 12, color: "#6b7280", letterSpacing: ".05em", textTransform: "uppercase" }}>由 cowork 提出，需你確認</div>
        <h1 style={{ fontSize: 22, margin: "6px 0 4px", color: copy.tone }}>確認{copy.verb}這條 Rule</h1>
        <div style={{ fontSize: 14, color: "#475467", marginBottom: 16 }}>對象：<b>{h.target_ref}</b></div>
        {impact ? (
          <div style={{ background: "#f8fafc", border: "1px solid #e5e7eb", borderRadius: 10, padding: "12px 14px", fontSize: 13, color: "#1f2933", marginBottom: 18 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>影響</div>{impact}
          </div>
        ) : null}
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={() => act("resolve")} disabled={busy}
            style={{ flex: 1, padding: "10px 0", borderRadius: 9, border: "none", background: copy.tone, color: "#fff", fontWeight: 700, fontSize: 14, cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}>
            {busy ? "處理中…" : `確認${copy.verb}`}
          </button>
          <button onClick={() => act("cancel")} disabled={busy}
            style={{ padding: "10px 18px", borderRadius: 9, border: "1px solid #d0d5dd", background: "#fff", color: "#475467", fontWeight: 600, fontSize: 14, cursor: busy ? "default" : "pointer" }}>
            取消
          </button>
        </div>
        <div style={{ marginTop: 14, fontSize: 12, color: "#98a2b3" }}>此動作在你（已登入）確認後才會執行，並記入 audit。</div>
      </div>
    </div>
  );
}
