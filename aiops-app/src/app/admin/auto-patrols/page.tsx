"use client";

import { useEffect, useState } from "react";
import { RenderMiddleware, type OutputSchemaField } from "@/components/operations/SkillOutputRenderer";

// ── Types ─────────────────────────────────────────────────────────────────────

type EventType  = { id: number; name: string; description?: string };
type StepMapping = { step_id: string; nl_segment: string; python_code: string };
type TargetScopeType = "event_driven" | "all_equipment" | "equipment_list";

type AutoPatrol = {
  id: number; name: string; description: string; auto_check_description: string;
  skill_id: number; trigger_mode: "event" | "schedule";
  event_type_id: number | null; cron_expr: string | null;
  data_context: "recent_ooc" | "active_lots" | "tool_status" | null;
  target_scope: { type: TargetScopeType; equipment_ids: string[] } | null;
  alarm_severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | null;
  alarm_title: string | null; is_active: boolean;
};

type StepResult = {
  step_id: string; nl_segment: string; status: string;
  output?: unknown; error?: string;
};

type TryRunResult = {
  success: boolean;
  step_results?: StepResult[];
  findings: { condition_met: boolean; evidence: Record<string, unknown>; impacted_lots: string[] } | null;
  total_elapsed_ms: number;
  error?: string;
};

type ExecutionLog = {
  id: number;
  triggered_by: string;
  status: "success" | "error" | "timeout";
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  findings: {
    condition_met: boolean;
    summary?: string;
    outputs?: Record<string, unknown>;
    evidence?: Record<string, unknown>;
    impacted_lots?: string[];
    step_results?: StepResult[];
  } | null;
  event_context: Record<string, unknown> | null;
  error_message: string | null;
  output_schema: OutputSchemaField[];
};

type PeriodPreset = "1h" | "24h" | "7d" | "30d";

const PERIOD_PRESETS: { label: string; value: PeriodPreset; hours: number }[] = [
  { label: "過去1小時",  value: "1h",  hours: 1   },
  { label: "過去24小時", value: "24h", hours: 24  },
  { label: "過去7天",   value: "7d",  hours: 168 },
  { label: "過去30天",  value: "30d", hours: 720 },
];

function sinceISO(hours: number): string {
  return new Date(Date.now() - hours * 3600 * 1000).toISOString();
}

// ── Constants ─────────────────────────────────────────────────────────────────

const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;

const SEV_COLOR: Record<string, { bg: string; color: string }> = {
  CRITICAL: { bg: "#fef2f2", color: "#dc2626" },
  HIGH:     { bg: "#fff7ed", color: "#ea580c" },
  MEDIUM:   { bg: "#fefce8", color: "#ca8a04" },
  LOW:      { bg: "#f8fafc", color: "#64748b" },
};

const SCHEDULE_PRESETS = [
  { label: "每 1 小時",   value: "1h",    cron: "0 * * * *"    },
  { label: "每 2 小時",   value: "2h",    cron: "0 */2 * * *"  },
  { label: "每 4 小時",   value: "4h",    cron: "0 */4 * * *"  },
  { label: "每 6 小時",   value: "6h",    cron: "0 */6 * * *"  },
  { label: "每 12 小時",  value: "12h",   cron: "0 */12 * * *" },
  { label: "每天指定時間", value: "daily", cron: ""             },
];

function cronFromPreset(preset: string, dailyTime: string): string {
  if (preset === "daily") {
    const [hh, mm] = dailyTime.split(":").map(Number);
    return `${mm ?? 0} ${hh ?? 8} * * *`;
  }
  return SCHEDULE_PRESETS.find(p => p.value === preset)?.cron ?? "0 * * * *";
}

// ── Styles ────────────────────────────────────────────────────────────────────

const S = {
  btn:  (c: string, dis = false): React.CSSProperties => ({
    padding: "7px 16px", borderRadius: 6, border: "none",
    cursor: dis ? "default" : "pointer", fontSize: 13, fontWeight: 500,
    background: dis ? "#a0aec0" : c, color: "#fff", opacity: dis ? 0.7 : 1,
  }),
  btnSm: (c: string): React.CSSProperties => ({
    padding: "4px 10px", borderRadius: 5, border: "none", cursor: "pointer",
    fontSize: 12, fontWeight: 500, background: c, color: "#fff",
  }),
  label: { display: "block", fontSize: 12, fontWeight: 600, color: "#4a5568", marginBottom: 4 } as React.CSSProperties,
  input: {
    width: "100%", padding: "7px 10px", border: "1px solid #cbd5e0",
    borderRadius: 6, fontSize: 13, color: "#2d3748", boxSizing: "border-box" as const,
  },
  textarea: {
    width: "100%", padding: "7px 10px", border: "1px solid #cbd5e0",
    borderRadius: 6, fontSize: 13, color: "#2d3748", resize: "vertical" as const,
    boxSizing: "border-box" as const,
  },
  select: {
    width: "100%", padding: "7px 10px", border: "1px solid #cbd5e0",
    borderRadius: 6, fontSize: 13, color: "#2d3748", background: "#fff",
    boxSizing: "border-box" as const,
  },
  row:     { marginBottom: 14 } as React.CSSProperties,
  section: {
    borderTop: "1px solid #e2e8f0", paddingTop: 16, marginTop: 16,
  } as React.CSSProperties,
  sectionTitle: {
    fontSize: 13, fontWeight: 700, color: "#2d3748", marginBottom: 12,
    display: "flex", alignItems: "center", gap: 6,
  } as React.CSSProperties,
  table: { width: "100%", borderCollapse: "collapse" as const, fontSize: 13 },
  th: {
    background: "#f7fafc", borderBottom: "2px solid #e2e8f0",
    padding: "8px 12px", textAlign: "left" as const, fontWeight: 600, color: "#4a5568",
  },
  td: { padding: "10px 12px", borderBottom: "1px solid #edf2f7", color: "#2d3748" },
};

