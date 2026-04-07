"use client";

import { useCallback, useEffect, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface MemoryRow {
  id: number;
  user_id: number;
  // Experience memory fields
  intent_summary?: string;
  abstract_action?: string;
  confidence_score?: number;
  use_count?: number;
  success_count?: number;
  fail_count?: number;
  status?: "ACTIVE" | "STALE" | "HUMAN_REJECTED";
  source_session_id?: string | null;
  last_used_at?: string | null;
  updated_at?: string;
  // Legacy RAG memory fields
  content?: string;
  task_type?: string;
  tool_name?: string;
  // Shared
  source: string;
  created_at: string;
  _memory_type?: "rag" | "experience";
}

type StatusFilter = "all" | "ACTIVE" | "STALE" | "HUMAN_REJECTED";

// ── Styles ────────────────────────────────────────────────────────────────────

const S = {
  page: { maxWidth: 1200 },
  header: {
    marginBottom: 24,
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-end",
  } as const,
  h1: { margin: 0, fontSize: 22, fontWeight: 700, color: "#1a202c" },
  sub: { margin: "4px 0 0", fontSize: 13, color: "#718096" },
  tabs: {
    display: "flex",
    gap: 4,
    marginBottom: 16,
    borderBottom: "1px solid #e2e8f0",
  } as const,
  tab: (active: boolean) => ({
    padding: "8px 16px",
    border: "none",
    background: "none",
    fontSize: 13,
    color: active ? "#2b6cb0" : "#718096",
    fontWeight: active ? 600 : 500,
    borderBottom: active ? "2px solid #2b6cb0" : "2px solid transparent",
    cursor: "pointer",
  }),
  table: {
    background: "#fff",
    borderRadius: 10,
    border: "1px solid #e2e8f0",
    overflow: "hidden",
  } as const,
};

// ── Health badge ──────────────────────────────────────────────────────────────

function HealthBadge({ score, status }: { score: number; status: string }) {
  if (status === "HUMAN_REJECTED") {
    return (
      <span style={{
        background: "#fed7d7", color: "#742a2a", fontSize: 11,
        fontWeight: 600, padding: "2px 8px", borderRadius: 10,
      }}>
        🚫 REJECTED
      </span>
    );
  }
  if (status === "STALE") {
    return (
      <span style={{
        background: "#fefcbf", color: "#744210", fontSize: 11,
        fontWeight: 600, padding: "2px 8px", borderRadius: 10,
      }}>
        🟡 STALE
      </span>
    );
  }
  // ACTIVE — colour by score
  const color = score >= 7 ? ["#c6f6d5", "#22543d", "🟢"]
              : score >= 4 ? ["#bee3f8", "#2c5282", "🔵"]
              : ["#feebc8", "#744210", "🟠"];
  return (
    <span style={{
      background: color[0], color: color[1], fontSize: 11,
      fontWeight: 600, padding: "2px 8px", borderRadius: 10,
    }}>
      {color[2]} {score}/10
    </span>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MemoriesPage() {
  const [rows, setRows] = useState<MemoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = filter === "all"
        ? "/api/admin/memories"
        : `/api/admin/memories?status=${filter}`;
      const res = await fetch(url, { cache: "no-store" });
      const data = await res.json();
      setRows(Array.isArray(data) ? data : []);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleReject(id: number) {
    if (!confirm("確定要標記此記憶為錯誤？此動作無法復原。")) return;
    await fetch(`/api/admin/memories/${id}/reject`, { method: "POST" });
    await load();
  }

  async function handleDelete(id: number) {
    if (!confirm("確定要永久刪除此記憶？通常建議使用「標記錯誤」而非刪除。")) return;
    await fetch(`/api/admin/memories/${id}`, { method: "DELETE" });
    await load();
  }

  const counts = {
    all: rows.length,
    ACTIVE: rows.filter(r => r.status === "ACTIVE").length,
    STALE: rows.filter(r => r.status === "STALE").length,
    HUMAN_REJECTED: rows.filter(r => r.status === "HUMAN_REJECTED").length,
  };

  return (
    <div style={S.page}>
      <div style={S.header}>
        <div>
          <h1 style={S.h1}>🧠 Agent Experience Memories</h1>
          <p style={S.sub}>
            Agent 的反思型記憶：每次成功任務後自動萃取為 (意圖, 策略) 對。
            <br />
            低信心記憶會自動 STALE；發現錯誤的記憶可手動標記為 REJECTED（終身封存）。
          </p>
        </div>
      </div>

      {/* Status filter tabs */}
      <div style={S.tabs}>
        {([
          ["all", `全部 (${counts.all})`],
          ["ACTIVE", `🟢 Active (${counts.ACTIVE})`],
          ["STALE", `🟡 Stale (${counts.STALE})`],
          ["HUMAN_REJECTED", `🚫 Rejected (${counts.HUMAN_REJECTED})`],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            style={S.tab(filter === key)}
            onClick={() => setFilter(key as StatusFilter)}
          >
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ padding: 48, textAlign: "center", color: "#718096" }}>
          載入中…
        </div>
      ) : rows.length === 0 ? (
        <div style={{
          background: "#fff", borderRadius: 10, padding: 56,
          textAlign: "center", border: "1px solid #e2e8f0",
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🧠</div>
          <p style={{ color: "#718096", fontSize: 15, margin: 0 }}>
            尚無記憶（或已全部被過濾）
          </p>
          <p style={{ color: "#a0aec0", fontSize: 12, marginTop: 8 }}>
            Agent 會在每次成功完成多步驟任務後自動寫入反思型記憶
          </p>
        </div>
      ) : (
        <div style={S.table}>
          <table style={{
            width: "100%", borderCollapse: "collapse", fontSize: 13,
          }}>
            <thead>
              <tr style={{
                background: "#f7f8fc",
                borderBottom: "1px solid #e2e8f0",
              }}>
                {[
                  "ID", "意圖 / 策略", "狀態", "使用", "成功/失敗", "最後使用", "動作",
                ].map(h => (
                  <th key={h} style={{
                    padding: "10px 16px", textAlign: "left", fontSize: 11,
                    fontWeight: 600, color: "#718096",
                    textTransform: "uppercase", letterSpacing: "0.4px",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => {
                const isLegacy = m._memory_type === "rag";
                const title = isLegacy
                  ? (m.content ?? "").slice(0, 80)
                  : (m.intent_summary ?? "");
                const detail = isLegacy
                  ? (m.content ?? "")
                  : (m.abstract_action ?? "");
                return (
                <tr key={`${m._memory_type}-${m.id}`} style={{ borderBottom: "1px solid #f7f8fc" }}>
                  <td style={{ padding: "12px 16px", color: "#a0aec0", fontFamily: "monospace" }}>
                    #{m.id}
                    {isLegacy && (
                      <div style={{ fontSize: 9, color: "#a0aec0", marginTop: 2 }}>RAG</div>
                    )}
                  </td>
                  <td style={{ padding: "12px 16px", maxWidth: 600 }}>
                    <div style={{ fontWeight: 600, color: "#1a202c", marginBottom: 4 }}>
                      {title}
                    </div>
                    <div style={{ fontSize: 12, color: "#4a5568", lineHeight: 1.4 }}>
                      {detail.length > 200 ? detail.slice(0, 200) + "…" : detail}
                    </div>
                    {isLegacy && m.tool_name && (
                      <div style={{ fontSize: 11, color: "#718096", marginTop: 2 }}>
                        Tool: {m.tool_name}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    {isLegacy ? (
                      <span style={{ fontSize: 11, color: "#718096", background: "#f7fafc", padding: "2px 8px", borderRadius: 10 }}>
                        {m.source}
                      </span>
                    ) : (
                      <HealthBadge score={m.confidence_score ?? 5} status={m.status ?? "ACTIVE"} />
                    )}
                  </td>
                  <td style={{ padding: "12px 16px", color: "#4a5568" }}>
                    {isLegacy ? "—" : (m.use_count ?? 0)}
                  </td>
                  <td style={{ padding: "12px 16px", fontSize: 12 }}>
                    {isLegacy ? "—" : (
                      <>
                        <span style={{ color: "#38a169" }}>✓{m.success_count ?? 0}</span>
                        {" / "}
                        <span style={{ color: "#e53e3e" }}>✗{m.fail_count ?? 0}</span>
                      </>
                    )}
                  </td>
                  <td style={{ padding: "12px 16px", fontSize: 12, color: "#718096" }}>
                    {(m.last_used_at || m.created_at)
                      ? new Date(m.last_used_at ?? m.created_at).toLocaleString("zh-TW", {
                          month: "short", day: "numeric",
                          hour: "2-digit", minute: "2-digit",
                        })
                      : "—"}
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <button
                      onClick={() => handleDelete(m.id)}
                      style={{
                        padding: "4px 10px", fontSize: 11,
                        border: "1px solid #cbd5e0", background: "#fff",
                        color: "#4a5568", borderRadius: 5, cursor: "pointer",
                      }}
                    >
                      刪除
                    </button>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
