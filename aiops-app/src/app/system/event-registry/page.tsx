"use client";

import { useCallback, useEffect, useState } from "react";
import type { StoredEventType } from "@/lib/store";

// ── Types ─────────────────────────────────────────────────────────────────────

interface EventLog {
  event_type_name: string;
  total: number;
  recent: {
    id: number;
    equipment_id: string | null;
    lot_id: string | null;
    received_at: string | null;
  }[];
}

// ── Styles ────────────────────────────────────────────────────────────────────

const SEVERITY_COLOR: Record<string, { text: string; bg: string }> = {
  info:     { text: "#2b6cb0", bg: "#ebf8ff" },
  warning:  { text: "#744210", bg: "#fefcbf" },
  critical: { text: "#742a2a", bg: "#fff5f5" },
};

const primaryBtn: React.CSSProperties = {
  background: "#3182ce", color: "#fff", border: "none", borderRadius: 6,
  padding: "8px 16px", cursor: "pointer", fontSize: 13, fontWeight: 600,
};
const secondaryBtn: React.CSSProperties = {
  background: "#fff", color: "#4a5568", border: "1px solid #e2e8f0",
  borderRadius: 6, padding: "8px 16px", cursor: "pointer", fontSize: 13,
};
const inp: React.CSSProperties = {
  width: "100%", padding: "7px 10px", borderRadius: 5, fontSize: 13,
  border: "1px solid #e2e8f0", background: "#fff", color: "#1a202c",
  boxSizing: "border-box", outline: "none",
};
const sel: React.CSSProperties = { ...inp, cursor: "pointer" };

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1)  return "剛才";
  if (mins < 60) return `${mins} 分鐘前`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs} 小時前`;
  return `${Math.floor(hrs / 24)} 天前`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function EventRegistryPage() {
  const [types, setTypes]           = useState<StoredEventType[]>([]);
  const [logs, setLogs]             = useState<Record<string, EventLog>>({});
  const [selectedName, setSelected] = useState<string | null>(null);
  const [showModal, setShowModal]   = useState(false);
  const [form, setForm]             = useState({ name: "", severity: "warning" as StoredEventType["severity"], description: "" });
  const [formError, setFormError]   = useState("");

  // ── Load event types ───────────────────────────────────────────────────────

  const loadTypes = useCallback(async () => {
    const r = await fetch("/api/admin/event-types");
    const data: StoredEventType[] = await r.json();
    setTypes(data);
    // Fetch log counts for all types in parallel
    const entries = await Promise.all(
      data.map(async (t) => {
        try {
          const lr = await fetch(`/api/admin/event-types/${encodeURIComponent(t.name)}/log?limit=10`, { cache: "no-store" });
          const ld = await lr.json();
          return [t.name, ld] as [string, EventLog];
        } catch {
          return [t.name, { event_type_name: t.name, total: 0, recent: [] }] as [string, EventLog];
        }
      })
    );
    setLogs(Object.fromEntries(entries));
  }, []);

  useEffect(() => { loadTypes(); }, [loadTypes]);

  // ── Auto-refresh log every 15s ─────────────────────────────────────────────
  useEffect(() => {
    const id = setInterval(loadTypes, 15000);
    return () => clearInterval(id);
  }, [loadTypes]);

  // ── CRUD ──────────────────────────────────────────────────────────────────

  async function handleDelete(id: string, name: string) {
    if (!confirm(`確定刪除 Event Type「${name}」？`)) return;
    await fetch(`/api/admin/event-types/${id}`, { method: "DELETE" });
    setSelected(null);
    loadTypes();
  }

  async function handleSave() {
    setFormError("");
    if (!form.name.trim()) { setFormError("Name 必填"); return; }
    const res = await fetch("/api/admin/event-types", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!res.ok) { const b = await res.json(); setFormError(b.error ?? "儲存失敗"); return; }
    setShowModal(false);
    setForm({ name: "", severity: "warning", description: "" });
    loadTypes();
  }

  const selectedLog = selectedName ? logs[selectedName] : null;

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#1a202c" }}>Event Registry</h1>
          <p style={{ margin: "4px 0 0", color: "#718096", fontSize: 13 }}>
            定義設備事件類型與嚴重程度，供 ontology 與 Agent 解析使用。
          </p>
        </div>
        <button style={primaryBtn} onClick={() => { setForm({ name: "", severity: "warning", description: "" }); setFormError(""); setShowModal(true); }}>
          + 新增 Event Type
        </button>
      </div>

      {/* Event Types Table */}
      <div style={{ background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0", overflow: "hidden", marginBottom: 24 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f7f8fc" }}>
              {["Name", "Severity", "Description", "收到次數", "最後收到", "操作"].map(h => (
                <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0", whiteSpace: "nowrap" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {types.length === 0 && (
              <tr><td colSpan={6} style={{ padding: "24px", color: "#a0aec0", textAlign: "center" }}>尚無 Event Type</td></tr>
            )}
            {types.map(t => {
              const log = logs[t.name];
              const sc = SEVERITY_COLOR[t.severity] ?? SEVERITY_COLOR.info;
              const isSelected = selectedName === t.name;
              return (
                <tr
                  key={t.id}
                  onClick={() => setSelected(isSelected ? null : t.name)}
                  style={{ cursor: "pointer", background: isSelected ? "#ebf8ff" : "transparent", borderBottom: "1px solid #f0f0f0", transition: "background 0.1s" }}
                  onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "#f7f8fc"; }}
                  onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >
                  <td style={{ padding: "11px 16px", fontWeight: 600 }}>{t.name}</td>
                  <td style={{ padding: "11px 16px" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, color: sc.text, background: sc.bg }}>
                      {t.severity.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ padding: "11px 16px", color: "#4a5568" }}>{t.description}</td>
                  <td style={{ padding: "11px 16px" }}>
                    {log === undefined ? (
                      <span style={{ color: "#a0aec0", fontSize: 12 }}>—</span>
                    ) : (
                      <span style={{
                        fontWeight: 700, fontSize: 13,
                        color: log.total > 0 ? "#2b6cb0" : "#a0aec0",
                      }}>
                        {log.total > 0 ? `${log.total} ↑` : "0"}
                      </span>
                    )}
                  </td>
                  <td style={{ padding: "11px 16px", color: "#718096", fontSize: 12 }}>
                    {log?.recent?.[0]?.received_at ? relativeTime(log.recent[0].received_at) : "—"}
                  </td>
                  <td style={{ padding: "11px 16px" }} onClick={e => e.stopPropagation()}>
                    <button
                      style={{ background: "#fff", color: "#e53e3e", border: "1px solid #feb2b2", borderRadius: 5, padding: "4px 10px", fontSize: 12, cursor: "pointer", fontWeight: 600 }}
                      onClick={() => handleDelete(t.id, t.name)}
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

      {/* Log Panel */}
      {selectedName && selectedLog && (
        <div style={{ background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0", overflow: "hidden" }}>
          {/* Panel header */}
          <div style={{ padding: "14px 20px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ fontWeight: 700, fontSize: 14, color: "#1a202c" }}>
                {selectedName} — 收到紀錄
              </span>
              <span style={{ fontSize: 12, background: "#ebf8ff", color: "#2b6cb0", padding: "2px 8px", borderRadius: 10, fontWeight: 600 }}>
                共 {selectedLog.total} 筆
              </span>
              <span style={{ fontSize: 11, color: "#a0aec0" }}>每 15 秒自動更新</span>
            </div>
            <button style={{ background: "none", border: "none", cursor: "pointer", color: "#a0aec0", fontSize: 18 }} onClick={() => setSelected(null)}>×</button>
          </div>

          {/* Log table */}
          {selectedLog.recent.length === 0 ? (
            <div style={{ padding: "32px", textAlign: "center", color: "#a0aec0", fontSize: 13 }}>
              尚未收到任何 <strong>{selectedName}</strong> 事件
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f7f8fc" }}>
                  {["#", "收到時間", "Equipment", "Lot ID"].map(h => (
                    <th key={h} style={{ padding: "9px 16px", textAlign: "left", fontWeight: 600, color: "#718096", borderBottom: "1px solid #e2e8f0", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.4px" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {selectedLog.recent.map((row, i) => (
                  <tr key={row.id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                    <td style={{ padding: "9px 16px", color: "#a0aec0", fontFamily: "ui-monospace, monospace", fontSize: 11 }}>{row.id}</td>
                    <td style={{ padding: "9px 16px", color: "#4a5568", whiteSpace: "nowrap" }}>
                      {row.received_at ? (
                        <>
                          <span style={{ fontWeight: 500 }}>{relativeTime(row.received_at)}</span>
                          <span style={{ color: "#a0aec0", marginLeft: 8, fontSize: 11 }}>
                            {new Date(row.received_at).toLocaleString("zh-TW")}
                          </span>
                        </>
                      ) : "—"}
                    </td>
                    <td style={{ padding: "9px 16px", fontFamily: "ui-monospace, monospace", fontSize: 12, color: "#2d3748" }}>
                      {row.equipment_id || <span style={{ color: "#a0aec0" }}>—</span>}
                    </td>
                    <td style={{ padding: "9px 16px", fontFamily: "ui-monospace, monospace", fontSize: 12, color: "#2d3748" }}>
                      {row.lot_id || <span style={{ color: "#a0aec0" }}>—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Add Modal */}
      {showModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
          <div style={{ background: "#fff", borderRadius: 12, padding: 28, width: 420, boxShadow: "0 20px 60px rgba(0,0,0,0.15)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#1a202c" }}>新增 Event Type</h3>
              <button style={{ background: "none", border: "none", cursor: "pointer", color: "#a0aec0", fontSize: 20 }} onClick={() => setShowModal(false)}>×</button>
            </div>
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: "#718096", display: "block", marginBottom: 4, textTransform: "uppercase" }}>Name *</label>
              <input style={inp} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="OOC" />
            </div>
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: "#718096", display: "block", marginBottom: 4, textTransform: "uppercase" }}>Severity</label>
              <select style={sel} value={form.severity} onChange={e => setForm({ ...form, severity: e.target.value as StoredEventType["severity"] })}>
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="critical">critical</option>
              </select>
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: "#718096", display: "block", marginBottom: 4, textTransform: "uppercase" }}>Description</label>
              <input style={inp} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} placeholder="簡短說明" />
            </div>
            {formError && <p style={{ color: "#e53e3e", fontSize: 13, margin: "0 0 12px" }}>{formError}</p>}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button onClick={() => setShowModal(false)} style={secondaryBtn}>取消</button>
              <button onClick={handleSave} style={primaryBtn}>儲存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
