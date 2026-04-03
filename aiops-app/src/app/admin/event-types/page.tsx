"use client";

import { useEffect, useState, useCallback } from "react";
import { AdminTable } from "@/components/admin/AdminTable";
import { Modal, FormField, inputStyle, selectStyle } from "@/components/admin/Modal";
import type { StoredEventType } from "@/lib/store";

const SEVERITY_COLOR: Record<string, string> = {
  info: "#63b3ed", warning: "#f6e05e", critical: "#fc8181",
};

const EMPTY_FORM = { name: "", severity: "info" as StoredEventType["severity"], description: "" };

export default function EventTypesPage() {
  const [types, setTypes] = useState<StoredEventType[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const r = await fetch("/api/admin/event-types");
    setTypes(await r.json());
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(id: string) {
    if (!confirm("確定刪除此 Event Type？")) return;
    await fetch(`/api/admin/event-types/${id}`, { method: "DELETE" });
    load();
  }

  async function handleSave() {
    setError("");
    if (!form.name.trim()) { setError("Name 必填"); return; }
    const res = await fetch("/api/admin/event-types", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!res.ok) { const b = await res.json(); setError(b.error ?? "儲存失敗"); return; }
    setShowModal(false);
    setForm(EMPTY_FORM);
    load();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, color: "#e2e8f0" }}>Event Types</h1>
          <p style={{ margin: "4px 0 0", color: "#718096", fontSize: 13 }}>
            定義設備事件類型與嚴重程度，供 ontology 與 Agent 解析使用。
          </p>
        </div>
        <button onClick={() => { setForm(EMPTY_FORM); setError(""); setShowModal(true); }} style={primaryBtn}>
          + 新增 Event Type
        </button>
      </div>

      <AdminTable
        columns={[
          { key: "name",        label: "Name" },
          { key: "severity",    label: "Severity", render: (r) =>
            <span style={{ color: SEVERITY_COLOR[r.severity] ?? "#a0aec0", fontSize: 12, fontWeight: 600 }}>
              {r.severity.toUpperCase()}
            </span> },
          { key: "description", label: "Description" },
          { key: "created_at",  label: "Created", render: (r) =>
            <span style={{ fontSize: 12, color: "#718096" }}>{new Date(r.created_at).toLocaleString("zh-TW")}</span> },
        ]}
        rows={types}
        onDelete={handleDelete}
      />

      {showModal && (
        <Modal title="新增 Event Type" onClose={() => setShowModal(false)}>
          <FormField label="Name *">
            <input style={inputStyle} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="hardware_fault" />
          </FormField>
          <FormField label="Severity">
            <select style={selectStyle as React.CSSProperties} value={form.severity}
              onChange={(e) => setForm({ ...form, severity: e.target.value as StoredEventType["severity"] })}>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="critical">critical</option>
            </select>
          </FormField>
          <FormField label="Description">
            <input style={inputStyle} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </FormField>
          {error && <p style={{ color: "#fc8181", fontSize: 13, margin: "8px 0" }}>{error}</p>}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
            <button onClick={() => setShowModal(false)} style={secondaryBtn}>取消</button>
            <button onClick={handleSave} style={primaryBtn}>儲存</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  background: "#3182ce", color: "#fff", border: "none", borderRadius: 6,
  padding: "8px 18px", cursor: "pointer", fontSize: 14, fontWeight: 600,
};
const secondaryBtn: React.CSSProperties = {
  background: "#2d3748", color: "#a0aec0", border: "1px solid #4a5568",
  borderRadius: 6, padding: "8px 18px", cursor: "pointer", fontSize: 14,
};
