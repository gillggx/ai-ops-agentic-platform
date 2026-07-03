"use client";

/**
 * Supervisor curation review (Phase 5, V72) — human-in-the-loop queue.
 *
 * The offline proposer (Haiku) queues MERGE / CORRECT / PRUNE / PROMOTE /
 * DOC_REVISE proposals; nothing mutates memory until a human approves here
 * (2026-07-03 pollution incident → propose-only is a hard rule).
 */

import { useCallback, useEffect, useState } from "react";

type Status = "proposed" | "approved" | "rejected";

interface Proposal {
  id: number;
  action_type: "MERGE" | "CORRECT" | "PRUNE" | "PROMOTE" | "DOC_REVISE";
  target_ids: unknown[];
  proposal: Record<string, unknown>;
  rationale?: string | null;
  status: Status;
  proposer_meta?: Record<string, unknown> | null;
  created_at?: string | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
  commit_result?: Record<string, unknown> | null;
}

const TYPE_META: Record<Proposal["action_type"], { color: string; desc: string }> = {
  MERGE:      { color: "#0891b2", desc: "合併語意重複的記憶" },
  CORRECT:    { color: "#dc2626", desc: "改寫 draft correction 成乾淨教訓" },
  PRUNE:      { color: "#94a3b8", desc: "停用過時 / 無再用價值的記憶" },
  PROMOTE:    { color: "#7c3aed", desc: "蒸餾成 domain / procedure 長期知識" },
  DOC_REVISE: { color: "#047857", desc: "block 文件修訂草案（不直接改 doc）" },
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const j = await res.json();
  if (!res.ok || j?.ok === false) throw new Error(j?.error?.message ?? `HTTP ${res.status}`);
  return j.data as T;
}

type Section = "curation" | "monitor";

export default function SupervisorPage() {
  const [section, setSection] = useState<Section>("curation");
  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: "0 auto", fontFamily: "system-ui, sans-serif" }}>
      <header style={{ marginBottom: 14 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600 }}>Supervisor</h1>
        <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 13 }}>
          兩個 human-in-the-loop 佇列：<b>蒸餾提案</b>（Supervisor 治理記憶 — 核准前不會有任何變更）
          與 <b>改善請求</b>（Monitor 監控我們 agent 自身的健康指標 — 核准後取得可下給 Planner 的指令）。
        </p>
      </header>
      <div style={{ display: "flex", gap: 6, marginBottom: 18 }}>
        {([["curation", "蒸餾提案 (Curation)"], ["monitor", "改善請求 (Monitor)"]] as [Section, string][]).map(([s, label]) => (
          <button key={s} onClick={() => setSection(s)} style={{
            padding: "7px 16px", borderRadius: 6, fontSize: 13, cursor: "pointer", fontWeight: section === s ? 700 : 500,
            border: `1px solid ${section === s ? "#2563eb" : "#e2e8f0"}`,
            background: section === s ? "#eff6ff" : "#fff", color: section === s ? "#1d4ed8" : "#475569",
          }}>{label}</button>
        ))}
      </div>
      {section === "curation" ? <CurationSection/> : <MonitorSection/>}
    </div>
  );
}

