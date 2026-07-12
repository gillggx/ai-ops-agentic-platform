"use client";

/**
 * 草稿暫存區 (V78, 2026-07-08 — Phase 1). Per-user shelf of the most-recent 10
 * chat-built pipelines. Auto-parked from the chat panel; here the user can
 * 標記(pin) / 清除 / 打開(Phase 2 陪同設計) / 啟用(Phase 3 自動化).
 */
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import SkillParameterizeModal, { type SkillDoc } from "@/components/skills-v2/SkillParameterizeModal";

interface Draft {
  id: number;
  name: string;
  nl: string;
  kind: string;
  node_count: number;
  edge_count: number;
  marked: boolean;
  created_at: string | null;
}
interface ShelfData {
  drafts: Draft[];
  used: number;
  marked: number;
  limit: number;
  free: number;
}

const INDIGO = "var(--p, #4F46E5)";

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "剛剛";
  if (m < 60) return `${m} 分鐘前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小時前`;
  return `${Math.floor(h / 24)} 天前`;
}

function KindTag({ kind }: { kind: string }) {
  const label =
    kind === "spc_trend" ? "SPC TREND" : kind === "bar" ? "BAR" :
    kind === "table" ? "TABLE" : kind === "panel" ? "SPC PANEL" :
    kind === "pareto" ? "PARETO" : "PIPELINE";
  return (
    <span style={{ position: "absolute", left: 9, top: 9, fontSize: 9.5, fontWeight: 700,
      letterSpacing: ".04em", padding: "2px 7px", borderRadius: 5, background: "var(--pl, #EEF2FF)", color: INDIGO }}>
      {label}
    </span>
  );
}

