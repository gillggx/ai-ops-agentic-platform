"use client";

import { useEffect, useState } from "react";
import { RenderMiddleware, type OutputSchemaField, type ChartDSL } from "@/components/operations/SkillOutputRenderer";
import { ClarifyDialog, type ClarifyQuestion, type ClarifyAnswer } from "@/components/skill-builder/ClarifyDialog";

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
  findings: { condition_met: boolean; summary?: string; outputs?: Record<string, unknown>; evidence?: Record<string, unknown>; impacted_lots: string[] } | null;
  charts?: ChartDSL[] | null;
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
    fontSize: 12, fontWeight: 500, background: c, color: "#fff", whiteSpace: "nowrap",
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
    // Phase 4-B: pipeline-based binding
    execution_mode: "skill" as "skill" | "pipeline",
    pipeline_id: null as number | null,
    input_binding: {} as Record<string, string>,
  };
}

// ── Page ──────────────────────────────────────────────────────────────────────

// ── Feedback / Auto-Fix Panel ─────────────────────────────────────────────────

function AutoPatrolFixPanel({ skillId, errorMessage, success, onFixed }: {
  skillId: number; errorMessage: string; success: boolean; onFixed: () => void;
}) {
  const [feedback, setFeedback] = useState("");
  const [fixing, setFixing] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  async function handleFix() {
    setFixing(true);
    setResult(null);
    try {
      const res = await fetch(`/api/admin/rules/${skillId}/fix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ error_message: errorMessage, user_feedback: feedback }),
      });
      const data = await res.json();
      const r = data?.data ?? data;
      if (r?.success) {
        setResult(`修正完成（${r.steps_count} steps）。請重新 Try Run。`);
        onFixed();
      } else {
        setResult(`修正失敗：${r?.error || "未知錯誤"}`);
      }
    } catch (e) {
      setResult(`修正失敗：${e}`);
    } finally {
      setFixing(false);
    }
  }

  return (
    <div style={{
      background: "#fffbeb", border: "1px solid #fbbf24", borderRadius: 8,
      padding: "10px 12px",
    }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#92400e", marginBottom: 6 }}>
        {success ? "結果 Feedback" : "LLM 自動修正"}
      </div>
      <textarea
        value={feedback}
        onChange={e => setFeedback(e.target.value)}
        placeholder="描述問題，例如：回傳是 list 不是 dict、field name 用錯了、沒有帶 toolID"
        style={{
          width: "100%", padding: "6px 8px", borderRadius: 5,
          border: "1px solid #e2e8f0", fontSize: 11, minHeight: 40,
          resize: "vertical", boxSizing: "border-box",
        }}
      />
      <div style={{ display: "flex", gap: 8, marginTop: 6, alignItems: "center" }}>
        <button
          onClick={handleFix}
          disabled={fixing}
          style={{
            padding: "5px 14px", borderRadius: 5, border: "none",
            background: fixing ? "#d69e2e" : "#f59e0b", color: "#fff",
            fontSize: 11, fontWeight: 600, cursor: fixing ? "wait" : "pointer",
          }}
        >
          {fixing ? "修正中..." : "自動修正"}
        </button>
        {result && (
          <span style={{ fontSize: 11, color: result.includes("失敗") ? "#dc2626" : "#16a34a" }}>
            {result}
          </span>
        )}
      </div>
    </div>
  );
}

type PipelineOption = { id: number; name: string; status: string; inputs: Array<{ name: string; type: string; required?: boolean; example?: unknown; description?: string }> };

export default function AutoPatrolsPage() {
  const [patrols, setPatrols]         = useState<AutoPatrol[]>([]);
  const [eventTypes, setEventTypes]   = useState<EventType[]>([]);
  const [showModal, setShowModal]     = useState(false);
  const [form, setForm]               = useState(emptyForm());
  // Phase 4-B: available pipelines for the binding dropdown
  const [pipelineOptions, setPipelineOptions] = useState<PipelineOption[]>([]);

  // Clarify dialog state
  const [clarifyOpen, setClarifyOpen] = useState(false);
  const [clarifyQuestions, setClarifyQuestions] = useState<ClarifyQuestion[]>([]);

  // Diagnostic plan state
  const [generating, setGenerating]   = useState(false);
  const [consoleLogs, setConsoleLogs] = useState<{icon: string; text: string}[]>([]);
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
  const [editingSkillId, setEditingSkillId] = useState<number | null>(null);

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
    // PR-B: Auto-Patrol can only bind to ACTIVE + auto_patrol kind pipelines.
    fetch("/api/pipeline-builder/pipelines").then(r => r.json()).then((pipelines: Array<{ id: number; name: string; status: string; pipeline_kind?: string; pipeline_json: { inputs?: PipelineOption["inputs"] } }>) => {
      const active = (Array.isArray(pipelines) ? pipelines : []).filter(p =>
        p.status === "active" && (p.pipeline_kind ?? "diagnostic") === "auto_patrol",
      );
      setPipelineOptions(active.map(p => ({
        id: p.id, name: p.name, status: p.status,
        inputs: p.pipeline_json?.inputs ?? [],
      })));
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
    setEditingSkillId(p.skill_id);
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

    // Phase 4-B: detect execution mode from pipeline_id presence
    const isPipelineMode = (p as AutoPatrol & { pipeline_id?: number | null }).pipeline_id != null;
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
      execution_mode:         isPipelineMode ? "pipeline" : "skill",
      pipeline_id:            (p as AutoPatrol & { pipeline_id?: number | null }).pipeline_id ?? null,
      input_binding:          (p as AutoPatrol & { input_binding?: Record<string, string> }).input_binding ?? {},
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
    setConsoleLogs([]);
    await runGenerateStream(form.auto_check_description.trim(), false);
  }

  async function runGenerateStream(description: string, skipClarify: boolean) {
    const addLog = (icon: string, text: string) =>
      setConsoleLogs(prev => [...prev, { icon, text }]);

    try {
      const res = await fetch("/api/admin/rules/generate-steps/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          auto_check_description: description,
          skip_clarify: skipClarify,
          patrol_context: {
            trigger_mode: form.trigger_mode,
            data_context: form.data_context,
            target_scope_type: form.target_scope_type,
          },
        }),
      });

      if (!res.ok || !res.body) { setError("AI 設計失敗"); return; }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalResult: Record<string, unknown> | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          // Accept both "data: " (Python) and "data:" (Spring SseEmitter) prefixes.
          if (!line.startsWith("data:")) continue;
          try {
            const event = JSON.parse(line.slice(5).replace(/^\s/, "")) as Record<string, unknown>;
            const type = event.type as string;

            if (type === "clarify_needed") {
              const qs = (event.questions as ClarifyQuestion[]) ?? [];
              addLog("🤔", `需要確認 ${qs.length} 件事`);
              setClarifyQuestions(qs);
              setClarifyOpen(true);
              return; // Stop streaming, wait for user
            } else if (type === "phase") {
              addLog("📦", `Phase ${event.phase}: ${event.message}`);
            } else if (type === "fetch") {
              const status = event.status as string;
              const icon = status === "ok" ? "✅" : status === "error" ? "❌" : "⏳";
              addLog(icon, `${event.mcp_name} → ${status}${event.shape ? ` (${event.shape})` : ""}${event.error ? ` — ${event.error}` : ""}`);
            } else if (type === "step_code") {
              const status = event.status as string;
              if (status === "generating") {
                addLog("⏳", `${event.step_id}: ${event.nl_segment}`);
              } else if (status === "done") {
                addLog("✅", `${event.step_id} 生成完成`);
              } else if (status === "error") {
                addLog("❌", `${event.step_id} 失敗: ${event.error}`);
              }
            } else if (type === "self_test") {
              const st = event.status as string;
              if (st === "running") addLog("🔍", "Self-test 執行中...");
              else if (st === "pass") addLog("✅", "Self-test 通過");
              else if (st === "warning") addLog("⚠️", `Self-test 警告: ${(event.issues as string[])?.join("; ")}`);
              else if (st === "fail") addLog("❌", `Self-test 失敗: ${event.error}`);
            } else if (type === "error") {
              addLog("❌", event.error as string);
              setError(event.error as string);
            } else if (type === "done") {
              finalResult = event.result as Record<string, unknown>;
            }
          } catch { /* skip malformed SSE */ }
        }
      }

      if (finalResult) {
        const steps = (finalResult.steps_mapping as StepMapping[]) ?? [];
        const proposal = (finalResult.proposal_steps as string[]) ?? steps.map(s => s.nl_segment);
        if (steps.length === 0) { setError("AI 未能生成步驟"); return; }

        setForm(f => ({
          ...f,
          steps_mapping: steps,
          input_schema: (finalResult!.input_schema as InputSchemaField[]) ?? [],
          output_schema: (finalResult!.output_schema as OutputSchemaField[]) ?? [],
        }));
        setProposalSteps(proposal);
        setEditedCode(Object.fromEntries(steps.map(s => [s.step_id, s.python_code])));
        setSelectedStepId(steps[0]?.step_id ?? null);
        addLog("🎉", `生成完成 — ${steps.length} 個步驟`);
      }
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
    // Phase 4-B: validate based on execution mode
    if (form.execution_mode === "skill" && form.steps_mapping.length === 0) {
      setError("Skill 模式下請先讓 AI 設計診斷計畫"); return;
    }
    if (form.execution_mode === "pipeline" && form.pipeline_id == null) {
      setError("Pipeline 模式下請選擇要綁定的 Pipeline"); return;
    }

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

    const isPipelineMode = form.execution_mode === "pipeline";
    const payload: Record<string, unknown> = {
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
    };
    if (isPipelineMode) {
      // Phase 4-B: Pipeline-backed — no embedded skill
      payload.pipeline_id   = form.pipeline_id;
      payload.input_binding = form.input_binding;
    } else {
      // Legacy skill-backed
      payload.steps_mapping = finalSteps;
      payload.input_schema  = form.input_schema;
      payload.output_schema = form.output_schema;
    }

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

  function handleTrigger(id: number) {
    // Open edit modal for this patrol so user can use the full Try-Run UI
    const patrol = patrols.find(p => p.id === id);
    if (patrol) {
      openEdit(patrol);
    }
  }

  const canSave = form.name.trim().length > 0 && (
    form.execution_mode === "pipeline"
      ? form.pipeline_id != null
      : form.steps_mapping.length > 0
  );

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: "#1a202c" }}>Auto-Patrols</div>
        <button style={S.btn("#6366f1")} onClick={openCreate}>+ 新增 Auto-Patrol</button>
      </div>

      {/* List */}
      <div style={{ overflowX: "auto" }}>
      <table style={{ ...S.table, minWidth: 800 }}>
        <thead>
          <tr>
            <th style={S.th}>名稱</th>
            <th style={S.th}>觸發方式</th>
            <th style={S.th}>近 24h 執行</th>
            <th style={S.th}>警報</th>
            <th style={{ ...S.th, width: 60 }}>狀態</th>
            <th style={{ ...S.th, width: 180 }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {patrols.length === 0 && (
            <tr><td colSpan={6} style={{ ...S.td, color: "#a0aec0", textAlign: "center" }}>尚無 Auto-Patrol</td></tr>
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
              <td style={{ ...S.td, fontSize: 11, minWidth: 200 }}>
                {(() => {
                  const stats = (p as any).stats;
                  if (!stats || stats.total === 0) {
                    return <span style={{ color: "#a0aec0" }}>近 24h 無執行</span>;
                  }
                  const byTrigger: Record<string, number> = stats.by_trigger || {};
                  const byEq: Record<string, number> = stats.by_equipment || {};
                  const lastAt = stats.last_at ? new Date(stats.last_at) : null;
                  const minsAgo = lastAt ? Math.floor((Date.now() - lastAt.getTime()) / 60000) : null;
                  const lastAgo = minsAgo === null ? "—"
                    : minsAgo < 60 ? `${minsAgo} 分前`
                    : minsAgo < 1440 ? `${Math.floor(minsAgo/60)} 時前`
                    : `${Math.floor(minsAgo/1440)} 天前`;
                  return (
                    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <span style={{ fontWeight: 700, color: "#2d3748" }}>{stats.total} 次</span>
                        {stats.error > 0 && (
                          <span style={{ color: "#e53e3e", fontSize: 10 }}>({stats.error} err)</span>
                        )}
                        {stats.condition_met_count > 0 && (
                          <span style={{ color: "#dd6b20", fontSize: 10 }}>⚠ {stats.condition_met_count} 觸發</span>
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        {Object.entries(byTrigger).map(([k, v]) => {
                          const label = k === "event_poller" ? "⚡event" :
                                        k === "schedule" ? "🕐schedule" :
                                        k === "manual" ? "👆manual" :
                                        k.startsWith("alarm:") ? "🚨alarm" : k;
                          return (
                            <span key={k} style={{ padding: "1px 6px", borderRadius: 8, background: "#edf2f7", color: "#4a5568", fontSize: 10 }}>
                              {label} {v}
                            </span>
                          );
                        })}
                      </div>
                      {Object.keys(byEq).length > 0 && (
                        <div style={{ fontSize: 10, color: "#718096" }}>
                          機台: {Object.keys(byEq).length} 台 ({Object.entries(byEq).slice(0,3).map(([k,v]) => `${k}×${v}`).join(", ")}{Object.keys(byEq).length > 3 ? "…" : ""})
                        </div>
                      )}
                      <div style={{ fontSize: 10, color: "#a0aec0" }}>
                        最後: {lastAgo}
                      </div>
                    </div>
                  );
                })()}
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
                <div style={{ display: "flex", gap: 4, flexWrap: "nowrap" }}>
                  <button style={S.btnSm("#dd6b20")} onClick={() => handleTrigger(p.id)}>執行</button>
                  <button style={S.btnSm("#3182ce")} onClick={() => openEdit(p)}>編輯</button>
                  <button style={S.btnSm("#6366f1")} onClick={() => openHistory(p)}>紀錄</button>
                  <button style={S.btnSm("#e53e3e")} onClick={() => handleDelete(p.id)}>刪除</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>

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

            {/* ── Phase 4-B: 執行方式切換 ── */}
            <div style={S.section}>
              <div style={S.sectionTitle}>④ 執行方式</div>
              <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <button
                  type="button"
                  data-testid="exec-mode-skill"
                  onClick={() => setForm(f => ({ ...f, execution_mode: "skill" }))}
                  style={{
                    padding: "8px 16px", fontSize: 13, fontWeight: 600,
                    border: `1px solid ${form.execution_mode === "skill" ? "#3182ce" : "#cbd5e0"}`,
                    background: form.execution_mode === "skill" ? "#ebf8ff" : "#fff",
                    color: form.execution_mode === "skill" ? "#2c5282" : "#4a5568",
                    borderRadius: 4, cursor: "pointer",
                  }}
                >
                  🧩 Skill-based（legacy Python steps）
                </button>
                <button
                  type="button"
                  data-testid="exec-mode-pipeline"
                  onClick={() => setForm(f => ({ ...f, execution_mode: "pipeline" }))}
                  style={{
                    padding: "8px 16px", fontSize: 13, fontWeight: 600,
                    border: `1px solid ${form.execution_mode === "pipeline" ? "#38a169" : "#cbd5e0"}`,
                    background: form.execution_mode === "pipeline" ? "#f0fff4" : "#fff",
                    color: form.execution_mode === "pipeline" ? "#276749" : "#4a5568",
                    borderRadius: 4, cursor: "pointer",
                  }}
                >
                  🔄 Pipeline-based（Phase 4-B）
                </button>
              </div>
            </div>

            {/* ── Pipeline binding panel (Phase 4-B) ── */}
            {form.execution_mode === "pipeline" && (
              <div style={S.section}>
                <div style={S.sectionTitle}>⑤ Pipeline 綁定</div>

                <div style={S.row}>
                  <label style={S.label}>Pipeline</label>
                  <select
                    data-testid="pipeline-select"
                    value={form.pipeline_id ?? ""}
                    onChange={e => {
                      const id = e.target.value ? Number(e.target.value) : null;
                      // Auto-seed input_binding with examples from chosen pipeline
                      const chosen = pipelineOptions.find(p => p.id === id);
                      const seededBinding: Record<string, string> = {};
                      if (chosen?.inputs) {
                        for (const inp of chosen.inputs) {
                          // Prefer $event.<name> as default binding source (common pattern)
                          seededBinding[inp.name] = inp.name === "tool_id" ? "$event.equipment_id" : (inp.example ? String(inp.example) : "");
                        }
                      }
                      setForm(f => ({ ...f, pipeline_id: id, input_binding: seededBinding }));
                    }}
                    style={{ ...S.input, minWidth: 360 }}
                  >
                    <option value="">— 選擇 Pipeline —</option>
                    {pipelineOptions.map(p => (
                      <option key={p.id} value={p.id}>
                        #{p.id} {p.name} [{p.status}]
                      </option>
                    ))}
                  </select>
                </div>

                {form.pipeline_id && (() => {
                  const pipeline = pipelineOptions.find(p => p.id === form.pipeline_id);
                  if (!pipeline) return null;
                  if (pipeline.inputs.length === 0) {
                    return (
                      <div style={{ fontSize: 12, color: "#a0aec0", padding: 10, background: "#f7fafc", borderRadius: 4, marginTop: 8 }}>
                        此 Pipeline 沒有宣告 inputs — 直接用 pipeline 內部的 hardcoded 參數執行。
                      </div>
                    );
                  }
                  return (
                    <div style={{ marginTop: 8 }}>
                      <div style={{ fontSize: 10, color: "#718096", fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 6 }}>
                        Input Binding （{pipeline.inputs.length} 個變數）
                      </div>
                      <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
                        <thead>
                          <tr style={{ background: "#f7fafc" }}>
                            <th style={{ textAlign: "left", padding: "6px 8px", fontSize: 10, color: "#4a5568", fontWeight: 600 }}>變數</th>
                            <th style={{ textAlign: "left", padding: "6px 8px", fontSize: 10, color: "#4a5568", fontWeight: 600 }}>Type</th>
                            <th style={{ textAlign: "left", padding: "6px 8px", fontSize: 10, color: "#4a5568", fontWeight: 600 }}>綁定值</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pipeline.inputs.map(inp => (
                            <tr key={inp.name} data-testid={`pipeline-binding-${inp.name}`}>
                              <td style={{ padding: "5px 8px", borderBottom: "1px solid #edf2f7" }}>
                                <code style={{ color: "#3730A3", fontFamily: "ui-monospace, monospace" }}>${inp.name}</code>
                                {inp.required && <span style={{ color: "#c53030", marginLeft: 4 }}>*</span>}
                              </td>
                              <td style={{ padding: "5px 8px", borderBottom: "1px solid #edf2f7", color: "#718096", fontFamily: "ui-monospace, monospace", fontSize: 11 }}>
                                {inp.type}
                              </td>
                              <td style={{ padding: "5px 8px", borderBottom: "1px solid #edf2f7" }}>
                                <input
                                  type="text"
                                  value={form.input_binding[inp.name] ?? ""}
                                  onChange={e => setForm(f => ({ ...f, input_binding: { ...f.input_binding, [inp.name]: e.target.value } }))}
                                  placeholder={inp.example ? String(inp.example) : "literal or $event.xxx"}
                                  list={`binding-suggest-${inp.name}`}
                                  style={{ ...S.input, fontSize: 11, width: "100%" }}
                                />
                                <datalist id={`binding-suggest-${inp.name}`}>
                                  <option value="$event.equipment_id" />
                                  <option value="$event.toolID" />
                                  <option value="$event.lot_id" />
                                  <option value="$event.step" />
                                  <option value="$event.event_time" />
                                  <option value="$context.equipment_id" />
                                </datalist>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <div style={{ fontSize: 10, color: "#a0aec0", marginTop: 6 }}>
                        提示：literal（直接值） / <code>$event.xxx</code> / <code>$context.xxx</code>（從觸發 payload 取）
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}

            {/* ── 診斷計畫 (Skill mode only) ── */}
            {form.execution_mode === "skill" && (
            <div style={S.section}>
              <div style={S.sectionTitle}>⑤ 診斷計畫</div>

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

              {/* AI Console */}
              {consoleLogs.length > 0 && (
                <div style={{
                  background: "#1a202c", borderRadius: 8, padding: "10px 14px",
                  marginBottom: 12, maxHeight: 200, overflowY: "auto",
                }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: "#718096", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    AI Console
                  </div>
                  {consoleLogs.map((log, i) => (
                    <div key={i} style={{ fontSize: 11, color: "#e2e8f0", marginBottom: 3, display: "flex", gap: 6 }}>
                      <span style={{ flexShrink: 0 }}>{log.icon}</span>
                      <span style={{ color: "#a0aec0" }}>{log.text}</span>
                    </div>
                  ))}
                  {generating && (
                    <div style={{ fontSize: 11, color: "#fbbf24", marginTop: 4 }}>⏳ 處理中...</div>
                  )}
                </div>
              )}

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

                  {/* Evidence + charts (structured via RenderMiddleware) */}
                  {tryRunResult.findings && (
                    <div style={{ padding: "12px 14px" }}>
                      <RenderMiddleware findings={tryRunResult.findings} outputSchema={form.output_schema} charts={tryRunResult.charts} />
                    </div>
                  )}

                  {tryRunResult.error && !tryRunResult.findings && (
                    <div style={{ padding: "10px 14px", color: "#c53030", fontSize: 13 }}>{tryRunResult.error}</div>
                  )}

                  {/* Feedback / auto-fix panel */}
                  {editingSkillId && (
                    <div style={{ padding: "12px 14px", borderTop: "1px solid #e2e8f0" }}>
                      <AutoPatrolFixPanel
                        skillId={editingSkillId}
                        errorMessage={tryRunResult.error || ""}
                        success={tryRunResult.success}
                        onFixed={() => setTryRunResult(null)}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>

            )}
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

      {/* Inline clarification dialog */}
      <ClarifyDialog
        open={clarifyOpen}
        questions={clarifyQuestions}
        onCancel={() => {
          setClarifyOpen(false);
          setGenerating(false);
          setConsoleLogs(prev => [...prev, { icon: "❌", text: "已取消生成" }]);
        }}
        onConfirm={async (answers: ClarifyAnswer[]) => {
          setClarifyOpen(false);
          const enriched =
            form.auto_check_description.trim() +
            "\n\n[使用者澄清]\n" +
            answers.map(a => `- ${a.label}：${a.value}`).join("\n");
          setConsoleLogs(prev => [...prev, { icon: "✓", text: "已收到澄清，繼續生成..." }]);
          await runGenerateStream(enriched, true);
        }}
      />
    </div>
  );
}
