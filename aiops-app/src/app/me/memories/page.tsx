"use client";

import { useEffect, useState } from "react";

interface RagMemory {
  id: number;
  content: string;
  source: string | null;
  task_type: string | null;
  data_subject: string | null;
  tool_name: string | null;
  created_at: string;
}

interface ExperienceMemory {
  id: number;
  intent_summary: string;
  abstract_action: string;
  confidence_score: number;
  use_count: number;
  success_count: number;
  fail_count: number;
  status: string;
  source: string;
  created_at: string;
  last_used_at: string | null;
}

export default function MyMemoriesPage() {
  const [rag, setRag] = useState<RagMemory[]>([]);
  const [exp, setExp] = useState<ExperienceMemory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/me/memories", { cache: "no-store" });
        const body = await res.json();
        setRag(body.memories ?? []);
        setExp(body.experience ?? []);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div style={{ padding: 24, maxWidth: 1200, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "#0f172a" }}>🧠 我的 Agent 記憶</h1>
      <p style={{ fontSize: 13, color: "#64748b", marginTop: 4, marginBottom: 20 }}>
        你與 Agent 對話累積的記憶——RAG 記憶 + 經驗庫。只顯示你自己的資料。
        IT_ADMIN 可在 <a href="/admin/memories" style={{ color: "#1e40af" }}>/admin/memories</a> 看全站。
      </p>

      {error && (
        <div style={{ padding: "8px 12px", borderRadius: 6, fontSize: 13, marginBottom: 12,
                      background: "#fef2f2", color: "#991b1b", border: "1px solid #fca5a5" }}>
          {error}
        </div>
      )}

      {loading ? (
        <div style={{ color: "#94a3b8" }}>載入中…</div>
      ) : (
        <>
          <h2 style={sectionTitle}>📖 RAG 記憶（對話片段）· {rag.length} 筆</h2>
          {rag.length === 0 ? (
            <Empty text="尚無 RAG 記憶（與 Agent 對話會自動累積）" />
          ) : (
            <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden" }}>
              <table style={tableStyle}>
                <thead><tr style={theadRow}>
                  <th style={th}>ID</th><th style={th}>內容</th><th style={th}>Source</th>
                  <th style={th}>Task / Subject</th><th style={th}>Created</th>
                </tr></thead>
                <tbody>
                  {rag.map((m, i) => (
                    <tr key={m.id} style={{ background: i % 2 ? "#fafafa" : "#fff", borderBottom: "1px solid #f0f0f0" }}>
                      <td style={td}>{m.id}</td>
                      <td style={{ ...td, maxWidth: 500 }}>
                        <div style={{ whiteSpace: "pre-wrap", fontSize: 12, color: "#1a202c" }}>
                          {m.content.length > 300 ? m.content.slice(0, 300) + "…" : m.content}
                        </div>
                      </td>
                      <td style={td}>{m.source ?? "—"}</td>
                      <td style={{ ...td, fontSize: 11, color: "#64748b" }}>
                        {[m.task_type, m.data_subject, m.tool_name].filter(Boolean).join(" / ") || "—"}
                      </td>
                      <td style={{ ...td, fontSize: 11, color: "#94a3b8" }}>
                        {new Date(m.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 style={sectionTitle}>💡 經驗記憶（成功模式）· {exp.length} 筆</h2>
          {exp.length === 0 ? (
            <Empty text="尚無經驗記憶（Agent 累積成功 action 的抽象模式）" />
          ) : (
            <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden" }}>
              <table style={tableStyle}>
                <thead><tr style={theadRow}>
                  <th style={th}>ID</th><th style={th}>意圖摘要</th><th style={th}>抽象 Action</th>
                  <th style={th}>分數</th><th style={th}>次數 (成/敗)</th><th style={th}>狀態</th>
                </tr></thead>
                <tbody>
                  {exp.map((e, i) => (
                    <tr key={e.id} style={{ background: i % 2 ? "#fafafa" : "#fff", borderBottom: "1px solid #f0f0f0" }}>
                      <td style={td}>{e.id}</td>
                      <td style={{ ...td, maxWidth: 300, fontWeight: 600 }}>{e.intent_summary}</td>
                      <td style={{ ...td, maxWidth: 400, fontSize: 11, color: "#475569" }}>
                        <div style={{ whiteSpace: "pre-wrap" }}>
                          {e.abstract_action.length > 200 ? e.abstract_action.slice(0, 200) + "…" : e.abstract_action}
                        </div>
                      </td>
                      <td style={td}>{e.confidence_score}/10</td>
                      <td style={td}>
                        {e.use_count} ({e.success_count}/{e.fail_count})
                      </td>
                      <td style={td}>
                        <span style={{
                          padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600,
                          background: e.status === "ACTIVE" ? "#dcfce7" : "#fee2e2",
                          color: e.status === "ACTIVE" ? "#166534" : "#991b1b",
                        }}>{e.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div style={{
      padding: 24, textAlign: "center", fontSize: 13, color: "#94a3b8",
      background: "#fafafa", border: "1px dashed #e2e8f0", borderRadius: 8,
    }}>{text}</div>
  );
}

const sectionTitle: React.CSSProperties = {
  fontSize: 14, fontWeight: 700, color: "#374151",
  marginTop: 24, marginBottom: 10,
};
const tableStyle: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const theadRow: React.CSSProperties = { background: "#f8fafc", borderBottom: "1px solid #e2e8f0" };
const th: React.CSSProperties = {
  padding: "8px 12px", textAlign: "left", fontSize: 11,
  fontWeight: 700, color: "#4a5568", textTransform: "uppercase", letterSpacing: "0.3px",
};
const td: React.CSSProperties = { padding: "8px 12px", verticalAlign: "top" };