function CurationSection() {
  const [tab, setTab] = useState<Status>("proposed");
  const [items, setItems] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (status: Status) => {
    setLoading(true); setError(null);
    try { setItems(await api<Proposal[]>(`/api/supervisor/proposals?status=${status}`)); }
    catch (e) { setError(String((e as Error).message || e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(tab); }, [tab, load]);

  const review = async (id: number, verb: "approve" | "reject") => {
    if (verb === "approve" && !confirm("核准後會實際套用這筆變更（寫入/停用記憶）。確定？")) return;
    setBusy(id);
    try { await api(`/api/supervisor/proposals/${id}/${verb}`, { method: "POST" }); await load(tab); }
    catch (e) { alert(String((e as Error).message || e)); }
    finally { setBusy(null); }
  };

  return (
    <div>
      <p style={{ margin: "0 0 12px", color: "#64748b", fontSize: 12.5 }}>
        MERGE 合併重複 · CORRECT 改寫草稿 · PRUNE 汰舊 · PROMOTE 蒸餾 domain/procedure ·
        DOC_REVISE 文件修訂草案。<b>核准前不會有任何變更。</b>
      </p>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e2e8f0", marginBottom: 16 }}>
        {(["proposed", "approved", "rejected"] as Status[]).map((s) => (
          <button key={s} onClick={() => setTab(s)} style={{
            padding: "9px 16px", border: "none", background: "none", cursor: "pointer",
            borderBottom: tab === s ? "2px solid #2563eb" : "2px solid transparent",
            color: tab === s ? "#1e293b" : "#64748b", fontWeight: tab === s ? 600 : 400, fontSize: 13.5,
          }}>
            {s === "proposed" ? "待審" : s === "approved" ? "已核准" : "已駁回"}
          </button>
        ))}
      </div>

      {error && <div style={{ color: "#dc2626", padding: 12 }}>{error}</div>}
      {loading ? <p style={{ color: "#94a3b8", padding: 24, textAlign: "center" }}>Loading…</p>
       : items.length === 0 ? (
        <div style={{ padding: "60px 28px", textAlign: "center", color: "#94a3b8", fontSize: 13 }}>
          {tab === "proposed"
            ? "目前沒有待審提案。到 EC2 跑 tools/supervisor_curate 產生一批。"
            : "無資料。"}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((p) => (
            <ProposalCard key={p.id} p={p} busy={busy === p.id}
              onApprove={() => review(p.id, "approve")}
              onReject={() => review(p.id, "reject")}/>
          ))}
        </div>
      )}
    </div>
  );
}

function ProposalCard({ p, busy, onApprove, onReject }: {
  p: Proposal; busy: boolean; onApprove: () => void; onReject: () => void;
}) {
  const meta = TYPE_META[p.action_type] ?? { color: "#475569", desc: "" };
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: "1px solid #e2e8f0", borderLeft: `3px solid ${meta.color}`, borderRadius: 6, background: "#fff" }}>
      <div style={{ padding: "12px 16px", display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontWeight: 700, color: meta.color, fontSize: 13 }}>{p.action_type}</span>
            <span style={{ fontSize: 11.5, color: "#94a3b8" }}>{meta.desc}</span>
            <span style={{ fontSize: 11, color: "#cbd5e1" }}>#{p.id}</span>
          </div>
          {p.rationale && (
            <div style={{ fontSize: 13, color: "#334155", marginBottom: 6 }}>{p.rationale}</div>
          )}
          <ProposalSummary p={p}/>
          <button onClick={() => setOpen((v) => !v)} style={{
            marginTop: 6, border: "none", background: "none", color: "#2563eb",
            fontSize: 12, cursor: "pointer", padding: 0,
          }}>{open ? "收合完整內容 ▲" : "看完整提案 JSON ▼"}</button>
          {open && (
            <pre style={{
              margin: "8px 0 0", background: "#0f172a", color: "#e2e8f0", padding: 12,
              borderRadius: 6, fontSize: 11.5, lineHeight: 1.5, overflowX: "auto",
              whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 320, overflowY: "auto",
            }}>{JSON.stringify({ proposal: p.proposal, target_ids: p.target_ids, proposer_meta: p.proposer_meta, commit_result: p.commit_result }, null, 2)}</pre>
          )}
          {p.status !== "proposed" && (
            <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 6 }}>
              {p.status === "approved" ? "已核准" : "已駁回"} · reviewer #{p.reviewed_by ?? "?"} · {p.reviewed_at ? new Date(p.reviewed_at).toLocaleString() : ""}
            </div>
          )}
        </div>
        {p.status === "proposed" && (
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            <button disabled={busy} onClick={onApprove} style={{
              padding: "6px 14px", borderRadius: 4, fontSize: 12.5, fontWeight: 600, cursor: "pointer",
              background: busy ? "#f1f5f9" : "#047857", color: busy ? "#94a3b8" : "#fff", border: "none",
            }}>{busy ? "…" : "核准"}</button>
            <button disabled={busy} onClick={onReject} style={{
              padding: "6px 14px", borderRadius: 4, fontSize: 12.5, cursor: "pointer",
              background: "#fff", color: "#dc2626", border: "1px solid #fecaca",
            }}>駁回</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Monitor section (Phase 6, option A: self-health) ─────────────────────

type MonitorStatus = "open" | "approved" | "dismissed";

interface MonitorRequest {
  id: number;
  kind: "DOC_GAP" | "DIVERGENCE" | "REPAIR_HANDOVER";
  subject: string;
  evidence: Record<string, unknown>;
  suggested_instruction?: string | null;
  status: MonitorStatus;
  created_at?: string | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
}

const KIND_META: Record<MonitorRequest["kind"], { color: string; label: string }> = {
  DOC_GAP:         { color: "#047857", label: "文件缺口" },
  DIVERGENCE:      { color: "#dc2626", label: "自評與 user 分歧" },
  REPAIR_HANDOVER: { color: "#b45309", label: "自我修復失敗" },
};

function MonitorSection() {
  const [tab, setTab] = useState<MonitorStatus>("open");
  const [items, setItems] = useState<MonitorRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (status: MonitorStatus) => {
    setLoading(true); setError(null);
    try { setItems(await api<MonitorRequest[]>(`/api/monitor/requests?status=${status}`)); }
    catch (e) { setError(String((e as Error).message || e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(tab); }, [tab, load]);

  const scan = async () => {
    setScanning(true);
    try {
      const r = await api<{ created: number; deduped: number }>("/api/monitor/scan", { method: "POST" });
      alert(`掃描完成：新增 ${r.created} 筆請求（去重略過 ${r.deduped}）`);
      await load(tab);
    } catch (e) { alert(String((e as Error).message || e)); }
    finally { setScanning(false); }
  };

  const review = async (id: number, verb: "approve" | "dismiss") => {
    setBusy(id);
    try { await api(`/api/monitor/requests/${id}/${verb}`, { method: "POST" }); await load(tab); }
    catch (e) { alert(String((e as Error).message || e)); }
    finally { setBusy(null); }
  };

  return (
    <div>
      <p style={{ margin: "0 0 12px", color: "#64748b", fontSize: 12.5 }}>
        Monitor 用<b>確定性指標</b>（不經 LLM）掃描我們 agent 自己的健康：block 文件缺口 /
        divergence / repair handover。核准後取得建議指令，複製到 Builder 下給 Planner。
      </p>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e2e8f0", marginBottom: 16, alignItems: "center" }}>
        {(["open", "approved", "dismissed"] as MonitorStatus[]).map((s) => (
          <button key={s} onClick={() => setTab(s)} style={{
            padding: "9px 16px", border: "none", background: "none", cursor: "pointer",
            borderBottom: tab === s ? "2px solid #2563eb" : "2px solid transparent",
            color: tab === s ? "#1e293b" : "#64748b", fontWeight: tab === s ? 600 : 400, fontSize: 13.5,
          }}>
            {s === "open" ? "待審" : s === "approved" ? "已核准" : "已忽略"}
          </button>
        ))}
        <span style={{ flex: 1 }}/>
        <button onClick={scan} disabled={scanning} style={{
          padding: "5px 14px", borderRadius: 4, fontSize: 12.5, cursor: "pointer", marginBottom: 4,
          background: scanning ? "#f1f5f9" : "#2563eb", color: scanning ? "#94a3b8" : "#fff", border: "none",
        }}>{scanning ? "掃描中…" : "立即掃描"}</button>
      </div>

      {error && <div style={{ color: "#dc2626", padding: 12 }}>{error}</div>}
      {loading ? <p style={{ color: "#94a3b8", padding: 24, textAlign: "center" }}>Loading…</p>
       : items.length === 0 ? (
        <div style={{ padding: "60px 28px", textAlign: "center", color: "#94a3b8", fontSize: 13 }}>
          {tab === "open" ? "沒有待審請求 — 系統健康，或按「立即掃描」跑一次檢查。" : "無資料。"}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((r) => {
            const meta = KIND_META[r.kind] ?? { color: "#475569", label: r.kind };
            return (
              <div key={r.id} style={{ border: "1px solid #e2e8f0", borderLeft: `3px solid ${meta.color}`, borderRadius: 6, background: "#fff", padding: "12px 16px" }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, color: meta.color, fontSize: 13 }}>{r.kind}</span>
                  <span style={{ fontSize: 11.5, color: "#94a3b8" }}>{meta.label}</span>
                  <span style={{ fontFamily: "monospace", fontSize: 12, color: "#334155" }}>{r.subject}</span>
                  <span style={{ fontSize: 11, color: "#cbd5e1" }}>#{r.id}</span>
                  <span style={{ flex: 1 }}/>
                  {r.status === "open" && (
                    <span style={{ display: "flex", gap: 6 }}>
                      <button disabled={busy === r.id} onClick={() => review(r.id, "approve")} style={{
                        padding: "5px 12px", borderRadius: 4, fontSize: 12, fontWeight: 600, cursor: "pointer",
                        background: "#047857", color: "#fff", border: "none",
                      }}>核准</button>
                      <button disabled={busy === r.id} onClick={() => review(r.id, "dismiss")} style={{
                        padding: "5px 12px", borderRadius: 4, fontSize: 12, cursor: "pointer",
                        background: "#fff", color: "#64748b", border: "1px solid #e2e8f0",
                      }}>忽略</button>
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: "#64748b", marginBottom: 6 }}>
                  量測值：{JSON.stringify(r.evidence)}
                </div>
                {r.suggested_instruction && (
                  <div style={{ fontSize: 12.5, color: "#334155", background: "#f8fafc", border: "1px solid #f1f5f9", borderRadius: 4, padding: "8px 10px" }}>
                    <b>建議指令：</b>{r.suggested_instruction}
                    {r.status === "approved" && (
                      <button onClick={() => { void navigator.clipboard.writeText(r.suggested_instruction ?? ""); }} style={{
                        marginLeft: 8, padding: "2px 8px", borderRadius: 3, fontSize: 11, cursor: "pointer",
                        border: "1px solid #cbd5e1", background: "#fff", color: "#475569",
                      }}>複製，拿去下給 Planner</button>
                    )}
                  </div>
                )}
                {r.status !== "open" && (
                  <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 6 }}>
                    {r.status === "approved" ? "已核准" : "已忽略"} · reviewer #{r.reviewed_by ?? "?"} · {r.reviewed_at ? new Date(r.reviewed_at).toLocaleString() : ""}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Type-aware one-line summary so the reviewer rarely needs the raw JSON. */
function ProposalSummary({ p }: { p: Proposal }) {
  const b = p.proposal ?? {};
  const s = (v: unknown) => (v == null ? "" : String(v));
  let text = "";
  if (p.action_type === "MERGE") text = `保留 #${s(b.keep_id)}，停用 ${JSON.stringify(b.remove_ids)}${b.merged_body ? "，並更新合併後內文" : ""}`;
  else if (p.action_type === "CORRECT") text = `#${s(b.target_id)} → ${s(b.new_title || "（標題不變）")}${b.promote ? " · 核准即轉正 (active)" : " · 維持 draft"}`;
  else if (p.action_type === "PRUNE") text = `停用 ${JSON.stringify(b.target_ids)}`;
  else if (p.action_type === "PROMOTE") text = `新增 ${s(b.memo_class)}:「${s(b.title)}」`;
  else if (p.action_type === "DOC_REVISE") text = `${s(b.block_id)} 的文件修訂草案（${(b.memo_ids as unknown[] | undefined)?.length ?? 0} 筆備忘）`;
  return <div style={{ fontSize: 12.5, color: "#475569" }}>{text}</div>;
}
