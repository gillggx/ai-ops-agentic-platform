"use client";

import { useCallback, useEffect, useState } from "react";

interface StepEntry { step_id: string; nl_segment: string; python_code: string }
interface SchemaField { key?: string; name?: string; type?: string; label?: string; required?: boolean; description?: string; unit?: string }

interface SkillRow {
  id: number;
  name: string;
  description: string;
  source: string;
  visibility: string;
  is_active: boolean;
  auto_check_description: string;
  trigger_patrol_id: number | null;
  trigger_mode: string;
  created_at: string;
  updated_at: string;
  steps_mapping: StepEntry[];
  input_schema: SchemaField[];
  output_schema: SchemaField[];
}

const SOURCE_BADGE: Record<string, { bg: string; color: string; label: string }> = {
  skill:       { bg: "#f0fff4", color: "#276749", label: "My Skill" },
  rule:        { bg: "#dbeafe", color: "#1e40af", label: "Diagnostic Rule" },
  auto_patrol: { bg: "#fef3c7", color: "#92400e", label: "Auto-Patrol" },
  legacy:      { bg: "#e2e8f0", color: "#4a5568", label: "Legacy" },
};

// ── Detail section components ────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, color: "#718096", textTransform: "uppercase",
      letterSpacing: "0.4px", marginBottom: 8, paddingBottom: 4, borderBottom: "1px solid #edf2f7",
    }}>{children}</div>
  );
}

function StepsViewer({ steps }: { steps: StepEntry[] }) {
  if (!steps.length) return <div style={{ color: "#a0aec0", fontSize: 12 }}>尚無定義</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {steps.map((step, i) => (
        <div key={step.step_id || i} style={{ background: "#f7fafc", border: "1px solid #e2e8f0", borderRadius: 6, overflow: "hidden" }}>
          <div style={{ padding: "8px 12px", background: "#edf2f7", fontSize: 11, fontWeight: 600, color: "#4a5568", display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ background: "#cbd5e0", color: "#fff", borderRadius: 4, padding: "1px 6px", fontSize: 10 }}>Step {step.step_id || i + 1}</span>
            <span>{step.nl_segment}</span>
          </div>
          {step.python_code && (
            <pre style={{
              margin: 0, padding: "10px 12px", fontSize: 11, lineHeight: 1.5,
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              color: "#e2e8f0", background: "#1a202c",
              overflowX: "auto", maxHeight: 260,
              whiteSpace: "pre-wrap", wordBreak: "break-word",
            }}>{step.python_code}</pre>
          )}
        </div>
      ))}
    </div>
  );
}

