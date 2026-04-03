"use client";

import { useEffect, useState, useCallback } from "react";

// ── Types ────────────────────────────────────────────────────────────────────

interface CronJob {
  id: number;
  skill_id: number;
  schedule: string;
  timezone: string;
  label: string;
  status: "active" | "paused" | "deleted";
  created_by: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
}

// ── API helpers ───────────────────────────────────────────────────────────────

const BASE = "/api/admin/automation";

async function fetchJobs(): Promise<CronJob[]> {
  const r = await fetch(`${BASE}/cron-jobs`);
  const d = await r.json();
  return d.data ?? d ?? [];
}

async function createJob(body: {
  skill_id: number; schedule: string; timezone: string; label: string;
}): Promise<void> {
  const r = await fetch(`${BASE}/cron-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d?.detail ?? "建立失敗");
  }
}

async function deleteJob(jobId: number): Promise<void> {
  await fetch(`${BASE}/cron-jobs/${jobId}`, { method: "DELETE" });
}

// ── Sub-components ────────────────────────────────────────────────────────────

const statusColors: Record<string, { bg: string; color: string }> = {
  active:  { bg: "#dbeafe", color: "#1e40af" },
  paused:  { bg: "#fef3c7", color: "#92400e" },
  deleted: { bg: "#f3f4f6", color: "#6b7280" },
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

function formatDt(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-TW");
}

const TIMEZONES = ["Asia/Taipei", "UTC", "Asia/Tokyo", "Asia/Shanghai", "America/New_York"];

const CRON_PRESETS = [
  { label: "每天早上 8 點", value: "0 8 * * *" },
  { label: "每小時",        value: "0 * * * *" },
  { label: "每天午夜",      value: "0 0 * * *" },
  { label: "每週一早上 8 點", value: "0 8 * * 1" },
  { label: "每 30 分鐘",    value: "*/30 * * * *" },
];

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "8px 12px", borderRadius: 6,
  border: "1px solid #e2e8f0", fontSize: 13, color: "#1a202c",
  outline: "none", boxSizing: "border-box",
};

const selectStyle: React.CSSProperties = { ...inputStyle, background: "#fff" };

// ── Create Modal ──────────────────────────────────────────────────────────────

function CreateModal({
  onClose, onCreated,
}: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({
    skill_id: "",
    schedule: "0 8 * * *",
    timezone: "Asia/Taipei",
    label: "",
  });
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  function set(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }

  async function handleSubmit() {
    if (!form.skill_id || !form.schedule) {
      setError("Skill ID 和 Cron 表達式為必填");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await createJob({
        skill_id: Number(form.skill_id),
        schedule: form.schedule,
        timezone: form.timezone,
        label: form.label,
      });
      onCreated();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "建立失敗");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
    }}>
      <div style={{
        background: "#fff", borderRadius: 10, padding: 28, maxWidth: 480, width: "90%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, color: "#1a202c" }}>新增 Cron Job</h3>
          <button onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer", fontSize: 20, color: "#718096" }}>×</button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Skill ID */}
          <div>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#4a5568", marginBottom: 4 }}>
              Skill ID <span style={{ color: "#e53e3e" }}>*</span>
            </label>
            <input
              type="number" value={form.skill_id} style={inputStyle}
              onChange={(e) => set("skill_id", e.target.value)}
              placeholder="例如：1"
            />
          </div>

          {/* Schedule */}
          <div>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#4a5568", marginBottom: 4 }}>
              Cron 表達式 <span style={{ color: "#e53e3e" }}>*</span>
            </label>
            <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
              {CRON_PRESETS.slice(0, 3).map((p) => (
                <button key={p.value} onClick={() => set("schedule", p.value)} style={{
                  padding: "4px 10px", borderRadius: 5, border: "1px solid #e2e8f0",
                  background: form.schedule === p.value ? "#ebf8ff" : "#f7f8fc",
                  color: form.schedule === p.value ? "#2b6cb0" : "#4a5568",
                  cursor: "pointer", fontSize: 11,
                }}>{p.label}</button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              {CRON_PRESETS.slice(3).map((p) => (
                <button key={p.value} onClick={() => set("schedule", p.value)} style={{
                  padding: "4px 10px", borderRadius: 5, border: "1px solid #e2e8f0",
                  background: form.schedule === p.value ? "#ebf8ff" : "#f7f8fc",
                  color: form.schedule === p.value ? "#2b6cb0" : "#4a5568",
                  cursor: "pointer", fontSize: 11,
                }}>{p.label}</button>
              ))}
            </div>
            <input
              value={form.schedule} style={inputStyle}
              onChange={(e) => set("schedule", e.target.value)}
              placeholder="例如：0 8 * * *"
            />
          </div>

          {/* Timezone */}
          <div>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#4a5568", marginBottom: 4 }}>
              時區
            </label>
            <select value={form.timezone} style={selectStyle} onChange={(e) => set("timezone", e.target.value)}>
              {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
            </select>
          </div>

          {/* Label */}
          <div>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#4a5568", marginBottom: 4 }}>
              標籤說明
            </label>
            <input
              value={form.label} style={inputStyle}
              onChange={(e) => set("label", e.target.value)}
              placeholder="例如：每日早班巡檢"
            />
          </div>
        </div>

        {error && (
          <div style={{ marginTop: 12, padding: "8px 12px", background: "#fff5f5", border: "1px solid #fed7d7", borderRadius: 6, fontSize: 12, color: "#c53030" }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 20 }}>
          <button onClick={onClose} style={{
            padding: "8px 18px", borderRadius: 6, border: "1px solid #e2e8f0",
            background: "#fff", cursor: "pointer", fontSize: 13, color: "#4a5568",
          }}>取消</button>
          <button onClick={handleSubmit} disabled={loading} style={{
            padding: "8px 18px", borderRadius: 6, border: "none",
            background: loading ? "#a0aec0" : "#3182ce",
            color: "#fff", cursor: loading ? "not-allowed" : "pointer",
            fontSize: 13, fontWeight: 600,
          }}>{loading ? "建立中…" : "建立"}</button>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CronJobsPage() {
  const [jobs, setJobs]           = useState<CronJob[]>([]);
  const [loading, setLoading]     = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteId, setDeleteId]   = useState<number | null>(null);
  const [toast, setToast]         = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { setJobs(await fetchJobs()); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  }

  async function handleDelete(id: number) {
    try {
      await deleteJob(id);
      showToast(`CronJob #${id} 已刪除`);
      await load();
    } catch {
      showToast("刪除失敗");
    } finally {
      setDeleteId(null);
    }
  }

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#1a202c" }}>Cron Jobs</h1>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#718096" }}>
            管理 AIOps 自動排程，Skill 將依排程自動執行診斷腳本
          </p>
        </div>
        <button onClick={() => setShowCreate(true)} style={{
          padding: "9px 18px", borderRadius: 6, border: "none",
          background: "#3182ce", color: "#fff", cursor: "pointer",
          fontSize: 13, fontWeight: 600,
        }}>+ 新增排程</button>
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ textAlign: "center", padding: 48, color: "#718096" }}>載入中…</div>
      ) : jobs.length === 0 ? (
        <div style={{
          background: "#fff", borderRadius: 10, padding: 48,
          textAlign: "center", border: "1px solid #e2e8f0",
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>⏰</div>
          <p style={{ color: "#718096", fontSize: 15, margin: 0 }}>尚未建立任何排程</p>
          <button onClick={() => setShowCreate(true)} style={{
            marginTop: 16, padding: "8px 18px", borderRadius: 6, border: "none",
            background: "#3182ce", color: "#fff", cursor: "pointer", fontSize: 13,
          }}>建立第一個排程</button>
        </div>
      ) : (
        <div style={{ background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f7f8fc", borderBottom: "1px solid #e2e8f0" }}>
                {["ID", "Skill", "排程", "時區", "標籤", "狀態", "上次執行", "下次執行", ""].map((h) => (
                  <th key={h} style={{
                    padding: "10px 16px", textAlign: "left",
                    fontSize: 11, fontWeight: 600, color: "#718096",
                    textTransform: "uppercase", letterSpacing: "0.4px",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id} style={{ borderBottom: "1px solid #f7f8fc" }}>
                  <td style={{ padding: "12px 16px", color: "#718096", fontWeight: 600 }}>#{job.id}</td>
                  <td style={{ padding: "12px 16px", color: "#1a202c" }}>Skill #{job.skill_id}</td>
                  <td style={{ padding: "12px 16px" }}>
                    <code style={{
                      background: "#f7f8fc", padding: "2px 8px", borderRadius: 4,
                      fontSize: 12, fontFamily: "ui-monospace, monospace", color: "#2b6cb0",
                    }}>{job.schedule}</code>
                  </td>
                  <td style={{ padding: "12px 16px", color: "#4a5568" }}>{job.timezone}</td>
                  <td style={{ padding: "12px 16px", color: "#4a5568" }}>{job.label || "—"}</td>
                  <td style={{ padding: "12px 16px" }}><StatusBadge status={job.status} /></td>
                  <td style={{ padding: "12px 16px", color: "#718096", fontSize: 12 }}>{formatDt(job.last_run_at)}</td>
                  <td style={{ padding: "12px 16px", color: "#718096", fontSize: 12 }}>{formatDt(job.next_run_at)}</td>
                  <td style={{ padding: "12px 16px" }}>
                    <button onClick={() => setDeleteId(job.id)} style={{
                      padding: "5px 12px", borderRadius: 5, border: "1px solid #fed7d7",
                      background: "#fff5f5", color: "#c53030", cursor: "pointer", fontSize: 12,
                    }}>刪除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { load(); showToast("排程已建立"); }}
        />
      )}

      {/* Delete confirm */}
      {deleteId !== null && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
        }}>
          <div style={{
            background: "#fff", borderRadius: 10, padding: 28, maxWidth: 380, width: "90%",
            boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
          }}>
            <p style={{ margin: "0 0 20px", fontSize: 15, color: "#1a202c" }}>
              確認刪除 CronJob #{deleteId}？此操作無法復原，排程將停止觸發。
            </p>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button onClick={() => setDeleteId(null)} style={{
                padding: "8px 18px", borderRadius: 6, border: "1px solid #e2e8f0",
                background: "#fff", cursor: "pointer", fontSize: 13, color: "#4a5568",
              }}>取消</button>
              <button onClick={() => handleDelete(deleteId)} style={{
                padding: "8px 18px", borderRadius: 6, border: "none",
                background: "#e53e3e", color: "#fff", cursor: "pointer",
                fontSize: 13, fontWeight: 600,
              }}>確認刪除</button>
            </div>
          </div>
        </div>
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
