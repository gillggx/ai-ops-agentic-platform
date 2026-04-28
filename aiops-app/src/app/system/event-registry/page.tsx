"use client";

import { useCallback, useEffect, useState } from "react";

// ── Types (Java backend shape) ────────────────────────────────────────────────

interface EventTypeRow {
  id: number;
  name: string;
  description: string;
  source: string;
  isActive: boolean;
  attributes: string;        // JSON-encoded list of AttributeSpec
  diagnosisSkillIds: string; // JSON-encoded list (legacy)
}

interface AttributeSpec {
  name: string;
  type: "string" | "number" | "boolean" | "object";
  required: boolean;
  description?: string;
  enum?: string[];
}

interface EventLog {
  event_type_name: string;
  total: number;
  poller_total?: number;
  nats_total?: number;
  recent: Record<string, unknown>[];
}

// ── Styles ────────────────────────────────────────────────────────────────────

const primaryBtn: React.CSSProperties = {
  background: "#3182ce", color: "#fff", border: "none", borderRadius: 6,
  padding: "8px 16px", cursor: "pointer", fontSize: 13, fontWeight: 600,
};
const secondaryBtn: React.CSSProperties = {
  background: "#fff", color: "#4a5568", border: "1px solid #e2e8f0",
  borderRadius: 6, padding: "8px 16px", cursor: "pointer", fontSize: 13,
};
const inp: React.CSSProperties = {
  width: "100%", padding: "6px 9px", borderRadius: 5, fontSize: 12,
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

function parseAttrs(s: string): AttributeSpec[] {
  if (!s) return [];
  try {
    const parsed = JSON.parse(s);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

interface FormState {
  id?: number;            // present = edit mode
  name: string;
  description: string;
  attributes: AttributeSpec[];
}

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  attributes: [
    { name: "equipment_id", type: "string", required: true, description: "機台 ID" },
    { name: "step",         type: "string", required: true, description: "製程 step" },
  ],
};

export default function EventRegistryPage() {
  const [types, setTypes]             = useState<EventTypeRow[]>([]);
  const [logs, setLogs]               = useState<Record<number, EventLog>>({});
  const [selectedId, setSelected]     = useState<number | null>(null);
  const [showModal, setShowModal]     = useState(false);
  const [form, setForm]               = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError]     = useState("");

  // ── Load ────────────────────────────────────────────────────────────────────

  const loadTypes = useCallback(async () => {
    const r = await fetch("/api/admin/event-types");
    const data: EventTypeRow[] = await r.json();
    setTypes(Array.isArray(data) ? data : []);
    // Fetch log counts for all types in parallel
    const entries = await Promise.all(
      (Array.isArray(data) ? data : []).map(async (t) => {
        try {
          const lr = await fetch(`/api/admin/event-types/${t.id}/log?limit=10`, { cache: "no-store" });
          const ld = await lr.json();
          return [t.id, ld] as [number, EventLog];
        } catch {
          return [t.id, { event_type_name: t.name, total: 0, recent: [] }] as [number, EventLog];
        }
      }),
    );
    setLogs(Object.fromEntries(entries));
  }, []);

  useEffect(() => { loadTypes(); }, [loadTypes]);
  useEffect(() => {
    const id = setInterval(loadTypes, 30000);
    return () => clearInterval(id);
  }, [loadTypes]);

  // ── CRUD ────────────────────────────────────────────────────────────────────

  function openCreate() {
    setForm(EMPTY_FORM);
    setFormError("");
    setShowModal(true);
  }

  function openEdit(t: EventTypeRow) {
    setForm({
      id: t.id,
      name: t.name,
      description: t.description,
      attributes: parseAttrs(t.attributes),
    });
    setFormError("");
    setShowModal(true);
  }

  async function handleSave() {
    setFormError("");
    if (!form.name.trim()) { setFormError("Name 必填"); return; }
    // Validate attribute names unique & non-empty
    const names = form.attributes.map(a => a.name.trim());
    if (names.some(n => !n)) { setFormError("Attribute name 不可空白"); return; }
    if (new Set(names).size !== names.length) { setFormError("Attribute name 重複"); return; }

    const payload = {
      name: form.name.trim(),
      description: form.description,
      attributes: JSON.stringify(form.attributes),
    };
    const isEdit = form.id != null;
    const url = isEdit ? `/api/admin/event-types/${form.id}` : "/api/admin/event-types";
    const res = await fetch(url, {
      method: isEdit ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      setFormError(b.error ?? (isEdit ? "更新失敗" : "建立失敗"));
      return;
    }
    setShowModal(false);
    setForm(EMPTY_FORM);
    loadTypes();
  }

  async function handleDelete(t: EventTypeRow) {
    if (!confirm(`確定刪除 Event Type「${t.name}」？`)) return;
    await fetch(`/api/admin/event-types/${t.id}`, { method: "DELETE" });
    setSelected(null);
    loadTypes();
  }

  // ── Attribute editor row helpers ────────────────────────────────────────────

  function addAttr() {
    setForm(f => ({ ...f, attributes: [...f.attributes, { name: "", type: "string", required: false, description: "" }] }));
  }
  function updateAttr(idx: number, patch: Partial<AttributeSpec>) {
    setForm(f => ({ ...f, attributes: f.attributes.map((a, i) => i === idx ? { ...a, ...patch } : a) }));
  }
  function removeAttr(idx: number) {
    setForm(f => ({ ...f, attributes: f.attributes.filter((_, i) => i !== idx) }));
  }

  const selectedType = types.find(t => t.id === selectedId);
  const selectedLog = selectedId != null ? logs[selectedId] : null;

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#1a202c" }}>Event Registry</h1>
          <p style={{ margin: "4px 0 0", color: "#718096", fontSize: 13 }}>
            定義設備事件類型與屬性 schema，供 ontology 與 Auto-Patrol input mapping 使用。
          </p>
        </div>
        <button style={primaryBtn} onClick={openCreate}>+ 新增 Event Type</button>
      </div>

      {/* Table */}
      <div style={{ background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0", overflow: "hidden", marginBottom: 24 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f7f8fc" }}>
              {["Name", "Source", "Description", "Attributes", "收到次數", "最後收到", "操作"].map(h => (
                <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0", whiteSpace: "nowrap" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {types.length === 0 && (
              <tr><td colSpan={7} style={{ padding: "24px", color: "#a0aec0", textAlign: "center" }}>尚無 Event Type</td></tr>
            )}
            {types.map(t => {
              const log = logs[t.id];
              const attrs = parseAttrs(t.attributes);
              const isSelected = selectedId === t.id;
              return (
                <tr
                  key={t.id}
                  onClick={() => setSelected(isSelected ? null : t.id)}
                  style={{ cursor: "pointer", background: isSelected ? "#ebf8ff" : "transparent", borderBottom: "1px solid #f0f0f0" }}
                >
                  <td style={{ padding: "11px 16px", fontWeight: 600 }}>{t.name}</td>
                  <td style={{ padding: "11px 16px", color: "#4a5568", fontSize: 12 }}>{t.source}</td>
                  <td style={{ padding: "11px 16px", color: "#4a5568", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.description}</td>
                  <td style={{ padding: "11px 16px" }}>
                    <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 10, background: "#edf2f7", color: "#4a5568" }}>
                      {attrs.length} 個欄位
                    </span>
                  </td>
                  <td style={{ padding: "11px 16px" }}>
                    <span style={{ fontWeight: 700, fontSize: 13, color: log && log.total > 0 ? "#2b6cb0" : "#a0aec0" }}>
                      {log ? log.total : 0}
                    </span>
                  </td>
                  <td style={{ padding: "11px 16px", color: "#718096", fontSize: 12 }}>
                    {log?.recent?.[0]?.received_at ? relativeTime(log.recent[0].received_at as string) : (log?.recent?.[0]?.started_at ? relativeTime(log.recent[0].started_at as string) : "—")}
                  </td>
                  <td style={{ padding: "11px 16px", display: "flex", gap: 6 }} onClick={e => e.stopPropagation()}>
                    <button
                      style={{ background: "#fff", color: "#3182ce", border: "1px solid #bee3f8", borderRadius: 5, padding: "4px 10px", fontSize: 12, cursor: "pointer", fontWeight: 600 }}
                      onClick={() => openEdit(t)}
                    >
                      編輯
                    </button>
                    <button
                      style={{ background: "#fff", color: "#e53e3e", border: "1px solid #feb2b2", borderRadius: 5, padding: "4px 10px", fontSize: 12, cursor: "pointer", fontWeight: 600 }}
                      onClick={() => handleDelete(t)}
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

      {/* Selected: attribute schema preview */}
      {selectedType && (
        <div style={{ background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0", padding: 16, marginBottom: 24 }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10 }}>
            <span>{selectedType.name}</span>
            <span style={{ marginLeft: 12, fontSize: 12, color: "#a0aec0" }}>Attribute schema</span>
          </div>
          {parseAttrs(selectedType.attributes).length === 0 ? (
            <div style={{ color: "#a0aec0", fontSize: 12 }}>尚未定義 attribute</div>
          ) : (
            <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "#f7f8fc" }}>
                  {["Name", "Type", "Required", "Description"].map(h => (
                    <th key={h} style={{ padding: "6px 10px", textAlign: "left", color: "#718096", fontWeight: 600 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {parseAttrs(selectedType.attributes).map((a, i) => (
                  <tr key={i} style={{ borderTop: "1px solid #f0f0f0" }}>
                    <td style={{ padding: "6px 10px", fontFamily: "monospace", fontWeight: 600 }}>{a.name}</td>
                    <td style={{ padding: "6px 10px", color: "#4a5568" }}>{a.type}</td>
                    <td style={{ padding: "6px 10px" }}>
                      {a.required ? <span style={{ color: "#c05621", fontWeight: 600 }}>required</span> : <span style={{ color: "#a0aec0" }}>optional</span>}
                    </td>
                    <td style={{ padding: "6px 10px", color: "#4a5568" }}>{a.description ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {selectedLog && (
            <div style={{ marginTop: 12, fontSize: 11, color: "#a0aec0" }}>
              收到次數: {selectedLog.total} | 最近: {selectedLog.recent.length} 筆
            </div>
          )}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
          <div style={{ background: "#fff", borderRadius: 12, padding: 24, width: 720, maxHeight: "90vh", overflowY: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.15)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#1a202c" }}>
                {form.id != null ? "編輯 Event Type" : "新增 Event Type"}
              </h3>
              <button style={{ background: "none", border: "none", cursor: "pointer", color: "#a0aec0", fontSize: 20 }} onClick={() => setShowModal(false)}>×</button>
            </div>

            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: "#718096", display: "block", marginBottom: 4, textTransform: "uppercase" }}>Name *</label>
              <input
                style={inp}
                value={form.name}
                disabled={form.id != null}
                onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="OOC"
              />
              {form.id != null && <p style={{ fontSize: 10, color: "#a0aec0", margin: "2px 0 0" }}>name 是 unique key，建立後不可改</p>}
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: "#718096", display: "block", marginBottom: 4, textTransform: "uppercase" }}>Description</label>
              <input style={inp} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} placeholder="簡短說明" />
            </div>

            {/* Attribute editor */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <label style={{ fontSize: 11, fontWeight: 600, color: "#718096", textTransform: "uppercase" }}>
                  Attributes — 事件 payload 帶哪些欄位（patrol input mapping 會用）
                </label>
                <button onClick={addAttr} style={{ ...secondaryBtn, padding: "4px 10px", fontSize: 11 }}>+ 新增欄位</button>
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ background: "#f7f8fc" }}>
                    {["Name", "Type", "Required", "Description", ""].map(h => (
                      <th key={h} style={{ padding: "5px 8px", textAlign: "left", color: "#718096", fontWeight: 600, fontSize: 10, textTransform: "uppercase" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {form.attributes.length === 0 && (
                    <tr><td colSpan={5} style={{ padding: 16, textAlign: "center", color: "#a0aec0" }}>尚無 attribute — 點「+ 新增欄位」</td></tr>
                  )}
                  {form.attributes.map((a, i) => (
                    <tr key={i} style={{ borderTop: "1px solid #f0f0f0" }}>
                      <td style={{ padding: "4px 8px", width: "30%" }}>
                        <input style={inp} value={a.name} onChange={e => updateAttr(i, { name: e.target.value })} placeholder="equipment_id" />
                      </td>
                      <td style={{ padding: "4px 8px", width: "20%" }}>
                        <select style={sel} value={a.type} onChange={e => updateAttr(i, { type: e.target.value as AttributeSpec["type"] })}>
                          <option value="string">string</option>
                          <option value="number">number</option>
                          <option value="boolean">boolean</option>
                          <option value="object">object</option>
                        </select>
                      </td>
                      <td style={{ padding: "4px 8px", textAlign: "center", width: 80 }}>
                        <input type="checkbox" checked={a.required} onChange={e => updateAttr(i, { required: e.target.checked })} />
                      </td>
                      <td style={{ padding: "4px 8px" }}>
                        <input style={inp} value={a.description ?? ""} onChange={e => updateAttr(i, { description: e.target.value })} placeholder="說明（選填）" />
                      </td>
                      <td style={{ padding: "4px 8px", width: 40 }}>
                        <button onClick={() => removeAttr(i)} style={{ background: "transparent", border: "none", cursor: "pointer", color: "#e53e3e", fontSize: 14 }}>×</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