type InputSchemaField  = { key: string; type: string; required: boolean; default?: unknown; description: string };

// ── Form state ────────────────────────────────────────────────────────────────

function emptyForm() {
  return {
    name: "", description: "", auto_check_description: "",
    trigger_mode: "event" as "event" | "schedule",
    event_type_id: null as number | null,
    schedule_preset: "1h", daily_time: "08:00",
    data_context: "recent_ooc" as "recent_ooc" | "active_lots" | "tool_status",
    target_scope_type: "all_equipment" as TargetScopeType,
    target_equipment_ids: "",       // comma-separated, only used when type="equipment_list"
    alarm_severity: "HIGH" as "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
    alarm_title: "",
    steps_mapping:  [] as StepMapping[],
    input_schema:   [] as InputSchemaField[],
    output_schema:  [] as OutputSchemaField[],
  };
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AutoPatrolsPage() {
  const [patrols, setPatrols]         = useState<AutoPatrol[]>([]);
  const [eventTypes, setEventTypes]   = useState<EventType[]>([]);
  const [showModal, setShowModal]     = useState(false);
  const [form, setForm]               = useState(emptyForm());

  // Diagnostic plan state
  const [generating, setGenerating]   = useState(false);
  const [proposalSteps, setProposalSteps] = useState<string[]>([]);
  const [showCode, setShowCode]       = useState(false);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [editedCode, setEditedCode]   = useState<Record<string, string>>({});

  // Try-run state
  const [tryRunning, setTryRunning]   = useState(false);
  const [tryRunResult, setTryRunResult] = useState<TryRunResult | null>(null);
  const [mockForm, setMockForm]       = useState<Record<string, string>>({
    equipment_id: "EQP-01", lot_id: "LOT-0001",
    step: "STEP_038", event_time: new Date().toISOString().slice(0, 19) + "Z",
  });

  const [saving, setSaving]           = useState(false);
  const [error, setError]             = useState("");
  const [editingId, setEditingId]     = useState<number | null>(null);

  // History viewer state
  const [historyPatrol, setHistoryPatrol] = useState<AutoPatrol | null>(null);
  const [execLogs, setExecLogs]           = useState<ExecutionLog[]>([]);
  const [logsLoading, setLogsLoading]     = useState(false);
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null);
  const [historyPeriod, setHistoryPeriod] = useState<PeriodPreset>("24h");

  // ── Data loading ──────────────────────────────────────────────────────────

  function reloadList() {
    fetch("/api/admin/auto-patrols").then(r => r.json()).then(d =>
      setPatrols(Array.isArray(d) ? d : [])
    ).catch(() => {});
  }

  useEffect(() => {
    reloadList();
    fetch("/api/admin/skills/event-types").then(r => r.json()).then((d: EventType[]) => {
      const list = Array.isArray(d) ? d : [];
      setEventTypes(list.filter(e => !e.description?.includes("自動建立")));
    }).catch(() => {});
  }, []);

  // ── Modal helpers ─────────────────────────────────────────────────────────

  function openCreate() {
    setEditingId(null);
    setForm(emptyForm());
    setProposalSteps([]);
    setShowCode(false);
    setEditedCode({});
    setSelectedStepId(null);
    setTryRunResult(null);
    setError("");
    setShowModal(true);
  }

  async function openEdit(p: AutoPatrol) {
    setEditingId(p.id);
    setError("");
    setTryRunResult(null);
    setProposalSteps([]);
    setShowCode(false);
    setEditedCode({});
    setSelectedStepId(null);

    // Derive schedule_preset from cron_expr
    const preset = SCHEDULE_PRESETS.find(s => s.cron === (p.cron_expr ?? ""))?.value ?? "1h";

    const scope = p.target_scope;
    const scopeType: TargetScopeType = scope?.type ?? "all_equipment";
    const scopeIds = (scope?.equipment_ids ?? []).join(", ");

    setForm({
      name:                   p.name,
      description:            p.description ?? "",
      auto_check_description: p.auto_check_description ?? "",
      trigger_mode:           p.trigger_mode,
      event_type_id:          p.event_type_id,
      schedule_preset:        preset,
      daily_time:             "08:00",
      data_context:           p.data_context ?? "recent_ooc",
      target_scope_type:      scopeType,
      target_equipment_ids:   scopeIds,
      alarm_severity:         p.alarm_severity ?? "HIGH",
      alarm_title:            p.alarm_title ?? "",
      steps_mapping:          [],
      input_schema:           [],
      output_schema:          [],
    });

    // Load embedded skill steps
    try {
      const res = await fetch(`/api/admin/auto-patrols/${p.id}`);
      const detail = await res.json() as AutoPatrol & { steps_mapping?: StepMapping[]; input_schema?: InputSchemaField[]; output_schema?: OutputSchemaField[] };
      if (detail.steps_mapping && detail.steps_mapping.length > 0) {
        setForm(f => ({ ...f, steps_mapping: detail.steps_mapping!, input_schema: detail.input_schema ?? [], output_schema: detail.output_schema ?? [] }));
        setEditedCode(Object.fromEntries(detail.steps_mapping.map(s => [s.step_id, s.python_code])));
        setProposalSteps(detail.steps_mapping.map(s => s.nl_segment));
        setShowCode(true);
        setSelectedStepId(detail.steps_mapping[0]?.step_id ?? null);
      }
    } catch { /* ignore */ }

    setShowModal(true);
  }

  async function fetchLogs(patrolId: number, period: PeriodPreset) {
    const preset = PERIOD_PRESETS.find(p => p.value === period)!;
    const since = sinceISO(preset.hours);
    setLogsLoading(true);
    setExecLogs([]);
    try {
      const res = await fetch(`/api/admin/auto-patrols/${patrolId}/executions?since=${encodeURIComponent(since)}`);
      const data = await res.json() as ExecutionLog[];
      setExecLogs(Array.isArray(data) ? data : []);
    } catch { /* ignore */ }
    finally { setLogsLoading(false); }
  }

  async function openHistory(p: AutoPatrol) {
    setHistoryPatrol(p);
    setExecLogs([]);
    setExpandedLogId(null);
    setHistoryPeriod("24h");
    await fetchLogs(p.id, "24h");
  }

  // ── AI generate ───────────────────────────────────────────────────────────

  async function handleGenerate() {
    if (!form.auto_check_description.trim()) {
      setError("請先填寫自動檢查描述");
      return;
    }
    setGenerating(true);
    setError("");
    setProposalSteps([]);
    setTryRunResult(null);

    try {
      const res = await fetch("/api/admin/rules/generate-steps", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_check_description: form.auto_check_description.trim() }),
      });
      const data = await res.json() as Record<string, unknown>;
      if (!res.ok) { setError((data.error as string) ?? "AI 設計失敗"); return; }

      const steps   = (data.steps_mapping  as StepMapping[]) ?? [];
      const proposal = (data.proposal_steps as string[]) ?? steps.map(s => s.nl_segment);
      if (steps.length === 0) { setError("AI 未能生成步驟，請修改描述後重試"); return; }

      setForm(f => ({ ...f, steps_mapping: steps, input_schema: (data.input_schema as InputSchemaField[]) ?? [], output_schema: (data.output_schema as OutputSchemaField[]) ?? [] }));
      setProposalSteps(proposal);
      setEditedCode(Object.fromEntries(steps.map(s => [s.step_id, s.python_code])));
      setSelectedStepId(steps[0]?.step_id ?? null);
    } finally {
      setGenerating(false);
    }
  }

  // ── Try-run ───────────────────────────────────────────────────────────────

  async function handleTryRun() {
    setTryRunning(true);
    setTryRunResult(null);
    setError("");

    const finalSteps = form.steps_mapping.map(s => ({
      ...s, python_code: editedCode[s.step_id] ?? s.python_code,
    }));

    // Type-cast mockForm values based on input_schema types
    const typedMockPayload: Record<string, unknown> = {
      event_type: eventTypes.find(e => e.id === form.event_type_id)?.name ?? "OOC",
    };
    for (const [key, raw] of Object.entries(mockForm)) {
      const fieldDef = form.input_schema.find(f => f.key === key);
      const t = fieldDef?.type?.toLowerCase() ?? "";
      if (t === "list" || t === "array") {
        typedMockPayload[key] = raw.split(",").map(s => s.trim()).filter(Boolean);
      } else if (t === "number" || t === "float") {
        typedMockPayload[key] = raw === "" ? null : parseFloat(raw);
      } else if (t === "integer" || t === "int") {
        typedMockPayload[key] = raw === "" ? null : parseInt(raw, 10);
      } else if (t === "boolean" || t === "bool") {
        typedMockPayload[key] = raw === "true" || raw === "1";
      } else {
        typedMockPayload[key] = raw;
      }
    }

    try {
      const res = await fetch("/api/admin/rules/try-run-draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          steps_mapping: finalSteps,
          output_schema: form.output_schema,
          mock_payload: typedMockPayload,
        }),
      });
      const data = await res.json() as TryRunResult;
      setTryRunResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Try-run 失敗");
    } finally {
      setTryRunning(false);
    }
  }

  // ── Save ─────────────────────────────────────────────────────────────────

  async function handleSave() {
    setError("");
    if (!form.name.trim()) { setError("Patrol 名稱必填"); return; }
    if (form.trigger_mode === "event" && !form.event_type_id) { setError("請選擇事件類型"); return; }
    if (form.steps_mapping.length === 0) { setError("請先讓 AI 設計診斷計畫"); return; }

    setSaving(true);
    const finalSteps = form.steps_mapping.map(s => ({
      ...s, python_code: editedCode[s.step_id] ?? s.python_code,
    }));

    const targetScope = form.trigger_mode === "schedule"
      ? {
          type: form.target_scope_type,
          equipment_ids: form.target_scope_type === "equipment_list"
            ? form.target_equipment_ids.split(",").map(s => s.trim()).filter(Boolean)
            : [],
        }
      : { type: "event_driven" as const, equipment_ids: [] };

    const payload = {
      name:                   form.name.trim(),
      description:            form.description.trim(),
      auto_check_description: form.auto_check_description.trim(),
      trigger_mode:           form.trigger_mode,
      event_type_id:          form.trigger_mode === "event" ? form.event_type_id : null,
      cron_expr:              form.trigger_mode === "schedule"
                                ? cronFromPreset(form.schedule_preset, form.daily_time)
                                : null,
      data_context:           form.trigger_mode === "schedule" ? form.data_context : undefined,
      target_scope:           targetScope,
      alarm_severity:         form.alarm_severity,
      alarm_title:            form.alarm_title.trim() || `[Auto-Patrol] ${form.name.trim()}`,
      steps_mapping:          finalSteps,
      input_schema:           form.input_schema,
      output_schema:          form.output_schema,
    };

    try {
      const isEdit = editingId !== null;
      const res = await fetch(
        isEdit ? `/api/admin/auto-patrols/${editingId}` : "/api/admin/auto-patrols",
        {
          method: isEdit ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const data = await res.json();
      if (!res.ok) { setError(data.error ?? (isEdit ? "更新失敗" : "建立失敗")); return; }
      setShowModal(false);
      reloadList();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("確定刪除此 Auto-Patrol？")) return;
    await fetch(`/api/admin/auto-patrols/${id}`, { method: "DELETE" });
    reloadList();
  }

  async function handleTrigger(id: number) {
    const res = await fetch(`/api/admin/auto-patrols/${id}/trigger`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_payload: {} }),
    });
    const data = await res.json() as { condition_met?: boolean; alarm_created?: boolean; error?: string };
    if (data.error) alert(`執行失敗: ${data.error}`);
    else alert(`執行完成 — condition_met: ${data.condition_met}, alarm_created: ${data.alarm_created}`);
    reloadList();
  }

  const canSave = form.name.trim().length > 0 && form.steps_mapping.length > 0;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: "#1a202c" }}>Auto-Patrols</div>
        <button style={S.btn("#6366f1")} onClick={openCreate}>+ 新增 Auto-Patrol</button>
      </div>

      {/* List */}
      <table style={S.table}>
        <thead>
          <tr>
            <th style={S.th}>名稱</th>
            <th style={S.th}>觸發方式</th>
            <th style={S.th}>警報</th>
            <th style={S.th}>狀態</th>
            <th style={S.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {patrols.length === 0 && (
            <tr><td colSpan={5} style={{ ...S.td, color: "#a0aec0", textAlign: "center" }}>尚無 Auto-Patrol</td></tr>
          )}
          {patrols.map(p => (
            <tr key={p.id}>
              <td style={S.td}>
                <div style={{ fontWeight: 600 }}>{p.name}</div>
                {p.auto_check_description && (
                  <div style={{ fontSize: 11, color: "#718096", marginTop: 2, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {p.auto_check_description}
                  </div>
                )}
              </td>
              <td style={{ ...S.td, fontSize: 12 }}>
                {p.trigger_mode === "event"
                  ? `⚡ ${eventTypes.find(e => e.id === p.event_type_id)?.name ?? p.event_type_id ?? "—"}`
                  : `🕐 ${p.cron_expr ?? "—"} · ${
                      p.data_context === "recent_ooc"  ? "OOC 事件" :
                      p.data_context === "active_lots" ? "進行中 Lot" :
                      p.data_context === "tool_status" ? "Tool 狀態" : ""
                    }`}
              </td>
              <td style={S.td}>
                {p.alarm_severity ? (
                  <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 11, background: SEV_COLOR[p.alarm_severity]?.bg, color: SEV_COLOR[p.alarm_severity]?.color }}>
                    {p.alarm_severity}
                  </span>
                ) : "—"}
              </td>
              <td style={S.td}>
                <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 11, background: p.is_active ? "#c6f6d5" : "#fed7d7", color: p.is_active ? "#276749" : "#c53030" }}>
                  {p.is_active ? "啟用" : "停用"}
                </span>
              </td>
              <td style={S.td}>
                <button style={{ ...S.btnSm("#dd6b20"), marginRight: 6 }} onClick={() => handleTrigger(p.id)}>執行</button>
                <button style={{ ...S.btnSm("#3182ce"), marginRight: 6 }} onClick={() => openEdit(p)}>編輯</button>
                <button style={{ ...S.btnSm("#6366f1"), marginRight: 6 }} onClick={() => openHistory(p)}>紀錄</button>
                <button style={S.btnSm("#e53e3e")} onClick={() => handleDelete(p.id)}>刪除</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* ── Modal (single-page form) ── */}
      {showModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "#fff", borderRadius: 12, padding: 28, width: 760, maxHeight: "92vh", overflowY: "auto", boxShadow: "0 8px 32px rgba(0,0,0,0.2)" }}>

            <h3 style={{ margin: "0 0 20px", fontSize: 17, fontWeight: 700 }}>
              {editingId !== null ? "編輯 Auto-Patrol" : "新增 Auto-Patrol"}
            </h3>

            {/* ── 基本資訊 ── */}
            <div style={{ fontSize: 13, fontWeight: 700, color: "#4a5568", marginBottom: 12 }}>① 基本資訊</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
              <div>
                <label style={S.label}>Patrol 名稱 *</label>
                <input style={S.input} value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. SPC OOC 週期監控" />
              </div>
              <div>
                <label style={S.label}>描述</label>
                <input style={S.input} value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  placeholder="簡述監控目的" />
              </div>
            </div>

            {/* ── 觸發方式 ── */}
            <div style={S.section}>
              <div style={S.sectionTitle}>② 觸發方式</div>
              <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
                {(["event", "schedule"] as const).map(mode => (
                  <button key={mode} onClick={() => setForm(f => ({ ...f, trigger_mode: mode }))}
                    style={{
                      flex: 1, padding: "10px 16px", borderRadius: 8, cursor: "pointer",
                      border: `2px solid ${form.trigger_mode === mode ? "#6366f1" : "#e2e8f0"}`,
                      background: form.trigger_mode === mode ? "#eef2ff" : "#fff",
                      color: form.trigger_mode === mode ? "#4338ca" : "#4a5568",
                      fontWeight: form.trigger_mode === mode ? 600 : 400, fontSize: 13,
                    }}>
                    {mode === "event" ? "⚡ 事件觸發" : "🕐 排程觸發"}
                    <div style={{ fontSize: 11, fontWeight: 400, marginTop: 3, color: "#718096" }}>
                      {mode === "event" ? "OOC 事件發生時立即執行" : "依固定週期定時執行"}
                    </div>
                  </button>
                ))}
              </div>

              {form.trigger_mode === "event" && (
                <div style={S.row}>
                  <label style={S.label}>事件類型 *</label>
                  <select style={S.select}
                    value={form.event_type_id != null ? String(form.event_type_id) : ""}
                    onChange={e => setForm(f => ({ ...f, event_type_id: e.target.value ? Number(e.target.value) : null }))}>
                    <option value="">— 選擇事件類型 —</option>
                    {eventTypes.map(et => (
                      <option key={et.id} value={String(et.id)}>{et.name}</option>
                    ))}
                  </select>
                </div>
              )}

              {form.trigger_mode === "schedule" && (
                <>
                  <div style={S.row}>
                    <label style={S.label}>執行頻率</label>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
                      {SCHEDULE_PRESETS.map(preset => (
                        <button key={preset.value} onClick={() => setForm(f => ({ ...f, schedule_preset: preset.value }))}
                          style={{
                            padding: "8px 12px", borderRadius: 6, cursor: "pointer", fontSize: 12,
                            border: `1px solid ${form.schedule_preset === preset.value ? "#6366f1" : "#e2e8f0"}`,
                            background: form.schedule_preset === preset.value ? "#eef2ff" : "#fff",
                            color: form.schedule_preset === preset.value ? "#4338ca" : "#4a5568",
                            fontWeight: form.schedule_preset === preset.value ? 600 : 400,
                          }}>
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  {form.schedule_preset === "daily" && (
                    <div style={S.row}>
                      <label style={S.label}>每天執行時間 (UTC)</label>
                      <input type="time" style={{ ...S.input, width: 140 }}
                        value={form.daily_time}
                        onChange={e => setForm(f => ({ ...f, daily_time: e.target.value }))} />
                    </div>
                  )}
                  <div style={{ fontSize: 11, color: "#718096" }}>
                    Cron: <code>{cronFromPreset(form.schedule_preset, form.daily_time)}</code>
                  </div>

                  {/* data_context selector */}
                  <div style={{ ...S.row, marginTop: 12 }}>
                    <label style={S.label}>資料來源 *</label>
                    <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
                      {([
                        { value: "recent_ooc",  label: "📊 近期 OOC 事件",   desc: "拉取最近 N 筆 OOC 紀錄作為診斷上下文" },
                        { value: "active_lots", label: "🏭 進行中 Lot",       desc: "拉取目前在線上的 Lot 清單" },
                        { value: "tool_status", label: "🔧 Tool 狀態快照",    desc: "拉取所有 Tool 目前的健康狀態" },
                      ] as const).map(opt => (
                        <label key={opt.value} style={{
                          display: "flex", alignItems: "flex-start", gap: 8, cursor: "pointer",
                          padding: "8px 12px", borderRadius: 6,
                          border: `1px solid ${form.data_context === opt.value ? "#6366f1" : "#e2e8f0"}`,
                          background: form.data_context === opt.value ? "#eef2ff" : "#fff",
                        }}>
                          <input type="radio" name="data_context" value={opt.value}
                            checked={form.data_context === opt.value}
                            onChange={() => setForm(f => ({ ...f, data_context: opt.value }))}
                            style={{ marginTop: 2 }} />
                          <div>
                            <div style={{ fontSize: 13, fontWeight: form.data_context === opt.value ? 600 : 400, color: form.data_context === opt.value ? "#4338ca" : "#2d3748" }}>
                              {opt.label}
                            </div>
                            <div style={{ fontSize: 11, color: "#718096" }}>{opt.desc}</div>
                          </div>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* target_scope: who to run the Skill against */}
                  <div style={{ ...S.row, marginTop: 12 }}>
                    <label style={S.label}>掃描範圍 <span style={{ fontWeight: 400, color: "#718096" }}>（每個目標各跑一次 Skill）</span></label>
                    <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
                      {([
                        { value: "all_equipment",  label: "🏭 所有機台",   desc: "自動從 OntologySimulator 拉取全部機台，逐台執行" },
                        { value: "equipment_list", label: "📋 指定清單",   desc: "手動輸入要掃描的機台 ID，逐台執行" },
                      ] as const).map(opt => (
                        <label key={opt.value} style={{
                          display: "flex", alignItems: "flex-start", gap: 8, cursor: "pointer",
                          padding: "8px 12px", borderRadius: 6,
                          border: `1px solid ${form.target_scope_type === opt.value ? "#0891b2" : "#e2e8f0"}`,
                          background: form.target_scope_type === opt.value ? "#ecfeff" : "#fff",
                        }}>
                          <input type="radio" name="target_scope_type" value={opt.value}
                            checked={form.target_scope_type === opt.value}
                            onChange={() => setForm(f => ({ ...f, target_scope_type: opt.value }))}
                            style={{ marginTop: 2 }} />
                          <div>
                            <div style={{ fontSize: 13, fontWeight: form.target_scope_type === opt.value ? 600 : 400, color: form.target_scope_type === opt.value ? "#0e7490" : "#2d3748" }}>
                              {opt.label}
                            </div>
                            <div style={{ fontSize: 11, color: "#718096" }}>{opt.desc}</div>
                          </div>
                        </label>
                      ))}
                    </div>
                    {form.target_scope_type === "equipment_list" && (
                      <div style={{ marginTop: 8 }}>
                        <label style={{ fontSize: 11, color: "#4a5568", display: "block", marginBottom: 4 }}>
                          機台 ID 清單（逗號分隔）
                        </label>
                        <input
                          style={S.input}
                          value={form.target_equipment_ids}
                          onChange={e => setForm(f => ({ ...f, target_equipment_ids: e.target.value }))}
                          placeholder="e.g. EQP-01, EQP-03, EQP-07"
                        />
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* ── 警報設定 ── */}
            <div style={S.section}>
              <div style={S.sectionTitle}>③ 警報設定</div>
              <div style={{ ...S.row }}>
                <label style={S.label}>嚴重程度</label>
                <div style={{ display: "flex", gap: 8 }}>
                  {SEVERITIES.map(sev => (
                    <button key={sev} onClick={() => setForm(f => ({ ...f, alarm_severity: sev }))}
                      style={{
                        flex: 1, padding: "8px", borderRadius: 8, cursor: "pointer",
                        border: `2px solid ${form.alarm_severity === sev ? SEV_COLOR[sev].color : "#e2e8f0"}`,
                        background: form.alarm_severity === sev ? SEV_COLOR[sev].bg : "#fff",
                        color: SEV_COLOR[sev].color,
                        fontWeight: form.alarm_severity === sev ? 700 : 400, fontSize: 12,
                      }}>
                      {sev}
                    </button>
                  ))}
                </div>
              </div>
              <div style={S.row}>
                <label style={S.label}>警報標題</label>
                <input style={S.input} value={form.alarm_title}
                  onChange={e => setForm(f => ({ ...f, alarm_title: e.target.value }))}
                  placeholder={`[Auto-Patrol] ${form.name || "未命名"}`} />
              </div>
            </div>

            {/* ── 診斷計畫 ── */}
            <div style={S.section}>
              <div style={S.sectionTitle}>④ 診斷計畫</div>

              <div style={S.row}>
                <label style={S.label}>自動檢查描述</label>
                <textarea style={{ ...S.textarea, minHeight: 70 }}
                  value={form.auto_check_description}
                  onChange={e => setForm(f => ({ ...f, auto_check_description: e.target.value }))}
                  placeholder="描述此 Patrol 要自動檢查什麼，例如：Tool 最近 5 次 Process 中超過 3 次 OOC" />
                <button
                  style={{ ...S.btn(generating || !form.auto_check_description.trim() ? "#a0aec0" : "#6b46c1", generating || !form.auto_check_description.trim()), marginTop: 8, fontSize: 12 }}
                  disabled={generating || !form.auto_check_description.trim()}
                  onClick={handleGenerate}>
                  {generating ? "⏳ AI 設計中..." : "✨ 讓 AI 設計監控計畫"}
                </button>
              </div>

              {/* Proposal steps */}
              {proposalSteps.length > 0 && (
                <div style={{ ...S.row, background: "#f7fafc", borderRadius: 8, padding: 12, border: "1px solid #e2e8f0" }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "#4a5568", marginBottom: 8 }}>診斷計畫</div>
                  <ol style={{ margin: 0, paddingLeft: 18 }}>
                    {proposalSteps.map((s, i) => (
                      <li key={i} style={{ fontSize: 13, color: "#2d3748", marginBottom: 4 }}>{s}</li>
                    ))}
                  </ol>
                  <button style={{ ...S.btnSm("#4a5568"), marginTop: 8, fontSize: 11 }}
                    onClick={() => setShowCode(v => !v)}>
                    {showCode ? "▲ 隱藏程式碼" : "▼ 查看/編輯程式碼"}
                  </button>
                </div>
              )}

              {/* Code editor */}
              {showCode && form.steps_mapping.length > 0 && (
                <div style={{ ...S.row, border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden" }}>
                  <div style={{ display: "flex", background: "#edf2f7", overflowX: "auto" as const }}>
                    {form.steps_mapping.map(s => (
                      <button key={s.step_id} onClick={() => setSelectedStepId(s.step_id)}
                        style={{
                          padding: "6px 14px", border: "none", cursor: "pointer", fontSize: 12,
                          background: selectedStepId === s.step_id ? "#fff" : "transparent",
                          color: selectedStepId === s.step_id ? "#6366f1" : "#4a5568",
                          borderBottom: selectedStepId === s.step_id ? "2px solid #6366f1" : "none",
                          fontWeight: selectedStepId === s.step_id ? 600 : 400,
                        }}>
                        {s.step_id}
                      </button>
                    ))}
                  </div>
                  {selectedStepId && (
                    <div style={{ padding: 12 }}>
                      <div style={{ fontSize: 11, color: "#718096", marginBottom: 6 }}>
                        {form.steps_mapping.find(s => s.step_id === selectedStepId)?.nl_segment}
                      </div>
                      <textarea
                        style={{ ...S.textarea, minHeight: 140, fontFamily: "monospace", fontSize: 12 }}
                        value={editedCode[selectedStepId] ?? ""}
                        onChange={e => setEditedCode(prev => ({ ...prev, [selectedStepId]: e.target.value }))}
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Try-run */}
              {form.steps_mapping.length > 0 && (
                <div style={{ background: "#fffbeb", border: "1px solid #f6e05e", borderRadius: 8, padding: 12, marginBottom: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "#744210", marginBottom: 8 }}>Try-Run 測試</div>
                  {form.input_schema.length > 0 ? (
                    /* Dynamic fields from input_schema */
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8, marginBottom: 10 }}>
                      {form.input_schema.map(f => (
                        <div key={f.key}>
                          <label style={{ fontSize: 11, color: "#744210", display: "block", marginBottom: 2 }}>
                            {f.key}{f.required && <span style={{ color: "#e53e3e" }}> *</span>}
                          </label>
                          <input
                            style={{ ...S.input, fontSize: 12 }}
                            placeholder={String(f.default ?? f.description)}
                            value={mockForm[f.key] ?? ""}
                            onChange={e => setMockForm(m => ({ ...m, [f.key]: e.target.value }))}
                          />
                          {f.description && <div style={{ fontSize: 10, color: "#a0aec0", marginTop: 2 }}>{f.description}</div>}
                        </div>
                      ))}
                    </div>
                  ) : (
                    /* Fallback: no input_schema yet */
                    <>
                      <div style={{ marginBottom: 8 }}>
                        <label style={{ fontSize: 11, color: "#744210", display: "block", marginBottom: 2 }}>equipment_id</label>
                        <input style={{ ...S.input, fontSize: 12, maxWidth: 240 }}
                          value={mockForm.equipment_id ?? ""}
                          onChange={e => setMockForm(f => ({ ...f, equipment_id: e.target.value }))} />
                      </div>
                      <details style={{ marginBottom: 10 }}>
                        <summary style={{ fontSize: 11, color: "#92610a", cursor: "pointer", userSelect: "none" as const }}>進階參數（lot_id / step / event_time）</summary>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 8 }}>
                          {["lot_id", "step", "event_time"].map(k => (
                            <div key={k}>
                              <label style={{ fontSize: 11, color: "#744210", display: "block", marginBottom: 2 }}>{k}</label>
                              <input style={{ ...S.input, fontSize: 12 }}
                                value={mockForm[k] ?? ""}
                                onChange={e => setMockForm(f => ({ ...f, [k]: e.target.value }))} />
                            </div>
                          ))}
                        </div>
                      </details>
                    </>
                  )}
                  <button style={S.btn("#dd6b20", tryRunning)} disabled={tryRunning} onClick={handleTryRun}>
                    {tryRunning ? "⏳ 執行中..." : "▶ Try Run"}
                  </button>
                </div>
              )}

              {/* Try-run results */}
              {tryRunResult && (
                <div style={{ border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden", marginBottom: 14 }}>
                  {/* Header */}
                  <div style={{
                    padding: "8px 14px", fontWeight: 600, fontSize: 13,
                    background: tryRunResult.success ? "#f0fff4" : "#fff5f5",
                    color: tryRunResult.success ? "#276749" : "#c53030",
                    borderBottom: "1px solid #e2e8f0",
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                  }}>
                    <span>{tryRunResult.success ? "✅ 執行成功" : "❌ 執行失敗"}</span>
                    {(tryRunResult.total_elapsed_ms ?? 0) > 0 && (
                      <span style={{ fontSize: 11, fontWeight: 400, color: "#718096" }}>
                        {tryRunResult.total_elapsed_ms.toFixed(0)} ms
                      </span>
                    )}
                  </div>

                  {/* Step-by-step console */}
                  {tryRunResult.step_results && tryRunResult.step_results.length > 0 && (
                    <div style={{ padding: "10px 14px", borderBottom: "1px solid #e2e8f0", background: "#1a202c" }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                        執行日誌
                      </div>
                      {tryRunResult.step_results.map((sr, i) => (
                        <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 4, fontSize: 12 }}>
                          <span style={{ flexShrink: 0, marginTop: 1 }}>
                            {sr.status === "ok" ? "✅" : "❌"}
                          </span>
                          <div>
                            <span style={{ color: "#68d391", fontFamily: "monospace" }}>{sr.step_id}</span>
                            <span style={{ color: "#a0aec0" }}> — {sr.nl_segment}</span>
                            {sr.error && (
                              <div style={{ color: "#fc8181", fontFamily: "monospace", fontSize: 11, marginTop: 2 }}>
                                {sr.error}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Evidence (structured via RenderMiddleware) */}
                  {tryRunResult.findings && (
                    <div style={{ padding: "12px 14px" }}>
                      <RenderMiddleware findings={tryRunResult.findings} outputSchema={form.output_schema} />
                    </div>
                  )}

                  {tryRunResult.error && !tryRunResult.findings && (
                    <div style={{ padding: "10px 14px", color: "#c53030", fontSize: 13 }}>{tryRunResult.error}</div>
                  )}
                </div>
              )}
            </div>

            {error && <div style={{ color: "#c53030", fontSize: 12, marginBottom: 12 }}>{error}</div>}

            {/* Action buttons */}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, paddingTop: 16, borderTop: "1px solid #e2e8f0" }}>
              <button style={S.btn("#a0aec0")} onClick={() => setShowModal(false)}>取消</button>
              <button style={S.btn(canSave && !saving ? "#38a169" : "#a0aec0", !canSave || saving)}
                disabled={!canSave || saving} onClick={handleSave}>
                {saving ? "儲存中..." : editingId !== null ? "✓ 更新 Auto-Patrol" : "✓ 儲存 Auto-Patrol"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── History Drawer ── */}
      {historyPatrol && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1100, display: "flex", justifyContent: "flex-end" }}>
          <div style={{ width: 620, background: "#fff", height: "100%", display: "flex", flexDirection: "column" as const, boxShadow: "-4px 0 24px rgba(0,0,0,0.15)" }}>

            {/* Drawer header */}
            <div style={{ padding: "18px 24px 14px", borderBottom: "1px solid #e2e8f0", flexShrink: 0 }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#1a202c" }}>執行紀錄</div>
                  <div style={{ fontSize: 12, color: "#718096", marginTop: 2 }}>{historyPatrol.name}</div>
                </div>
                <button onClick={() => setHistoryPatrol(null)} style={{ border: "none", background: "none", fontSize: 20, cursor: "pointer", color: "#718096", lineHeight: 1 }}>×</button>
              </div>
              {/* Period selector */}
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                {PERIOD_PRESETS.map(p => (
                  <button key={p.value} onClick={async () => {
                    setHistoryPeriod(p.value);
                    setExpandedLogId(null);
                    await fetchLogs(historyPatrol.id, p.value);
                  }} style={{
                    padding: "4px 10px", borderRadius: 6, border: "1px solid",
                    cursor: "pointer", fontSize: 12,
                    borderColor: historyPeriod === p.value ? "#6366f1" : "#e2e8f0",
                    background: historyPeriod === p.value ? "#eef2ff" : "#fff",
                    color: historyPeriod === p.value ? "#4338ca" : "#4a5568",
                    fontWeight: historyPeriod === p.value ? 600 : 400,
                  }}>{p.label}</button>
                ))}
                {!logsLoading && (
                  <span style={{ fontSize: 11, color: "#a0aec0", marginLeft: 4 }}>共 {execLogs.length} 筆</span>
                )}
              </div>
            </div>

            {/* Logs list */}
            <div style={{ flex: 1, overflowY: "auto" as const, padding: "14px 24px" }}>
              {logsLoading && (
                <div style={{ color: "#a0aec0", fontSize: 13, textAlign: "center", marginTop: 40 }}>載入中...</div>
              )}
              {!logsLoading && execLogs.length === 0 && (
                <div style={{ color: "#a0aec0", fontSize: 13, textAlign: "center", marginTop: 40 }}>
                  此期間內無執行紀錄
                </div>
              )}
              {execLogs.map(log => {
                const isExpanded = expandedLogId === log.id;
                const condMet = log.findings?.condition_met;
                return (
                  <div key={log.id} style={{ marginBottom: 10, border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden" }}>
                    {/* Row header */}
                    <div
                      onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                      style={{
                        padding: "10px 14px", cursor: "pointer",
                        display: "flex", alignItems: "center", gap: 10,
                        background: isExpanded ? "#f0f4ff" : "#f7fafc",
                      }}
                    >
                      <span style={{ fontSize: 14, flexShrink: 0 }}>
                        {log.status === "success" ? "✅" : "❌"}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "#2d3748", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" as const }}>
                          <span>
                            {log.triggered_by === "event" ? "⚡ 事件觸發" :
                             log.triggered_by === "schedule" ? "🕐 排程觸發" : "▶ 手動執行"}
                          </span>
                          {condMet !== undefined && (
                            <span style={{
                              padding: "1px 7px", borderRadius: 8, fontSize: 11,
                              background: condMet ? "#fff5f5" : "#f0fff4",
                              color: condMet ? "#c53030" : "#276749",
                              border: `1px solid ${condMet ? "#feb2b2" : "#9ae6b4"}`,
                            }}>
                              {condMet ? "⚠ 條件成立" : "✓ 正常"}
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 11, color: "#718096", marginTop: 2 }}>
                          {log.started_at ? new Date(log.started_at).toLocaleString("zh-TW") : "—"}
                          {log.duration_ms != null && (
                            <span style={{ marginLeft: 6 }}>{log.duration_ms} ms</span>
                          )}
                        </div>
                        {/* Summary preview when collapsed */}
                        {!isExpanded && log.findings?.summary && (
                          <div style={{ fontSize: 11, color: "#4a5568", marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const }}>
                            {log.findings.summary}
                          </div>
                        )}
                      </div>
                      <span style={{ fontSize: 11, color: "#a0aec0", flexShrink: 0 }}>{isExpanded ? "▲" : "▼"}</span>
                    </div>

                    {/* Expanded detail */}
                    {isExpanded && (
                      <div style={{ borderTop: "1px solid #e2e8f0" }}>
                        {/* Error */}
                        {log.error_message && (
                          <div style={{ padding: "10px 14px", background: "#fff5f5", borderBottom: "1px solid #fed7d7", fontSize: 12, color: "#c53030" }}>
                            {log.error_message}
                          </div>
                        )}

                        {/* Step console */}
                        {log.findings?.step_results && log.findings.step_results.length > 0 && (
                          <div style={{ padding: "10px 14px", background: "#1a202c", borderBottom: "1px solid #2d3748" }}>
                            <div style={{ fontSize: 11, fontWeight: 600, color: "#68d391", marginBottom: 6, textTransform: "uppercase" as const, letterSpacing: "0.5px" }}>執行日誌</div>
                            {log.findings.step_results.map((sr, i) => (
                              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 4, fontSize: 12 }}>
                                <span style={{ flexShrink: 0 }}>{sr.status === "ok" ? "✅" : "❌"}</span>
                                <div>
                                  <span style={{ color: "#68d391", fontFamily: "monospace" }}>{sr.step_id}</span>
                                  <span style={{ color: "#a0aec0" }}> — {sr.nl_segment}</span>
                                  {sr.error && <div style={{ color: "#fc8181", fontFamily: "monospace", fontSize: 11, marginTop: 2 }}>{sr.error}</div>}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Findings */}
                        {log.findings && (
                          <div style={{ padding: "12px 14px", borderBottom: "1px solid #f7fafc" }}>
                            <RenderMiddleware findings={log.findings} outputSchema={log.output_schema} />
                          </div>
                        )}

                        {/* Event context */}
                        {log.event_context && Object.keys(log.event_context).length > 0 && (
                          <details style={{ padding: "8px 14px" }}>
                            <summary style={{ fontSize: 11, color: "#718096", cursor: "pointer", userSelect: "none" as const }}>事件上下文</summary>
                            <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap" as const, gap: 6 }}>
                              {Object.entries(log.event_context).map(([k, v]) => (
                                <span key={k} style={{ fontSize: 11, background: "#edf2f7", borderRadius: 4, padding: "2px 8px", color: "#4a5568" }}>
                                  <strong>{k}:</strong> {v !== null && typeof v === "object" ? JSON.stringify(v) : String(v)}
                                </span>
                              ))}
                            </div>
                          </details>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
