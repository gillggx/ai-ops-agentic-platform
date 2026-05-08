"use client";

/**
 * Phase 9-C — minimal personal-rules management page.
 * List own rules, pause/unpause, delete. Editing schedule_cron / template
 * is shipped; full pipeline editing is intentionally NOT here (re-create
 * via chat is faster + safer than a tiny inline canvas).
 */

import { useCallback, useEffect, useState } from "react";

interface Rule {
  id: number;
  name: string;
  description: string;
  kind: string;
  scheduleCron: string | null;
  pipelineId: number | null;
  isActive: boolean;
  notificationChannels: string | null;
  notificationTemplate: string | null;
  lastDispatchedAt: string | null;
  createdAt: string;
  createdBy: number | null;
}

const KIND_LABEL: Record<string, string> = {
  personal_briefing: "每日 briefing",
  weekly_report: "每週報告",
  saved_query: "儲存查詢",
  watch_rule: "條件觸發",
};

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/rules", { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message || `HTTP ${res.status}`);
      setRules(body.data ?? body);
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
      body: JSON.stringify({ isActive: !rule.isActive }),
    });
    fetchRules();
  };

  const deleteRule = async (rule: Rule) => {
    if (!confirm(`確定刪除規則「${rule.name}」？`)) return;
    await fetch(`/api/rules/${rule.id}`, { method: "DELETE" });
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
              {rules.map((r) => (
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
                    {r.scheduleCron ?? "— manual —"}
                  </td>
                  <td style={{ ...tdStyle, fontSize: 11, color: "#64748b" }}>
                    {r.lastDispatchedAt
                      ? new Date(r.lastDispatchedAt).toLocaleString("zh-TW", { hour12: false })
                      : "從未"}
                  </td>
                  <td style={tdStyle}>
                    <span style={{
                      ...stateBadge,
                      background: r.isActive ? "#dcfce7" : "#fef3c7",
                      color: r.isActive ? "#166534" : "#92400e",
                    }}>
                      {r.isActive ? "● 啟用中" : "⏸ 已暫停"}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button onClick={() => togglePause(r)} style={btnStyle}>
                        {r.isActive ? "暫停" : "啟用"}
                      </button>
                      <button onClick={() => deleteRule(r)} style={{ ...btnStyle, color: "#dc2626", borderColor: "#fecaca" }}>
                        刪除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
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
