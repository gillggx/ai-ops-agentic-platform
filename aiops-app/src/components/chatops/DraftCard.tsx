"use client";

/**
 * DraftCard (My Drafts B 案, 2026-07-12) — 對話內的草稿卡。
 *
 * 動作（user 裁決）：
 *   - Try Run：桌機/手機都可 — 跑一次、圖表直接回貼到對話
 *   - 啟用：接既有 skill_activate 確認卡（含可變欄位勾選）
 *   - 刪除：走確認
 *   - 編輯 pipeline：手機卡關（顯示提示），桌機開 /drafts；不做 canvas 檢視
 */
import { useEffect, useState } from "react";

export interface DraftCardData {
  id: number;
  name: string;
  nl: string;
  kind: string;
  node_count: number;
  edge_count: number;
  created_at: string | null;
  /** 跨裝置一致：處理結果隨 rich history 同步。 */
  resolved?: "deleted";
  lastRun?: { status: string; duration_ms?: number; nodes_ok?: number; nodes_total?: number };
}

export interface TryRunChart { node_id: string; chart_spec: Record<string, unknown> }

export function DraftCard({ data, onPatch, onCharts, onEnable }: {
  data: DraftCardData;
  /** 把卡片狀態寫回訊息資料（rich history 同步）。 */
  onPatch: (patch: Partial<DraftCardData>) => void;
  /** Try Run 結果圖 → 回貼對話。 */
  onCharts: (charts: TryRunChart[], note: string) => void;
  /** 啟用 → 由 panel 接 skill_activate 確認卡。 */
  onEnable: (pj: Record<string, unknown>, name: string, nl: string) => void;
}) {
  const [busy, setBusy] = useState<"" | "run" | "enable" | "delete">("");
  const [msg, setMsg] = useState("");
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    setIsMobile(window.matchMedia("(max-width: 899px)").matches);
  }, []);

  const fetchPipeline = async (): Promise<Record<string, unknown> | null> => {
    const r = await fetch(`/api/chat-drafts/${data.id}`, { cache: "no-store" });
    if (!r.ok) return null;
    const j = await r.json();
    return ((j.data ?? j) as { pipeline_json?: Record<string, unknown> }).pipeline_json ?? null;
  };

  const tryRun = async () => {
    setBusy("run"); setMsg("");
    try {
      const pj = await fetchPipeline();
      if (!pj) throw new Error("讀取草稿失敗（可能已被清掉）");
      const r = await fetch("/api/pipeline/tryrun", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pipeline_json: pj }),
      });
      const out = await r.json();
      if (!r.ok) throw new Error(out?.error || `HTTP ${r.status}`);
      const nodes = (out.nodes ?? []) as Array<{ status?: string }>;
      const okN = nodes.filter((n) => n.status === "success").length;
      onPatch({ lastRun: { status: out.status, duration_ms: out.duration_ms, nodes_ok: okN, nodes_total: nodes.length } });
      const charts = (out.charts ?? []) as TryRunChart[];
      onCharts(charts,
        out.status === "success"
          ? `Try Run 完成（${okN}/${nodes.length} 節點，${out.duration_ms ?? "?"}ms）${charts.length ? "— 圖表如下" : "— 這條 pipeline 沒有圖表輸出"}`
          : `Try Run 失敗（${okN}/${nodes.length} 節點成功）：${(out.nodes ?? []).find((n: { error?: string }) => n.error)?.error ?? out.error ?? "未知錯誤"}`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "失敗");
    } finally {
      setBusy("");
    }
  };

  const enable = async () => {
    setBusy("enable"); setMsg("");
    try {
      const pj = await fetchPipeline();
      if (!pj) throw new Error("讀取草稿失敗");
      onEnable(pj, data.name || data.nl || "Chat Skill", data.nl || "");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "失敗");
    } finally {
      setBusy("");
    }
  };

  const remove = async () => {
    if (!window.confirm(`刪除草稿「${(data.name || "未命名").slice(0, 30)}」？`)) return;
    setBusy("delete"); setMsg("");
    try {
      const r = await fetch(`/api/chat-drafts/${data.id}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      onPatch({ resolved: "deleted" });
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "失敗");
    } finally {
      setBusy("");
    }
  };

  if (data.resolved === "deleted") {
    return <div style={box}><div style={{ padding: "10px 15px", fontSize: 12, color: "#94a3b8" }}>
      草稿「{(data.name || "未命名").slice(0, 30)}」已刪除。</div></div>;
  }

  return (
    <div style={box}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid #EEF2F6", background: "var(--pn, #F8FAFC)" }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>
          草稿：{data.name || "未命名 pipeline"}
          <span style={{
            marginLeft: 8, fontSize: 9.5, fontWeight: 700, fontFamily: "ui-monospace, monospace",
            padding: "1px 7px", borderRadius: 4, background: "#f1f2f7", color: "#5b6070",
          }}>{data.kind || "pipeline"}</span>
        </div>
        <div style={{ fontSize: 11, color: "#64748B", marginTop: 2, fontFamily: "ui-monospace, monospace" }}>
          {data.node_count} nodes ・ {data.edge_count} edges
          {data.lastRun ? ` ・ 上次 Try Run：${data.lastRun.status === "success" ? "成功" : "失敗"}（${data.lastRun.nodes_ok}/${data.lastRun.nodes_total}）` : ""}
        </div>
      </div>
      {data.nl && (
        <div style={{ padding: "9px 14px", fontSize: 12, color: "#475569", lineHeight: 1.6 }}>{data.nl}</div>
      )}
      {isMobile && (
        <div style={{ padding: "0 14px 8px", fontSize: 11, color: "#B45309" }}>
          [note] 編輯 pipeline 結構請在桌機的草稿頁進行 — 手機可 Try Run、啟用、刪除。
        </div>
      )}
      {msg && <div style={{ padding: "0 14px 8px", fontSize: 12, color: "#B91C1C" }}>{msg}</div>}
      <div style={{ padding: "9px 14px", borderTop: "1px solid #EEF2F6", display: "flex", gap: 7, justifyContent: "flex-end", flexWrap: "wrap" }}>
        <button onClick={() => void remove()} disabled={!!busy} style={btn(false)}>
          {busy === "delete" ? "刪除中…" : "刪除"}
        </button>
        {!isMobile && (
          <a href="/drafts" target="_blank" rel="noreferrer" style={{ ...btn(false), textDecoration: "none", display: "inline-block" }}>
            編輯（草稿頁）↗
          </a>
        )}
        <button onClick={() => void tryRun()} disabled={!!busy} style={btn(false)}>
          {busy === "run" ? "執行中…" : "Try Run"}
        </button>
        <button onClick={() => void enable()} disabled={!!busy} style={btn(true)}>
          {busy === "enable" ? "準備中…" : "啟用"}
        </button>
      </div>
    </div>
  );
}

const box: React.CSSProperties = {
  maxWidth: 460, border: "1px solid #E2E8F0", borderRadius: 12, overflow: "hidden", background: "#fff",
};
function btn(primary: boolean): React.CSSProperties {
  return {
    fontSize: 12, fontWeight: 700, padding: "6px 13px", borderRadius: 8, cursor: "pointer",
    border: primary ? "none" : "1px solid #E2E8F0",
    background: primary ? "var(--p, #2b6cb0)" : "#fff",
    color: primary ? "#fff" : "#475569",
  };
}
