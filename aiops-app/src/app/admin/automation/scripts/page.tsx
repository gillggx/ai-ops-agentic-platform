"use client";

import { useEffect, useState, useCallback } from "react";

// ── Types ────────────────────────────────────────────────────────────────────

interface ScriptVersion {
  id: number;
  skill_id: number;
  version: number;
  status: "draft" | "approved" | "active" | "deprecated";
  code: string;
  change_note: string | null;
  reviewed_by: string | null;
  approved_at: string | null;
  generated_at: string;
}

// ── API helpers ───────────────────────────────────────────────────────────────

const BASE = "/api/admin/automation";

async function fetchPending(): Promise<ScriptVersion[]> {
  const r = await fetch(`${BASE}/script-registry/pending`);
  const d = await r.json();
  return d.data ?? d ?? [];
}

async function approveVersion(versionId: number): Promise<void> {
  await fetch(`${BASE}/script-registry/versions/${versionId}/approve`, { method: "POST" });
}

async function testRun(skillId: number, versionId: number): Promise<object> {
  const r = await fetch(`${BASE}/script-registry/skills/${skillId}/test-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_context: { event_type: "manual", eventTime: new Date().toISOString(), severity: "info", payload: {} },
      version: versionId,
    }),
  });
  const d = await r.json();
  return d.data ?? d;
}

// ── Sub-components ────────────────────────────────────────────────────────────

const statusColors: Record<string, { bg: string; color: string }> = {
  draft:      { bg: "#fef3c7", color: "#92400e" },
  approved:   { bg: "#d1fae5", color: "#065f46" },
  active:     { bg: "#dbeafe", color: "#1e40af" },
  deprecated: { bg: "#f3f4f6", color: "#6b7280" },
};

function StatusBadge({ status }: { status: string }) {
  const s = statusColors[status] ?? { bg: "#f3f4f6", color: "#374151" };
  return (
    <span style={{
      background: s.bg, color: s.color,
      fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 10,
      textTransform: "uppercase", letterSpacing: "0.4px",
    }}>{status}</span>
  );
}

function CodeViewer({ code }: { code: string }) {
  return (
    <pre style={{
      background: "#1a202c", color: "#e2e8f0",
      padding: 16, borderRadius: 8, fontSize: 12,
      overflowX: "auto", maxHeight: 400, overflowY: "auto",
      margin: "12px 0", lineHeight: 1.6,
      fontFamily: "ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace",
    }}>{code}</pre>
  );
}

function ConfirmDialog({
  message, onConfirm, onCancel,
}: { message: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
    }}>
      <div style={{
        background: "#fff", borderRadius: 10, padding: 28, maxWidth: 420, width: "90%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
      }}>
        <p style={{ margin: "0 0 20px", fontSize: 15, color: "#1a202c" }}>{message}</p>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onCancel} style={{
            padding: "8px 18px", borderRadius: 6, border: "1px solid #e2e8f0",
            background: "#fff", cursor: "pointer", fontSize: 13, color: "#4a5568",
          }}>取消</button>
          <button onClick={onConfirm} style={{
            padding: "8px 18px", borderRadius: 6, border: "none",
            background: "#3182ce", color: "#fff", cursor: "pointer", fontSize: 13, fontWeight: 600,
          }}>確認核准</button>
        </div>
      </div>
    </div>
  );
}

function TestRunModal({ result, onClose }: { result: object; onClose: () => void }) {
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
    }}>
      <div style={{
        background: "#fff", borderRadius: 10, padding: 28, maxWidth: 560, width: "90%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16, color: "#1a202c" }}>Test Run 結果</h3>
          <button onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer", fontSize: 20, color: "#718096" }}>×</button>
        </div>
        <pre style={{
          background: "#f7f8fc", padding: 16, borderRadius: 8,
          fontSize: 12, overflowX: "auto", color: "#1a202c",
          fontFamily: "ui-monospace, monospace", lineHeight: 1.6,
        }}>{JSON.stringify(result, null, 2)}</pre>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ScriptRegistryPage() {
  const [scripts, setScripts]             = useState<ScriptVersion[]>([]);
  const [loading, setLoading]             = useState(true);
  const [expandedId, setExpandedId]       = useState<number | null>(null);
  const [confirmId, setConfirmId]         = useState<number | null>(null);
  const [testRunResult, setTestRunResult] = useState<object | null>(null);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [toast, setToast]                 = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setScripts(await fetchPending());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  }

  async function handleApprove(id: number) {
    setActionLoading(id);
    try {
      await approveVersion(id);
      showToast("腳本已核准，status → active");
      await load();
    } catch {
      showToast("核准失敗，請重試");
    } finally {
      setActionLoading(null);
      setConfirmId(null);
    }
  }

  async function handleTestRun(skillId: number, versionId: number) {
    setActionLoading(versionId);
    try {
      const result = await testRun(skillId, versionId);
      setTestRunResult(result);
    } catch {
      showToast("Test run 失敗");
    } finally {
      setActionLoading(null);
    }
  }

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#1a202c" }}>Script Registry</h1>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#718096" }}>
            待審核的 AI 生成診斷腳本 — 核准後才會進入排程執行
          </p>
        </div>
        <button onClick={load} style={{
          padding: "8px 16px", borderRadius: 6, border: "1px solid #e2e8f0",
          background: "#fff", cursor: "pointer", fontSize: 13, color: "#4a5568",
        }}>重新整理</button>
      </div>

      {/* Empty state */}
      {!loading && scripts.length === 0 && (
        <div style={{
          background: "#fff", borderRadius: 10, padding: 48,
          textAlign: "center", border: "1px solid #e2e8f0",
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
          <p style={{ color: "#718096", fontSize: 15, margin: 0 }}>目前沒有待審核的腳本</p>
        </div>
      )}

      {/* Script list */}
      {loading ? (
        <div style={{ textAlign: "center", padding: 48, color: "#718096" }}>載入中…</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {scripts.map((sv) => (
            <div key={sv.id} style={{
              background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0",
              overflow: "hidden",
            }}>
              {/* Row header */}
              <div style={{
                display: "flex", alignItems: "center", gap: 16,
                padding: "14px 20px",
              }}>
                <StatusBadge status={sv.status} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, color: "#1a202c" }}>
                    Skill #{sv.skill_id} — Version {sv.version}
                  </div>
                  {sv.change_note && (
                    <div style={{ fontSize: 12, color: "#718096", marginTop: 2 }}>{sv.change_note}</div>
                  )}
                </div>
                <div style={{ fontSize: 12, color: "#a0aec0", whiteSpace: "nowrap" }}>
                  {new Date(sv.generated_at).toLocaleString("zh-TW")}
                </div>

                {/* Actions */}
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={() => setExpandedId(expandedId === sv.id ? null : sv.id)}
                    style={{
                      padding: "6px 14px", borderRadius: 6, border: "1px solid #e2e8f0",
                      background: "#f7f8fc", cursor: "pointer", fontSize: 12, color: "#4a5568",
                    }}
                  >
                    {expandedId === sv.id ? "收合" : "查看代碼"}
                  </button>
                  <button
                    disabled={actionLoading === sv.id}
                    onClick={() => handleTestRun(sv.skill_id, sv.id)}
                    style={{
                      padding: "6px 14px", borderRadius: 6, border: "1px solid #68d391",
                      background: "#f0fff4", cursor: "pointer", fontSize: 12, color: "#276749",
                    }}
                  >
                    {actionLoading === sv.id ? "執行中…" : "Test Run"}
                  </button>
                  <button
                    disabled={actionLoading === sv.id}
                    onClick={() => setConfirmId(sv.id)}
                    style={{
                      padding: "6px 14px", borderRadius: 6, border: "none",
                      background: "#3182ce", cursor: "pointer", fontSize: 12,
                      color: "#fff", fontWeight: 600,
                    }}
                  >
                    核准
                  </button>
                </div>
              </div>

              {/* Code panel */}
              {expandedId === sv.id && (
                <div style={{ padding: "0 20px 16px", borderTop: "1px solid #f7f8fc" }}>
                  <CodeViewer code={sv.code} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Confirm approve dialog */}
      {confirmId !== null && (
        <ConfirmDialog
          message={`確認核准 ScriptVersion #${confirmId}？核准後將立即成為此 Skill 的執行腳本。`}
          onConfirm={() => handleApprove(confirmId)}
          onCancel={() => setConfirmId(null)}
        />
      )}

      {/* Test run result */}
      {testRunResult && (
        <TestRunModal result={testRunResult} onClose={() => setTestRunResult(null)} />
      )}

      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", bottom: 24, right: 24, zIndex: 2000,
          background: "#2d3748", color: "#fff",
          padding: "12px 20px", borderRadius: 8, fontSize: 13,
          boxShadow: "0 4px 20px rgba(0,0,0,0.2)",
        }}>{toast}</div>
      )}
    </div>
  );
}
