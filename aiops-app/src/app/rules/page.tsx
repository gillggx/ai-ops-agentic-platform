"use client";

/**
 * Phase 9-C — minimal personal-rules management page.
 * List own rules, pause/unpause, delete. Editing schedule_cron / template
 * is shipped; full pipeline editing is intentionally NOT here (re-create
 * via chat is faster + safer than a tiny inline canvas).
 */

import { useCallback, useEffect, useState } from "react";

/** Java backend uses Jackson SNAKE_CASE, so all DTO fields arrive as snake_case. */
interface Rule {
  id: number;
  name: string;
  description: string;
  kind: string;
  schedule_cron: string | null;
  pipeline_id: number | null;
  is_active: boolean;
  notification_channels: string | null;
  notification_template: string | null;
  last_dispatched_at: string | null;
  created_at: string;
  created_by: number | null;
}

const KIND_LABEL: Record<string, string> = {
  personal_briefing: "每日 briefing",
  weekly_report: "每週報告",
  saved_query: "儲存查詢",
  watch_rule: "條件觸發",
};

interface PipelineSummary {
  id: number;
  name: string;
  blockNames: string[];   // ordered block_id list, for "what does this rule do"
  lastRunPayload: string | null;  // rendered notification body from most recent fire
}

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [pipelineMap, setPipelineMap] = useState<Map<number, PipelineSummary>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editCron, setEditCron] = useState("");
  const [editTemplate, setEditTemplate] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const fetchRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/rules", { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message || `HTTP ${res.status}`);
      const list: Rule[] = body.data ?? body;
      setRules(list);

      // Pull each unique pipeline for display ("what does this rule do").
      // Resolved in parallel; missing pipelines fall back to "(unavailable)".
      const ids = Array.from(new Set(list.map(r => r.pipeline_id).filter((x): x is number => x != null)));
      const pairs = await Promise.all(ids.map(async (id) => {
        try {
          const pr = await fetch(`/api/admin/pipelines/${id}`, { cache: "no-store" });
          if (!pr.ok) return null;
          const pd = await pr.json();
          const pj = typeof pd.pipeline_json === "string"
            ? JSON.parse(pd.pipeline_json)
            : (pd.pipeline_json ?? {});
          const blockNames: string[] = Array.isArray(pj.nodes)
            ? pj.nodes.map((n: { block_id?: string }) => String(n.block_id ?? "?"))
            : [];
          // Try to grab the most recent inbox payload for this rule via /api/notifications/inbox
          // — done once per page load below in a separate fetch — we don't loop here.
          return [id, { id, name: pd.name ?? `pipeline ${id}`, blockNames, lastRunPayload: null }] as const;
        } catch {
          return null;
        }
      }));
      const m = new Map<number, PipelineSummary>();
      for (const p of pairs) if (p) m.set(p[0], p[1]);

      // One pass through inbox to attach the latest payload per rule_id.
      try {
        const ir = await fetch("/api/notifications/inbox?limit=20", { cache: "no-store" });
        const ib = await ir.json();
        const items = (ib.data?.items ?? ib.items ?? []) as Array<{ rule_id: number | null; payload: string }>;
        const latestByRule = new Map<number, string>();
        for (const it of items) {
          if (it.rule_id != null && !latestByRule.has(it.rule_id)) {
            latestByRule.set(it.rule_id, it.payload);
          }
        }
        for (const r of list) {
          if (r.pipeline_id != null && r.id != null) {
            const summary = m.get(r.pipeline_id);
            if (summary) {
              const raw = latestByRule.get(r.id);
              if (raw) {
                try {
                  const j = JSON.parse(raw);
                  summary.lastRunPayload = String(j.body ?? raw).slice(0, 200);
                } catch {
                  summary.lastRunPayload = raw.slice(0, 200);
                }
              }
            }
          }
        }
      } catch { /* best-effort */ }

      setPipelineMap(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRules(); }, [fetchRules]);

  const togglePause = async (rule: Rule) => {
    await fetch(`/api/rules/${rule.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !rule.is_active }),
    });
    fetchRules();
  };

  const deleteRule = async (rule: Rule) => {
    if (!confirm(`確定刪除規則「${rule.name}」？`)) return;
    await fetch(`/api/rules/${rule.id}`, { method: "DELETE" });
    fetchRules();
  };

  const startEdit = (rule: Rule) => {
    setEditingId(rule.id);
    setEditCron(rule.schedule_cron ?? "");
    setEditTemplate(rule.notification_template ?? "");
  };

  const saveEdit = async (rule: Rule) => {
    const body: Record<string, unknown> = {};
    if (editCron !== (rule.schedule_cron ?? "")) body.schedule_cron = editCron;
    if (editTemplate !== (rule.notification_template ?? "")) body.notification_template = editTemplate;
    if (Object.keys(body).length === 0) {
      setEditingId(null);
      return;
    }
    const res = await fetch(`/api/rules/${rule.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(`儲存失敗：${err?.error?.message ?? res.status}`);
      return;
    }
    setEditingId(null);
    fetchRules();
  };

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1100 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 6, color: "#0f172a" }}>
        🔔 我的規則
      </h1>
      <p style={{ color: "#64748b", fontSize: 13, marginBottom: 24 }}>
        Phase 9 · 由 chat agent 建立的個人排程規則 — 每次觸發會推到右上角鈴鐺。
        要新增規則請到 chat panel 對 agent 說「以後每週一早 8 點...」。
      </p>

      {loading && <div style={{ color: "#94a3b8" }}>讀取中…</div>}
      {error && (
        <div style={{
          background: "#fef2f2", border: "1px solid #fecaca",
          padding: "12px 16px", borderRadius: 6, color: "#991b1b", marginBottom: 16,
        }}>
          ⚠ 讀取失敗：{error}
        </div>
      )}

      {!loading && rules.length === 0 && !error && (
        <div style={{
          padding: "60px 20px", textAlign: "center",
          background: "#f8fafc", borderRadius: 8,
          color: "#64748b", fontSize: 14,
        }}>
          目前沒有規則 — 去 chat panel 跟 agent 說想要排程什麼分析吧
        </div>
      )}

      {rules.length > 0 && (
        <div style={{
          background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8,
          overflow: "hidden",
        }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                <th style={thStyle}>名稱</th>
                <th style={thStyle}>類型</th>
                <th style={thStyle}>排程</th>
                <th style={thStyle}>上次推播</th>
                <th style={thStyle}>狀態</th>
                <th style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {rules.flatMap((r) => [
                <tr key={r.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={tdStyle}>
                    <div style={{ fontWeight: 600, color: "#0f172a" }}>{r.name}</div>
                    {r.description && (
                      <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{r.description}</div>
                    )}
                  </td>
                  <td style={tdStyle}>
                    <span style={kindBadge}>{KIND_LABEL[r.kind] ?? r.kind}</span>
                  </td>
                  <td style={{ ...tdStyle, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11 }}>
                    {r.schedule_cron ?? "— manual —"}
                  </td>
                  <td style={{ ...tdStyle, fontSize: 11, color: "#64748b" }}>
                    {r.last_dispatched_at
                      ? new Date(r.last_dispatched_at).toLocaleString("zh-TW", { hour12: false })
                      : "從未"}
                  </td>
                  <td style={tdStyle}>
                    <span style={{
                      ...stateBadge,
                      background: r.is_active ? "#dcfce7" : "#fef3c7",
                      color: r.is_active ? "#166534" : "#92400e",
                    }}>
                      {r.is_active ? "● 啟用中" : "⏸ 已暫停"}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <button onClick={() => setExpandedId(expandedId === r.id ? null : r.id)} style={btnStyle}>
                        {expandedId === r.id ? "收起" : "細節"}
                      </button>
                      <button onClick={() => startEdit(r)} style={btnStyle}>
                        改排程
                      </button>
                      {r.pipeline_id != null && (
                        <a
                          href={`/admin/pipeline-builder/${r.pipeline_id}`}
                          style={{ ...btnStyle, textDecoration: "none", display: "inline-block" }}
                        >
                          改 pipeline
                        </a>
                      )}
                      <button onClick={() => togglePause(r)} style={btnStyle}>
                        {r.is_active ? "暫停" : "啟用"}
                      </button>
                      <button onClick={() => deleteRule(r)} style={{ ...btnStyle, color: "#dc2626", borderColor: "#fecaca" }}>
                        刪除
                      </button>
                    </div>
                  </td>
                </tr>,
                expandedId === r.id && (() => {
                  const ps = r.pipeline_id != null ? pipelineMap.get(r.pipeline_id) : undefined;
                  return (
                    <tr key={`detail-${r.id}`} style={{ background: "#f8fafc" }}>
                      <td colSpan={6} style={{ padding: "14px 18px" }}>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                          <div>
                            <div style={{ fontSize: 11, fontWeight: 600, color: "#475569", letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 4 }}>
                              這條規則執行什麼 pipeline
                            </div>
                            <div style={{ fontSize: 12, color: "#334155", marginBottom: 6 }}>
                              {ps ? <><b>{ps.name}</b> <span style={{ color: "#94a3b8" }}>(id={ps.id})</span></> : "(pipeline 不可讀)"}
                            </div>
                            {ps && ps.blockNames.length > 0 && (
                              <div style={{
                                fontFamily: "ui-monospace, Menlo, monospace",
                                fontSize: 11, color: "#475569",
                                lineHeight: 1.7,
                              }}>
                                {ps.blockNames.map((n, i) => (
                                  <span key={i}>
                                    {i > 0 && <span style={{ color: "#cbd5e0" }}> → </span>}
                                    <span style={{
                                      background: "#e0f2fe", color: "#075985",
                                      padding: "1px 6px", borderRadius: 3,
                                    }}>{n}</span>
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                          <div>
                            <div style={{ fontSize: 11, fontWeight: 600, color: "#475569", letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 4 }}>
                              上次推到鈴鐺的訊息
                            </div>
                            <div style={{
                              background: "#fff",
                              border: "1px solid #e2e8f0",
                              borderRadius: 6,
                              padding: "10px 12px",
                              fontSize: 12,
                              color: "#1f2937",
                              minHeight: 40,
                              whiteSpace: "pre-wrap",
                            }}>
                              {ps?.lastRunPayload ?? <span style={{ color: "#94a3b8" }}>從未推播 — 等下次排程觸發或手動 trigger</span>}
                            </div>
                            <div style={{ fontSize: 11, color: "#64748b", marginTop: 6 }}>
                              <b>模板：</b><span style={{ fontFamily: "ui-monospace, Menlo, monospace", color: "#475569" }}>
                                {r.notification_template ?? "(空 — 用 result_summary 當 body)"}
                              </span>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })(),
              ].filter(Boolean))}
              {editingId !== null && (() => {
                const r = rules.find(x => x.id === editingId);
                if (!r) return null;
                return (
                  <tr key={`edit-${editingId}`} style={{ background: "#fffbeb", borderTop: "1px solid #fcd34d" }}>
                    <td colSpan={6} style={{ padding: "16px 18px" }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#78350f", marginBottom: 10 }}>
                        ✏️ 編輯規則：{r.name}
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 12, marginBottom: 10 }}>
                        <div>
                          <label style={{ fontSize: 10, color: "#92400e", letterSpacing: "0.06em", fontWeight: 600, textTransform: "uppercase" }}>排程 cron (5-field)</label>
                          <input
                            value={editCron}
                            onChange={(e) => setEditCron(e.target.value)}
                            placeholder="0 8 * * 1"
                            style={{ width: "100%", padding: "5px 8px", border: "1px solid #fcd34d", borderRadius: 4, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12 }}
                          />
                        </div>
                        <div>
                          <label style={{ fontSize: 10, color: "#92400e", letterSpacing: "0.06em", fontWeight: 600, textTransform: "uppercase" }}>推播訊息模板</label>
                          <input
                            value={editTemplate}
                            onChange={(e) => setEditTemplate(e.target.value)}
                            placeholder="例：上週 OOC top-5: {top_tools}"
                            style={{ width: "100%", padding: "5px 8px", border: "1px solid #fcd34d", borderRadius: 4, fontSize: 12 }}
                          />
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                        <button onClick={() => setEditingId(null)} style={btnStyle}>取消</button>
                        <button onClick={() => saveEdit(r)} style={{ ...btnStyle, background: "#3b82f6", color: "#fff", borderColor: "#3b82f6" }}>儲存</button>
                      </div>
                    </td>
                  </tr>
                );
              })()}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 14px",
  fontSize: 11,
  fontWeight: 600,
  color: "#475569",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
};

const tdStyle: React.CSSProperties = {
  padding: "12px 14px",
  verticalAlign: "top",
};

const kindBadge: React.CSSProperties = {
  background: "#e0f2fe",
  color: "#075985",
  padding: "2px 8px",
  borderRadius: 4,
  fontSize: 11,
  fontWeight: 600,
};

const stateBadge: React.CSSProperties = {
  padding: "2px 8px",
  borderRadius: 10,
  fontSize: 11,
  fontWeight: 600,
};

const btnStyle: React.CSSProperties = {
  padding: "4px 10px",
  background: "#fff",
  border: "1px solid #e2e8f0",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 11,
  color: "#475569",
};
