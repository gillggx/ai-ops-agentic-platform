"use client";

import { useCallback, useEffect, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SchemaField {
  name: string;
  type: string;
  description: string;
  required: boolean;
}

interface SystemMcp {
  id: number;
  name: string;
  description: string;
  api_config: Record<string, unknown> | null;
  input_schema: { fields?: SchemaField[] } | null;
  output_schema: Record<string, unknown> | null;
  visibility: string;
  updated_at: string;
}

interface EditForm {
  name: string;
  description: string;
  endpoint_url: string;
  method: string;
  schemaFields: SchemaField[];
}

// ── API helper ─────────────────────────────────────────────────────────────────

const PROXY = "/api/admin/automation";

async function apiFetch(method: string, path: string, body?: unknown) {
  const res = await fetch(`${PROXY}/${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseSchemaFields(input_schema: SystemMcp["input_schema"]): SchemaField[] {
  if (!input_schema) return [];
  const fields = (input_schema as Record<string, unknown>).fields;
  if (!Array.isArray(fields)) return [];
  return fields.map((f) => {
    const field = f as Record<string, unknown>;
    return {
      name:        String(field.name        ?? ""),
      type:        String(field.type        ?? "string"),
      description: String(field.description ?? ""),
      required:    Boolean(field.required),
    };
  });
}

function schemaFieldsToJson(fields: SchemaField[]): Record<string, unknown> {
  return { fields: fields.map(f => ({ ...f, required: f.required })) };
}

// ── Styles ────────────────────────────────────────────────────────────────────

const inp: React.CSSProperties = {
  width: "100%", padding: "6px 9px", borderRadius: 5,
  border: "1px solid #e2e8f0", fontSize: 12,
  color: "#1a202c", background: "#fff", boxSizing: "border-box", outline: "none",
};
const sel: React.CSSProperties = { ...inp, cursor: "pointer" };

function btn(variant: "primary" | "secondary" | "danger" | "ghost" | "dim"): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: "7px 14px", borderRadius: 6, fontSize: 12, fontWeight: 600,
    cursor: "pointer", border: "1px solid transparent", whiteSpace: "nowrap",
  };
  if (variant === "primary")   return { ...base, background: "#3182ce", color: "#fff", border: "1px solid #2b6cb0" };
  if (variant === "danger")    return { ...base, background: "#fff", color: "#e53e3e", border: "1px solid #feb2b2" };
  if (variant === "ghost")     return { ...base, background: "transparent", color: "#3182ce", border: "1px solid #bee3f8" };
  if (variant === "dim")       return { ...base, background: "transparent", color: "#718096", border: "1px solid #e2e8f0", padding: "5px 10px", fontSize: 11 };
  return { ...base, background: "#fff", color: "#4a5568", border: "1px solid #e2e8f0" };
}

const label: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: "#718096",
  marginBottom: 4, display: "block", textTransform: "uppercase", letterSpacing: "0.3px",
};
const fieldWrap: React.CSSProperties = { marginBottom: 14 };
const sectionLabel: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: "#a0aec0",
  textTransform: "uppercase", letterSpacing: "0.5px",
  marginBottom: 8, paddingBottom: 6,
  borderBottom: "1px solid #f0f4f8",
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function SystemMcpAdminPage() {
  const [mcps, setMcps]     = useState<SystemMcp[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<SystemMcp | null>(null);
  const [isNew, setIsNew]   = useState(false);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState<EditForm>({
    name: "", description: "", endpoint_url: "", method: "GET", schemaFields: [],
  });

  // Test params: auto-populated from schemaFields
  const [testParams, setTestParams] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testLoading, setTestLoading] = useState(false);

  // ── Load list ────────────────────────────────────────────────────────────

  const loadList = useCallback(async () => {
    setLoading(true);
    const res = await apiFetch("GET", "mcp-definitions?type=system");
    setMcps(res.data ?? []);
    setLoading(false);
  }, []);

  useEffect(() => { loadList(); }, [loadList]);

  // ── Sync testParams when schemaFields change ─────────────────────────────

  useEffect(() => {
    setTestParams(prev => {
      const next: Record<string, string> = {};
      form.schemaFields.forEach(f => {
        next[f.name] = prev[f.name] ?? "";
      });
      return next;
    });
  }, [form.schemaFields]);

  // ── Select row ───────────────────────────────────────────────────────────

  function selectMcp(mcp: SystemMcp) {
    setSelected(mcp);
    setIsNew(false);
    setTestResult(null);
    const cfg = (mcp.api_config ?? {}) as Record<string, string>;
    const fields = parseSchemaFields(mcp.input_schema);
    setForm({
      name:         mcp.name,
      description:  mcp.description ?? "",
      endpoint_url: cfg.endpoint_url ?? "",
      method:       cfg.method ?? "GET",
      schemaFields: fields,
    });
  }

  function openNew() {
    setSelected(null);
    setIsNew(true);
    setTestResult(null);
    setForm({ name: "", description: "", endpoint_url: "", method: "GET", schemaFields: [] });
    setTestParams({});
  }

  function closePanel() {
    setSelected(null);
    setIsNew(false);
    setTestResult(null);
  }

  // ── Schema field helpers ─────────────────────────────────────────────────

  function addField() {
    setForm(f => ({
      ...f,
      schemaFields: [...f.schemaFields, { name: "", type: "string", description: "", required: true }],
    }));
  }

  function removeField(idx: number) {
    setForm(f => ({ ...f, schemaFields: f.schemaFields.filter((_, i) => i !== idx) }));
  }

  function updateField(idx: number, patch: Partial<SchemaField>) {
    setForm(f => ({
      ...f,
      schemaFields: f.schemaFields.map((field, i) => i === idx ? { ...field, ...patch } : field),
    }));
  }

  // ── Save ─────────────────────────────────────────────────────────────────

  async function handleSave() {
    setSaving(true);
    const payload = {
      name:         form.name,
      description:  form.description,
      api_config:   { endpoint_url: form.endpoint_url, method: form.method },
      input_schema: schemaFieldsToJson(form.schemaFields),
    };
    if (isNew) {
      await apiFetch("POST", "mcp-definitions", { ...payload, mcp_type: "system" });
    } else if (selected) {
      await apiFetch("PATCH", `mcp-definitions/${selected.id}`, payload);
    }
    setSaving(false);
    closePanel();
    loadList();
  }

  // ── Delete ───────────────────────────────────────────────────────────────

  async function handleDelete() {
    if (!selected) return;
    if (!confirm(`確定要刪除「${selected.name}」？`)) return;
    await apiFetch("DELETE", `mcp-definitions/${selected.id}`);
    closePanel();
    loadList();
  }

  // ── Sample Fetch ─────────────────────────────────────────────────────────

  async function handleTest() {
    if (!selected) return;
    setTestLoading(true);
    setTestResult(null);
    try {
      // Filter out empty string values so optional params aren't sent as ""
      const params: Record<string, string> = {};
      Object.entries(testParams).forEach(([k, v]) => { if (v.trim()) params[k] = v.trim(); });
      const res = await apiFetch("POST", `mcp-definitions/${selected.id}/sample-fetch`, params);
      setTestResult(JSON.stringify(res, null, 2));
    } catch (e) {
      setTestResult(String(e));
    }
    setTestLoading(false);
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const panelOpen = !!selected || isNew;

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>System MCPs</h1>
          <p style={{ fontSize: 13, color: "#718096", margin: "4px 0 0" }}>
            管理底層資料來源 MCP（endpoint_url / input_schema）
          </p>
        </div>
        <button style={btn("primary")} onClick={openNew}>+ 新增 System MCP</button>
      </div>

      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>

        {/* ── Table ── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {loading ? (
            <div style={{ color: "#a0aec0", fontSize: 13, padding: 24 }}>載入中...</div>
          ) : (
            <div style={{ background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0", overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: "#f7f8fc" }}>
                    {["ID", "名稱", "Method", "Endpoint URL", ""].map(h => (
                      <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0", whiteSpace: "nowrap" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {mcps.length === 0 && (
                    <tr><td colSpan={5} style={{ padding: "24px 14px", color: "#a0aec0", textAlign: "center" }}>尚無 System MCP</td></tr>
                  )}
                  {mcps.map(m => {
                    const cfg = (m.api_config ?? {}) as Record<string, string>;
                    const isActive = selected?.id === m.id;
                    return (
                      <tr key={m.id} onClick={() => selectMcp(m)} style={{ cursor: "pointer", background: isActive ? "#ebf8ff" : "transparent", borderBottom: "1px solid #f0f0f0" }}>
                        <td style={{ padding: "9px 14px", color: "#a0aec0" }}>{m.id}</td>
                        <td style={{ padding: "9px 14px", fontWeight: 600 }}>{m.name}</td>
                        <td style={{ padding: "9px 14px" }}>
                          <span style={{
                            fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
                            background: cfg.method === "POST" ? "#fefcbf" : "#ebf8ff",
                            color: cfg.method === "POST" ? "#744210" : "#2b6cb0",
                          }}>{cfg.method ?? "GET"}</span>
                        </td>
                        <td style={{ padding: "9px 14px", color: "#4a5568", fontFamily: "ui-monospace, monospace", fontSize: 11, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {cfg.endpoint_url ?? "—"}
                        </td>
                        <td style={{ padding: "9px 14px", textAlign: "right" }}>
                          <button style={btn("ghost")} onClick={e => { e.stopPropagation(); selectMcp(m); }}>編輯</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Edit Panel ── */}
        {panelOpen && (
          <div style={{
            width: 420, flexShrink: 0,
            background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0",
            padding: 20, maxHeight: "85vh", overflowY: "auto",
          }}>
            {/* Panel header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>
                {isNew ? "新增 System MCP" : `編輯 #${selected?.id}`}
              </h3>
              <button style={{ background: "none", border: "none", cursor: "pointer", color: "#a0aec0", fontSize: 18, padding: 0 }} onClick={closePanel}>×</button>
            </div>

            {/* ── Section: Basic Info ── */}
            <div style={{ ...sectionLabel }}>基本資訊</div>

            <div style={fieldWrap}>
              <label style={label}>名稱 *</label>
              <input style={inp} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. get_process_context" />
            </div>

            <div style={fieldWrap}>
              <label style={label}>說明</label>
              <input style={inp} value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder="簡短說明此資料源的用途" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "80px 1fr", gap: 10, marginBottom: 14 }}>
              <div>
                <label style={label}>Method</label>
                <select style={sel} value={form.method} onChange={e => setForm(f => ({ ...f, method: e.target.value }))}>
                  <option value="GET">GET</option>
                  <option value="POST">POST</option>
                </select>
              </div>
              <div>
                <label style={label}>Endpoint URL *</label>
                <input style={inp} value={form.endpoint_url} onChange={e => setForm(f => ({ ...f, endpoint_url: e.target.value }))} placeholder="http://localhost:8012/api/v1/..." />
              </div>
            </div>

            {/* ── Section: Input Schema ── */}
            <div style={{ ...sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>Input 參數定義</span>
              <button style={btn("dim")} onClick={addField}>+ 新增欄位</button>
            </div>

            {form.schemaFields.length === 0 ? (
              <div style={{
                background: "#f7f8fc", border: "1px dashed #cbd5e0",
                borderRadius: 6, padding: "14px 12px",
                color: "#a0aec0", fontSize: 12, textAlign: "center",
                marginBottom: 14,
              }}>
                尚無參數 — 點擊「+ 新增欄位」加入
              </div>
            ) : (
              <div style={{ marginBottom: 14 }}>
                {/* Header row */}
                <div style={{
                  display: "grid", gridTemplateColumns: "1fr 68px 40px 20px",
                  gap: 6, padding: "0 0 5px",
                  fontSize: 10, fontWeight: 700, color: "#a0aec0",
                  textTransform: "uppercase", letterSpacing: "0.3px",
                }}>
                  <span>欄位名稱</span>
                  <span>型別</span>
                  <span style={{ textAlign: "center" }}>必填</span>
                  <span />
                </div>

                {form.schemaFields.map((field, idx) => (
                  <div key={idx} style={{
                    background: "#f7fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: 6, padding: "8px 10px",
                    marginBottom: 6,
                  }}>
                    {/* Row 1: name / type / required / remove */}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 68px 40px 20px", gap: 6, alignItems: "center", marginBottom: 5 }}>
                      <input
                        style={{ ...inp, padding: "4px 7px", fontSize: 12, fontFamily: "ui-monospace, monospace" }}
                        placeholder="field_name"
                        value={field.name}
                        onChange={e => updateField(idx, { name: e.target.value })}
                      />
                      <select
                        style={{ ...sel, padding: "4px 5px", fontSize: 11 }}
                        value={field.type}
                        onChange={e => updateField(idx, { type: e.target.value })}
                      >
                        <option value="string">string</option>
                        <option value="number">number</option>
                        <option value="integer">integer</option>
                        <option value="boolean">boolean</option>
                        <option value="array">array</option>
                        <option value="object">object</option>
                      </select>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <input
                          type="checkbox"
                          checked={field.required}
                          onChange={e => updateField(idx, { required: e.target.checked })}
                          style={{ cursor: "pointer", width: 14, height: 14 }}
                        />
                      </div>
                      <button
                        onClick={() => removeField(idx)}
                        style={{ background: "none", border: "none", color: "#fc8181", cursor: "pointer", fontSize: 15, lineHeight: 1, padding: 0, textAlign: "center" }}
                      >×</button>
                    </div>
                    {/* Row 2: description */}
                    <input
                      style={{ ...inp, padding: "4px 7px", fontSize: 11, color: "#718096", background: "#fff" }}
                      placeholder="欄位說明（選填）"
                      value={field.description}
                      onChange={e => updateField(idx, { description: e.target.value })}
                    />
                  </div>
                ))}
              </div>
            )}

            {/* ── Section: Test Sample Fetch (existing MCP only) ── */}
            {!isNew && (
              <>
                <div style={sectionLabel}>測試 Sample Fetch</div>

                {form.schemaFields.length > 0 ? (
                  <div style={{
                    background: "#f7fafc", border: "1px solid #e2e8f0",
                    borderRadius: 6, padding: "10px 12px", marginBottom: 14,
                  }}>
                    {form.schemaFields.map(field => (
                      <div key={field.name} style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: 8, alignItems: "center", marginBottom: 7 }}>
                        <div>
                          <span style={{ fontSize: 11, fontFamily: "ui-monospace, monospace", color: "#2d3748" }}>
                            {field.name}
                          </span>
                          {field.required && (
                            <span style={{ fontSize: 10, color: "#e53e3e", marginLeft: 3 }}>*</span>
                          )}
                          <div style={{ fontSize: 10, color: "#a0aec0" }}>{field.type}</div>
                        </div>
                        <input
                          style={{ ...inp, padding: "5px 8px", fontSize: 12 }}
                          placeholder={field.required ? "（必填）" : "（選填）"}
                          value={testParams[field.name] ?? ""}
                          onChange={e => setTestParams(p => ({ ...p, [field.name]: e.target.value }))}
                        />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: "#a0aec0", marginBottom: 10 }}>
                    此 MCP 無定義 input 參數，將直接呼叫 endpoint。
                  </div>
                )}

                <button
                  style={{ ...btn("ghost"), marginBottom: 14, width: "100%" }}
                  onClick={handleTest}
                  disabled={testLoading}
                >
                  {testLoading ? "⏳ 撈取中..." : "▶ 執行 Sample Fetch"}
                </button>

                {testResult && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 4 }}>回應結果：</div>
                    <pre style={{
                      background: "#1a202c", color: "#e2e8f0", borderRadius: 6,
                      padding: 12, fontSize: 10, fontFamily: "ui-monospace, monospace",
                      overflowX: "auto", maxHeight: 260, lineHeight: 1.6, margin: 0,
                      whiteSpace: "pre-wrap",
                    }}>{testResult}</pre>
                  </div>
                )}
              </>
            )}

            {/* ── Action buttons ── */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", borderTop: "1px solid #f0f4f8", paddingTop: 14 }}>
              <button style={btn("primary")} onClick={handleSave} disabled={saving || !form.name || !form.endpoint_url}>
                {saving ? "儲存中..." : isNew ? "建立" : "儲存"}
              </button>
              {!isNew && (
                <button style={btn("danger")} onClick={handleDelete}>刪除</button>
              )}
              <button style={btn("secondary")} onClick={closePanel}>取消</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