function Thumb({ kind }: { kind: string }) {
  const c = "var(--p, #4F46E5)", c2 = "var(--p, #818CF8)";
  let art: React.ReactNode;
  if (kind === "bar" || kind === "pareto") {
    art = (
      <svg width="150" height="60" viewBox="0 0 150 60">
        <g fill={c2}>
          <rect x="16" y="30" width="16" height="26" rx="2" /><rect x="42" y="20" width="16" height="36" rx="2" />
          <rect x="68" y="38" width="16" height="18" rx="2" /><rect x="94" y="26" width="16" height="30" rx="2" />
          <rect x="120" y="44" width="16" height="12" rx="2" />
        </g>
        {kind === "pareto" && <polyline points="24,24 50,16 76,12 102,10 128,9" fill="none" stroke={c} strokeWidth="1.5" />}
      </svg>
    );
  } else if (kind === "table") {
    art = (
      <svg width="140" height="56" viewBox="0 0 140 56">
        <g stroke="#E2E8F0"><line x1="8" y1="14" x2="132" y2="14" /><line x1="8" y1="28" x2="132" y2="28" />
          <line x1="8" y1="42" x2="132" y2="42" /><line x1="52" y1="6" x2="52" y2="50" /><line x1="94" y1="6" x2="94" y2="50" /></g>
        <g fill="#CBD5E1"><rect x="14" y="9" width="30" height="4" rx="2" /><rect x="58" y="9" width="28" height="4" rx="2" />
          <rect x="100" y="9" width="24" height="4" rx="2" /></g>
      </svg>
    );
  } else if (kind === "panel") {
    art = (
      <svg width="150" height="60" viewBox="0 0 150 60">
        <rect x="10" y="8" width="60" height="20" rx="2" fill="var(--pl, #EEF2FF)" /><rect x="80" y="8" width="60" height="20" rx="2" fill="var(--pl, #EEF2FF)" />
        <rect x="10" y="34" width="130" height="18" rx="2" fill="#F1F5F9" />
        <polyline points="14,22 30,16 46,20 62,12" fill="none" stroke={c2} strokeWidth="1.5" />
      </svg>
    );
  } else {
    art = (
      <svg width="150" height="60" viewBox="0 0 150 60">
        <g stroke="#CBD5E1" strokeWidth="1"><line x1="10" y1="14" x2="140" y2="14" strokeDasharray="4 3" /><line x1="10" y1="46" x2="140" y2="46" strokeDasharray="4 3" /></g>
        <polyline points="12,32 32,26 52,38 72,22 92,34 112,18 132,30" fill="none" stroke={c} strokeWidth="2" />
      </svg>
    );
  }
  return (
    <div style={{ height: 96, background: "linear-gradient(180deg,#FBFCFE,#F3F6FA)",
      borderBottom: "1px solid #EEF2F6", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
      <KindTag kind={kind} />
      {art}
    </div>
  );
}

function PinBtn({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} title={on ? "已標記 · 不會被自動汰換" : "標記以保留"}
      style={{ position: "absolute", right: 8, top: 8, width: 26, height: 26, borderRadius: 7,
        border: `1px solid ${on ? INDIGO : "#E2E8F0"}`, background: on ? INDIGO : "#fff",
        color: on ? "#fff" : "#94A3B8", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
      <svg width="13" height="13" viewBox="0 0 24 24" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2">
        <path d="M14 2l8 8-5 1-4 6-2-2-5 5-1-1 5-5-2-2 6-4z" />
      </svg>
    </button>
  );
}

export default function DraftsPage() {
  const router = useRouter();
  const [data, setData] = useState<ShelfData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // 啟用 (Phase 3a): reuse the parameterize wizard (= chat 存為 Skill), then
  // hand off to the skill editor where the tested automation UI lives.
  const [enableFor, setEnableFor] = useState<{ name: string; nl: string; pj: Record<string, unknown> } | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/chat-drafts", { cache: "no-store" });
      const j = await r.json();
      setData((j.data ?? j) as ShelfData);
    } catch (e) {
      setErr(String(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const toggleMark = async (d: Draft) => {
    await fetch(`/api/chat-drafts/${d.id}/mark`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ marked: !d.marked }),
    });
    void load();
  };
  const remove = async (d: Draft) => {
    await fetch(`/api/chat-drafts/${d.id}`, { method: "DELETE" });
    void load();
  };
  const clearUnmarked = async () => {
    if (!confirm("清除所有未標記的草稿？已標記的會保留。")) return;
    setBusy(true);
    await fetch("/api/chat-drafts?keep_marked=true", { method: "DELETE" });
    setBusy(false); void load();
  };
  const open = async (d: Draft) => {
    // Phase 2 (V78): stash the full draft + navigate to the operations chat so
    // the agent co-designs it via modify-mode (拿掉區帶 / 加 tooltip / 換機台
    // → deltas, no rebuild). AIAgentPanel's open-draft effect loads it.
    try {
      const r = await fetch(`/api/chat-drafts/${d.id}`, { cache: "no-store" });
      const j = await r.json();
      const full = (j.data ?? j) as { pipeline_json?: unknown; columns?: unknown };
      sessionStorage.setItem("pb:open_draft", JSON.stringify({
        id: d.id, name: d.name, nl: d.nl,
        pipeline_json: full.pipeline_json, columns: full.columns ?? {},
      }));
      // 2026-07-12 fix: V78 時代 "/" 是操作台；現在 "/" 重導 dashboard，
      // co-design 流程落空（user 被丟去不相關頁）。操作台 = /chatops。
      router.push("/chatops");
    } catch {
      alert("打開草稿失敗");
    }
  };

  const startEnable = async (d: Draft) => {
    try {
      const r = await fetch(`/api/chat-drafts/${d.id}`, { cache: "no-store" });
      const j = await r.json();
      const full = (j.data ?? j) as { pipeline_json?: Record<string, unknown> };
      if (!full.pipeline_json) { alert("讀取草稿失敗"); return; }
      setEnableFor({ name: d.name || d.nl || "Chat Skill", nl: d.nl, pj: full.pipeline_json });
    } catch {
      alert("讀取草稿失敗");
    }
  };

  const confirmEnable = async (out: { pipelineJson: Record<string, unknown>; doc: SkillDoc | null }) => {
    if (!enableFor) return;
    setEnableFor(null);
    try {
      const res = await fetch("/api/skills-v2/with-pipeline", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: enableFor.name,
          nl: enableFor.nl,
          sub: enableFor.nl ? enableFor.nl.slice(0, 60) : "從草稿暫存區建立",
          pipeline_json: out.pipelineJson,
          pipeline_kind: "skill",
          doc: out.doc ?? undefined,
        }),
      });
      const env = await res.json();
      if (!res.ok) { alert(`建立 Skill 失敗：${env?.error?.message || res.statusText}`); return; }
      const sid = (env?.data ?? env)?.skill?.id;
      // Skill created as draft. Hand off to the editor to set role / automation
      // + activate (the tested automation surface lives there).
      if (sid && confirm("Skill 已建立（草稿）。要開啟編輯器設定角色 / 自動化並啟用嗎？")) {
        router.push(`/skills/${sid}`);
      }
    } catch {
      alert("建立 Skill 失敗");
    }
  };

  const drafts = data?.drafts ?? [];
  const used = data?.used ?? 0, limit = data?.limit ?? 10, marked = data?.marked ?? 0, free = data?.free ?? limit;

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "24px 22px 64px",
      fontFamily: "-apple-system,'Segoe UI',Roboto,'Noto Sans TC',sans-serif", color: "#0F172A" }}>

      {/* header + capacity */}
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 20, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: ".14em", textTransform: "uppercase", color: INDIGO, fontWeight: 700 }}>Chat · 草稿暫存區</div>
          <h1 style={{ margin: "2px 0", fontSize: 22 }}>草稿暫存區</h1>
          <div style={{ fontSize: 13, color: "#64748B", maxWidth: "52ch" }}>
            對話裡建好的圖會自動留在這裡（最近 {limit} 個）。打開讓 agent 陪你繼續調，滿意了再啟用成 Skill、設自動化。
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
          <span style={{ fontSize: 13, color: "#1E293B", fontWeight: 600 }}>
            <b style={{ fontSize: 15 }}>{used}</b> / {limit} <span style={{ color: "#64748B" }}>· {marked} 個已標記</span>
          </span>
          <div style={{ display: "flex", gap: 3 }}>
            {Array.from({ length: limit }).map((_, i) => {
              const isUsed = i < used, isPinned = i < marked;
              return <span key={i} style={{ width: 16, height: 8, borderRadius: 2,
                background: isUsed ? INDIGO : "#E2E8F0",
                boxShadow: isPinned ? "inset 0 0 0 2px #fff, 0 0 0 1px var(--p, #4F46E5)" : undefined }} />;
            })}
          </div>
        </div>
      </div>

      {/* toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "16px 0 14px", flexWrap: "wrap" }}>
        <button onClick={clearUnmarked} disabled={busy}
          style={{ fontSize: 12.5, padding: "7px 13px", borderRadius: 8, border: "1px solid #FCA5A5",
            background: "transparent", color: "#B91C1C", cursor: "pointer", fontWeight: 600 }}>
          清除未標記（保留已標記）
        </button>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: "#94A3B8" }}>自動存 · 滿 {limit} 個時汰換最舊的未標記草稿</span>
      </div>

      {/* limit warning */}
      {free <= 2 && free > 0 && (
        <div style={{ display: "flex", gap: 11, alignItems: "flex-start", background: "#FFFBEB",
          border: "1px solid #FDE68A", borderRadius: 10, padding: "11px 14px", marginBottom: 16, fontSize: 12.8, color: "#78350F" }}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#B45309" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }}>
            <path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
          <div>還剩 <b style={{ color: "#B45309" }}>{free} 個空位</b>。再建 {free} 個新草稿後，最舊的未標記草稿會被自動汰換 —— 想留住的請先按右上角<b>標記</b>。</div>
        </div>
      )}

      {err && <div style={{ color: "#B91C1C", fontSize: 13, marginBottom: 12 }}>{err}</div>}
      {data && drafts.length === 0 && (
        <div style={{ padding: "48px 0", textAlign: "center", color: "#94A3B8", fontSize: 13 }}>
          還沒有草稿。到對話面板建一張圖，它就會自動出現在這裡。
        </div>
      )}

      {/* grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: 14 }}>
        {drafts.map((d) => (
          <div key={d.id} style={{ position: "relative", background: "#fff",
            border: `1px solid ${d.marked ? "#C7D2FE" : "#E2E8F0"}`, borderRadius: 12, overflow: "hidden",
            display: "flex", flexDirection: "column",
            boxShadow: d.marked ? "0 0 0 1px #C7D2FE" : undefined }}>
            <div style={{ position: "relative" }}>
              <Thumb kind={d.kind} />
              <PinBtn on={d.marked} onClick={() => toggleMark(d)} />
            </div>
            <div style={{ padding: "11px 13px 12px", display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>
              <div style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.35, display: "-webkit-box",
                WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{d.name || d.nl || "Chat 草稿"}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "#64748B" }}>
                {d.marked && <span style={{ fontSize: 10, fontWeight: 600, padding: "1px 7px", borderRadius: 999, background: "var(--pl, #EEF2FF)", color: INDIGO }}>已標記</span>}
                <span style={{ fontFamily: "ui-monospace,monospace" }}>{d.node_count} 節點</span>
                <span style={{ width: 3, height: 3, borderRadius: "50%", background: "#CBD5E1" }} />
                <span>{timeAgo(d.created_at)}</span>
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 2 }}>
                <button onClick={() => open(d)} style={{ flex: 1, fontSize: 11.5, padding: "6px 8px", borderRadius: 7,
                  border: "none", background: INDIGO, color: "#fff", fontWeight: 600, cursor: "pointer" }}>打開</button>
                <button onClick={() => startEnable(d)} title="升級成正式 Skill，設角色 / 自動化"
                  style={{ flex: 1, fontSize: 11.5, padding: "6px 8px", borderRadius: 7, border: "1px solid #E2E8F0",
                    background: "#fff", color: "#1E293B", fontWeight: 600, cursor: "pointer" }}>啟用…</button>
                <button onClick={() => remove(d)} title="刪除"
                  style={{ flex: "0 0 34px", fontSize: 11.5, padding: "6px", borderRadius: 7, border: "1px solid #E2E8F0",
                    background: "#fff", color: "#94A3B8", cursor: "pointer" }}>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ display: "block", margin: "0 auto" }}>
                    <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /></svg>
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {enableFor && (
        <SkillParameterizeModal
          open
          skillName={enableFor.name}
          nl={enableFor.nl}
          pipelineJson={enableFor.pj}
          onClose={() => setEnableFor(null)}
          onConfirm={(out) => { void confirmEnable(out); }}
          confirmLabel="建立 Skill"
        />
      )}
    </div>
  );
}