function SchemaTable({ fields, label }: { fields: SchemaField[]; label: string }) {
  if (!fields.length) return <div style={{ color: "#a0aec0", fontSize: 12 }}>尚無定義</div>;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
      <thead>
        <tr style={{ borderBottom: "1px solid #e2e8f0" }}>
          {["Key", "Type", label === "Input" ? "Required" : "Label", "Description / Unit"].map(h => (
            <th key={h} style={{ padding: "5px 8px", textAlign: "left", fontWeight: 600, color: "#a0aec0", fontSize: 10 }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {fields.map((f, i) => (
          <tr key={i} style={{ borderBottom: "1px solid #f7f8fc" }}>
            <td style={{ padding: "5px 8px", fontFamily: "monospace", color: "#2d3748" }}>{f.key || f.name || "—"}</td>
            <td style={{ padding: "5px 8px", color: "#718096" }}>{f.type || "—"}</td>
            <td style={{ padding: "5px 8px", color: "#718096" }}>
              {label === "Input" ? (f.required ? "✓" : "—") : (f.label || "—")}
            </td>
            <td style={{ padding: "5px 8px", color: "#718096" }}>
              {f.description || f.unit || "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MetadataGrid({ skill }: { skill: SkillRow }) {
  const items = [
    { label: "Source", value: skill.source },
    { label: "Visibility", value: skill.visibility },
    { label: "Trigger Mode", value: skill.trigger_mode || "—" },
    { label: "Trigger Patrol ID", value: skill.trigger_patrol_id != null ? `#${skill.trigger_patrol_id}` : "—" },
    { label: "Active", value: skill.is_active ? "Yes" : "No" },
    { label: "Created", value: new Date(skill.created_at).toLocaleString("zh-TW") },
    { label: "Updated", value: new Date(skill.updated_at).toLocaleString("zh-TW") },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "6px 16px" }}>
      {items.map(({ label, value }) => (
        <div key={label} style={{ fontSize: 12 }}>
          <span style={{ color: "#a0aec0", fontWeight: 600, fontSize: 10, textTransform: "uppercase" }}>{label}: </span>
          <span style={{ color: "#4a5568" }}>{value}</span>
        </div>
      ))}
      {skill.auto_check_description && (
        <div style={{ gridColumn: "1 / -1", fontSize: 12 }}>
          <span style={{ color: "#a0aec0", fontWeight: 600, fontSize: 10, textTransform: "uppercase" }}>Auto-Check: </span>
          <span style={{ color: "#4a5568" }}>{skill.auto_check_description}</span>
        </div>
      )}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function AllSkillsPage() {
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [tab, setTab] = useState<"steps" | "schema" | "meta">("steps");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/admin/skills", { cache: "no-store" });
      const data = await res.json();
      setSkills(Array.isArray(data) ? data : []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function toggleExpand(id: number) {
    setExpandedId(prev => prev === id ? null : id);
    setTab("steps");
  }

  async function handleDelete(id: number, name: string) {
    if (!confirm(`確定要刪除 Skill #${id}「${name}」？此動作無法復原。`)) return;
    await fetch(`/api/admin/skills/${id}`, { method: "DELETE" });
    setExpandedId(null);
    await load();
  }

  return (
    <div style={{ maxWidth: 1200 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#1a202c" }}>All Skills</h1>
        <p style={{ margin: "4px 0 0", fontSize: 13, color: "#718096" }}>
          系統中所有 Skill 的總覽（含 Diagnostic Rules、Auto-Patrol 內嵌技能、公開 Skill）
        </p>
      </div>

      {loading ? (
        <div style={{ padding: 48, textAlign: "center", color: "#718096" }}>載入中…</div>
      ) : skills.length === 0 ? (
        <div style={{ background: "#fff", borderRadius: 10, padding: 56, textAlign: "center", border: "1px solid #e2e8f0" }}>
          <p style={{ color: "#718096" }}>尚無任何 Skill</p>
        </div>
      ) : (
        <div style={{ background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f7f8fc", borderBottom: "1px solid #e2e8f0" }}>
                {["ID", "名稱", "類型", "可見性", "Steps", "Input", "更新時間", ""].map(h => (
                  <th key={h} style={{
                    padding: "10px 14px", textAlign: "left", fontSize: 11,
                    fontWeight: 600, color: "#718096", textTransform: "uppercase", letterSpacing: "0.4px",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {skills.map(s => {
                const badge = SOURCE_BADGE[s.source] || SOURCE_BADGE.legacy;
                const steps = Array.isArray(s.steps_mapping) ? s.steps_mapping : [];
                const inputs = Array.isArray(s.input_schema) ? s.input_schema : [];
                const outputs = Array.isArray(s.output_schema) ? s.output_schema : [];
                const inputKeys = inputs.map((f) => f.key || f.name || "?").join(", ") || "—";
                const isExpanded = expandedId === s.id;

                return (
                  <tr key={s.id} style={{ borderBottom: isExpanded ? "none" : "1px solid #f7f8fc" }}>
                    <td colSpan={8} style={{ padding: 0 }}>
                      {/* Summary row */}
                      <div
                        onClick={() => toggleExpand(s.id)}
                        style={{
                          display: "grid", gridTemplateColumns: "60px 1fr 120px 70px 50px 120px 110px 60px",
                          alignItems: "center", cursor: "pointer",
                          background: isExpanded ? "#f0f7ff" : "transparent",
                          borderBottom: isExpanded ? "1px solid #e2e8f0" : "none",
                          transition: "background 0.1s",
                        }}
                      >
                        <span style={{ padding: "12px 14px", color: "#a0aec0", fontFamily: "monospace" }}>#{s.id}</span>
                        <div style={{ padding: "12px 14px" }}>
                          <div style={{ fontWeight: 600, color: "#1a202c" }}>{s.name}</div>
                          <div style={{ fontSize: 11, color: "#718096", marginTop: 2 }}>
                            {(s.description || s.auto_check_description || "").slice(0, 80)}
                          </div>
                        </div>
                        <span style={{ padding: "12px 14px" }}>
                          <span style={{
                            background: badge.bg, color: badge.color,
                            fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 10,
                          }}>{badge.label}</span>
                        </span>
                        <span style={{ padding: "12px 14px", fontSize: 11 }}>
                          {s.visibility === "public"
                            ? <span style={{ color: "#38a169" }}>Public</span>
                            : <span style={{ color: "#a0aec0" }}>Private</span>}
                        </span>
                        <span style={{ padding: "12px 14px", color: "#4a5568" }}>{steps.length}</span>
                        <span style={{ padding: "12px 14px", fontSize: 11, color: "#718096", fontFamily: "monospace" }}>
                          {inputKeys}
                        </span>
                        <span style={{ padding: "12px 14px", fontSize: 11, color: "#718096" }}>
                          {new Date(s.updated_at).toLocaleString("zh-TW", {
                            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                          })}
                        </span>
                        <span style={{ padding: "12px 14px" }}>
                          <button
                            onClick={e => { e.stopPropagation(); handleDelete(s.id, s.name); }}
                            style={{
                              padding: "4px 10px", fontSize: 11,
                              border: "1px solid #fc8181", background: "#fff5f5",
                              color: "#c53030", borderRadius: 5, cursor: "pointer",
                            }}
                          >刪除</button>
                        </span>
                      </div>

                      {/* Expanded detail panel */}
                      {isExpanded && (
                        <div style={{ padding: "16px 20px 20px", background: "#fafbfe", borderBottom: "2px solid #e2e8f0" }}>
                          {/* Tab bar */}
                          <div style={{ display: "flex", gap: 4, marginBottom: 14 }}>
                            {([
                              { key: "steps" as const, label: `Steps (${steps.length})` },
                              { key: "schema" as const, label: "Input / Output Schema" },
                              { key: "meta" as const, label: "Metadata" },
                            ]).map(t => (
                              <button
                                key={t.key}
                                onClick={() => setTab(t.key)}
                                style={{
                                  padding: "5px 14px", fontSize: 11, fontWeight: 600, borderRadius: 5, cursor: "pointer",
                                  border: tab === t.key ? "1px solid #3182ce" : "1px solid #e2e8f0",
                                  background: tab === t.key ? "#ebf8ff" : "#fff",
                                  color: tab === t.key ? "#2b6cb0" : "#718096",
                                }}
                              >{t.label}</button>
                            ))}
                          </div>

                          {tab === "steps" && <StepsViewer steps={steps as StepEntry[]} />}

                          {tab === "schema" && (
                            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                              <div>
                                <SectionTitle>Input Schema</SectionTitle>
                                <SchemaTable fields={inputs as SchemaField[]} label="Input" />
                              </div>
                              <div>
                                <SectionTitle>Output Schema</SectionTitle>
                                <SchemaTable fields={outputs as SchemaField[]} label="Output" />
                              </div>
                            </div>
                          )}

                          {tab === "meta" && <MetadataGrid skill={s} />}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ marginTop: 16, fontSize: 12, color: "#a0aec0" }}>
        <strong>類型說明：</strong>
        {" "}My Skill = 使用者建立的常用分析工具（Chat promote 或手動建立）；
        {" "}Diagnostic Rule = 告警觸發的深度診斷規則；
        {" "}Auto-Patrol = Event Poller 自動觸發的巡檢技能；
        {" "}Legacy = 舊版技能
      </div>
    </div>
  );
}
