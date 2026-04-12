"use client";

import { useEffect, useState } from "react";
import { RenderMiddleware, RenderOutputValue, type OutputSchemaField, type ChartDSL } from "@/components/operations/SkillOutputRenderer";
import { ClarifyDialog, type ClarifyQuestion, type ClarifyAnswer } from "@/components/skill-builder/ClarifyDialog";

// ── Types ─────────────────────────────────────────────────────────────────────

type StepMapping = {
  step_id: string;
  nl_segment: string;
  python_code: string;
};

type DiagnosticRule = {
  id: string;
  name: string;
  description: string;
  auto_check_description: string;
  steps_mapping: StepMapping[];
  input_schema: InputSchemaField[];
  output_schema: OutputSchemaField[];
  visibility: "private" | "public";
  is_active: boolean;
  created_at: string;
  updated_at: string;
  trigger_patrol_id: number | null;
};

type AutoPatrol = { id: number; name: string; alarm_severity?: string | null };

type StepResult = { step_id: string; nl_segment: string; status: string; output?: unknown; error?: string };

type TryRunResult = {
  success: boolean;
  step_results?: StepResult[];
  findings: {
    condition_met: boolean;
    summary?: string;
    outputs?: Record<string, unknown>;
    evidence?: Record<string, unknown>;
    impacted_lots: string[];
  } | null;
  charts?: ChartDSL[] | null;
  total_elapsed_ms: number;
  error?: string;
};

type InputSchemaField = {
  key: string; type: string; required: boolean;
  default?: unknown; description: string;
};

type BuildPhase = "idle" | "generating" | "proposed" | "try_running" | "result_ok" | "result_fail";

const SEV_COLOR: Record<string, string> = {
  CRITICAL: "#dc2626", HIGH: "#ea580c", MEDIUM: "#ca8a04", LOW: "#16a34a",
};

const EMPTY_META = {
  name: "",
  description: "",
  auto_check_description: "",
  visibility: "private" as "private" | "public",
  trigger_patrol_id: null as number | null,
};

// ── Styles ────────────────────────────────────────────────────────────────────

const S = {
  page: { padding: 0 } as React.CSSProperties,
  header: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    marginBottom: 20,
  } as React.CSSProperties,
  title: { fontSize: 20, fontWeight: 700, color: "#1a202c" } as React.CSSProperties,
  btn: (color: string): React.CSSProperties => ({
    padding: "7px 14px", borderRadius: 6, border: "none", cursor: "pointer",
    fontSize: 13, fontWeight: 500, background: color, color: "#fff",
  }),
  btnSm: (color: string): React.CSSProperties => ({
    padding: "4px 10px", borderRadius: 5, border: "none", cursor: "pointer",
    fontSize: 12, fontWeight: 500, background: color, color: "#fff",
  }),
  table: { width: "100%", borderCollapse: "collapse" as const, fontSize: 13 },
  th: {
    background: "#f7fafc", borderBottom: "2px solid #e2e8f0",
    padding: "8px 12px", textAlign: "left" as const, fontWeight: 600, color: "#4a5568",
  },
  td: { padding: "10px 12px", borderBottom: "1px solid #edf2f7", color: "#2d3748" },
  overlay: {
    position: "fixed" as const, inset: 0,
    background: "rgba(0,0,0,0.45)", zIndex: 1000,
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  modal: {
    background: "#fff", borderRadius: 10, padding: 28,
    width: 740, maxHeight: "90vh", overflowY: "auto" as const,
    boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
  },
  label: { display: "block", fontSize: 12, fontWeight: 600, color: "#4a5568", marginBottom: 4 } as React.CSSProperties,
  input: {
    width: "100%", padding: "7px 10px", border: "1px solid #cbd5e0",
    borderRadius: 6, fontSize: 13, color: "#2d3748",
    boxSizing: "border-box" as const,
  },
  textarea: {
    width: "100%", padding: "7px 10px", border: "1px solid #cbd5e0",
    borderRadius: 6, fontSize: 13, color: "#2d3748", resize: "vertical" as const,
    boxSizing: "border-box" as const,
  },
  row: { marginBottom: 14 } as React.CSSProperties,
  error: { color: "#c53030", fontSize: 13, marginTop: 8 } as React.CSSProperties,
};

// ── Page ──────────────────────────────────────────────────────────────────────

// ── Fix Panel (error auto-fix + user feedback) ──────────────────────────────

function FixPanel({ ruleId, errorMessage, onFixed }: { ruleId: string | number; errorMessage: string; onFixed: () => void }) {
  const [feedback, setFeedback] = useState("");
  const [fixing, setFixing] = useState(false);
  const [fixResult, setFixResult] = useState<string | null>(null);
  const isErrorMode = !!errorMessage;

  async function handleFix() {
    if (!isErrorMode && !feedback.trim()) {
      setFixResult("請先填寫回饋內容再送出");
      return;
    }
    setFixing(true);
    setFixResult(null);
    try {
      const res = await fetch(`/api/admin/rules/${ruleId}/fix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          error_message: errorMessage,
          user_feedback: feedback,
        }),
      });
      const data = await res.json();
      const result = data?.data ?? data;
      if (result?.success) {
        setFixResult(`修正完成（${result.steps_count} steps）。請重新 Try Run 驗證。`);
        onFixed();
      } else {
        setFixResult(`修正失敗：${result?.error || "未知錯誤"}`);
      }
    } catch (e) {
      setFixResult(`修正失敗：${e}`);
    } finally {
      setFixing(false);
    }
  }

  const headerColor = isErrorMode ? "#92400e" : "#1e40af";
  const bgColor = isErrorMode ? "#fffbeb" : "#eff6ff";
  const borderColor = isErrorMode ? "#fbbf24" : "#93c5fd";
  const btnColor = isErrorMode ? "#f59e0b" : "#3b82f6";
  const headerText = isErrorMode ? "LLM 自動修正" : "回饋與修正";
  const placeholder = isErrorMode
    ? "（選填）描述哪裡有問題，例如：object_id 應該用 step 不是 equipment_id"
    : "結果有問題嗎？描述邏輯哪裡需要調整，例如：應該用最近 5 次而不是 30 天的資料";
  const btnLabel = isErrorMode ? (fixing ? "修正中..." : "自動修正") : (fixing ? "送出中..." : "送出回饋並修正");

  return (
    <div style={{ marginTop: 12, padding: "12px 14px", background: bgColor, border: `1px solid ${borderColor}`, borderRadius: 8 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: headerColor, marginBottom: 8 }}>
        {headerText}
      </div>
      <textarea
        value={feedback}
        onChange={e => setFeedback(e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%", padding: "8px 10px", borderRadius: 6,
          border: "1px solid #e2e8f0", fontSize: 12, minHeight: 50,
          resize: "vertical", boxSizing: "border-box",
        }}
      />
      <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
        <button
          onClick={handleFix}
          disabled={fixing}
          style={{
            padding: "6px 16px", borderRadius: 6, border: "none",
            background: fixing ? "#94a3b8" : btnColor, color: "#fff",
            fontSize: 12, fontWeight: 600, cursor: fixing ? "wait" : "pointer",
          }}
        >
          {btnLabel}
        </button>
        {fixResult && (
          <span style={{ fontSize: 12, color: fixResult.includes("失敗") ? "#dc2626" : "#16a34a" }}>
            {fixResult}
          </span>
        )}
      </div>
    </div>
  );
}

export default function DiagnosticRulesPage() {
  const [rules, setRules]           = useState<DiagnosticRule[]>([]);
  const [autoPatrols, setAutoPatrols] = useState<AutoPatrol[]>([]);
  const [showModal, setShowModal]   = useState(false);
  const [editing, setEditing]       = useState<DiagnosticRule | null>(null);
  const [meta, setMeta]             = useState(EMPTY_META);
  const [proposalSteps, setProposalSteps]   = useState<string[]>([]);
  const [stepsMapping, setStepsMapping]     = useState<StepMapping[]>([]);
  const [inputSchema, setInputSchema]       = useState<InputSchemaField[]>([]);
  const [outputSchema, setOutputSchema]     = useState<OutputSchemaField[]>([]);
  const [phase, setPhase]           = useState<BuildPhase>("idle");
  const [showCode, setShowCode]     = useState(false);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [editedCode, setEditedCode] = useState<Record<string, string>>({});
  const [codeEdited, setCodeEdited] = useState(false);
  const [mockForm, setMockForm]     = useState<Record<string, string>>({
    equipment_id: "EQP-01",
    lot_id:       "LOT-0001",
    step:         "STEP_038",
    event_time:   new Date().toISOString().slice(0, 19) + "Z",
  });
  const [tryRunResult, setTryRunResult] = useState<TryRunResult | null>(null);
  const [consoleLogs, setConsoleLogs]   = useState<{ text: string; ok?: boolean }[]>([]);
  const [error, setError]           = useState("");

  // ── Data loading ──────────────────────────────────────────────────────────

  function reloadList() {
    fetch("/api/admin/rules").then(r => r.json()).then((d) => {
      setRules(Array.isArray(d) ? d : []);
    }).catch(() => setRules([]));
  }

  function loadPatrols() {
    fetch("/api/admin/auto-patrols").then(r => r.json()).then((d) => {
      setAutoPatrols(Array.isArray(d) ? d : []);
    }).catch(() => setAutoPatrols([]));
  }

  useEffect(() => { reloadList(); loadPatrols(); }, []);

  // ── Modal helpers ─────────────────────────────────────────────────────────

  function resetModal() {
    setEditing(null);
    setMeta(EMPTY_META);
    setProposalSteps([]);
    setStepsMapping([]);
    setInputSchema([]);
    setOutputSchema([]);
    setPhase("idle");
    setShowCode(false);
    setSelectedStepId(null);
    setEditedCode({});
    setCodeEdited(false);
    setTryRunResult(null);
    setConsoleLogs([]);
    setError("");
  }

  function openCreate() {
    resetModal();
    setShowModal(true);
  }

  // Clarify dialog state — for inline interruption when LLM detects ambiguity
  const [clarifyOpen, setClarifyOpen] = useState(false);
  const [clarifyQuestions, setClarifyQuestions] = useState<ClarifyQuestion[]>([]);

  function openEdit(rule: DiagnosticRule) {
    resetModal();
    setEditing(rule);
    const steps: StepMapping[] = Array.isArray(rule.steps_mapping) ? rule.steps_mapping : [];
    setMeta({
      name:                   rule.name,
      description:            rule.description,
      auto_check_description: rule.auto_check_description ?? "",
      visibility:             rule.visibility ?? "private",
      trigger_patrol_id:      rule.trigger_patrol_id ?? null,
    });
    if (steps.length > 0) {
      setProposalSteps(steps.map(s => s.nl_segment));
      setStepsMapping(steps);
      setEditedCode(Object.fromEntries(steps.map(s => [s.step_id, s.python_code])));
      setSelectedStepId(steps[0]?.step_id ?? null);
      setInputSchema(Array.isArray(rule.input_schema) ? rule.input_schema : []);
      setOutputSchema(Array.isArray(rule.output_schema) ? rule.output_schema : []);
      setPhase("proposed");
    }
    setShowModal(true);
  }

  // ── CRUD ──────────────────────────────────────────────────────────────────

  async function handleDelete(id: string) {
    if (!confirm("確定刪除此 Rule？")) return;
    await fetch(`/api/admin/rules/${id}`, { method: "DELETE" });
    reloadList();
  }

  async function handleSave() {
    setError("");
    if (!meta.name.trim()) { setError("名稱必填"); return; }
    if (stepsMapping.length === 0) { setError("請先讓 AI 設計診斷計畫"); return; }

    const finalSteps: StepMapping[] = stepsMapping.map(s => ({
      ...s,
      python_code: editedCode[s.step_id] ?? s.python_code,
    }));

    const payload = {
      name:                   meta.name.trim(),
      description:            meta.description.trim(),
      auto_check_description: meta.auto_check_description.trim(),
      steps_mapping:          finalSteps,
      input_schema:           inputSchema,
      output_schema:          outputSchema,
      visibility:             meta.visibility,
      trigger_patrol_id:      meta.trigger_patrol_id,
    };

    const res = editing
      ? await fetch(`/api/admin/rules/${editing.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
      : await fetch("/api/admin/rules", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      setError((b as Record<string, string>).error ?? "儲存失敗");
      return;
    }
    setShowModal(false);
    reloadList();
  }

  // ── LLM Generate ──────────────────────────────────────────────────────────

  const canGenerate = meta.name.trim().length > 0 && meta.auto_check_description.trim().length >= 5;

  async function handleGenerate() {
    setError("");
    setPhase("generating");
    setConsoleLogs([]);
    setProposalSteps([]);
    setStepsMapping([]);
    setInputSchema([]);
    setOutputSchema([]);
    setTryRunResult(null);
    setCodeEdited(false);
    await runGenerateStream(meta.auto_check_description.trim(), false);
  }

  async function runGenerateStream(description: string, skipClarify: boolean) {
    const addLog = (text: string, ok?: boolean) =>
      setConsoleLogs(prev => [...prev, { text, ok }]);

    try {
      const res = await fetch("/api/admin/rules/generate-steps/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          auto_check_description: description,
          skip_clarify: skipClarify,
        }),
      });

      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";

        for (const chunk of chunks) {
          const line = chunk.replace(/^data: /, "").trim();
          if (!line) continue;
          let event: Record<string, unknown>;
          try { event = JSON.parse(line); } catch { continue; }

          switch (event.type) {
            case "clarify_needed": {
              const qs = (event.questions as ClarifyQuestion[]) ?? [];
              addLog(`🤔 需要確認 ${qs.length} 件事`);
              setClarifyQuestions(qs);
              setClarifyOpen(true);
              return; // Stop streaming, wait for user to answer
            }
            case "phase":
              addLog(`[Phase ${event.phase}] ${event.message}`);
              break;
            case "log":
              addLog(event.message as string);
              break;
            case "fetch":
              if (event.status === "fetching") {
                addLog(`  ⏳ ${event.mcp_name}`);
              } else if (event.status === "ok") {
                addLog(`  ✓ ${event.mcp_name}  ${event.shape}`, true);
              } else {
                addLog(`  ✗ ${event.mcp_name}  ${event.error}`, false);
              }
              break;
            case "step_plan":
              addLog(`  規劃 ${event.total} 個步驟`, true);
              break;
            case "step_code":
              if (event.status === "generating") {
                addLog(`  ⏳ 生成 ${event.step_id} (${event.nl_segment})`);
              } else if (event.status === "done") {
                addLog(`  ✓ ${event.step_id}`, true);
              } else {
                addLog(`  ✗ ${event.step_id}: ${event.error}`, false);
              }
              break;
            case "self_test": {
              const st = event.status as string;
              if (st === "running") addLog("🔍 Self-test 執行中...");
              else if (st === "pass") addLog("✅ Self-test 通過", true);
              else if (st === "warning") addLog(`⚠️ Self-test 警告: ${(event.issues as string[])?.join("; ")}`, false);
              else if (st === "fail") addLog(`❌ Self-test 失敗: ${event.error}`, false);
              else if (st === "error") addLog(`❌ Self-test 錯誤: ${event.error}`, false);
              break;
            }
            case "done": {
              const r = event.result as Record<string, unknown>;
              const steps    = (r.steps_mapping  as StepMapping[]) ?? [];
              const proposal = (r.proposal_steps as string[]) ?? steps.map(s => s.nl_segment);
              const inSchema  = (r.input_schema   as InputSchemaField[]) ?? [];
              const outSchema = (r.output_schema  as OutputSchemaField[]) ?? [];

              // Show self-test result from done event
              const selfTest = r.self_test as Record<string, unknown> | undefined;
              if (selfTest) {
                const st = selfTest.status as string;
                if (st === "fail") setError(`Self-test 失敗: ${selfTest.error || "try-run 執行失敗"}。請用下方 feedback 修正。`);
                else if (st === "warning") setError(`Self-test 警告: ${(selfTest.issues as string[])?.join("; ")}`);
              }

              if (steps.length === 0) {
                setError("AI 未能生成診斷步驟，請修改描述後重試");
                setPhase("idle");
              } else {
                setProposalSteps(proposal);
                setStepsMapping(steps);
                setInputSchema(inSchema);
                setOutputSchema(outSchema);
                setEditedCode(Object.fromEntries(steps.map(s => [s.step_id, s.python_code])));
                setSelectedStepId(steps[0]?.step_id ?? null);
                addLog(`✅ 完成，共 ${steps.length} 個步驟`, true);
                setPhase("proposed");
              }
              break;
            }
            case "error":
              setError((event.error as string) ?? "AI 設計失敗");
              setPhase("idle");
              break;
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI 設計失敗");
      setPhase("idle");
    }
  }

  // ── Try-Run ───────────────────────────────────────────────────────────────

  async function handleTryRun() {
    setPhase("try_running");
    setTryRunResult(null);
    setError("");

    const finalSteps = stepsMapping.map(s => ({
      ...s,
      python_code: editedCode[s.step_id] ?? s.python_code,
    }));

    const mockPayload: Record<string, unknown> = { event_type: "OOC" };
    // Merge all mockForm values
    for (const [k, v] of Object.entries(mockForm)) {
      if (v) mockPayload[k] = v;
    }

    try {
      let res: Response;
      let data: Record<string, unknown>;

      if (editing) {
        await fetch(`/api/admin/rules/${editing.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ steps_mapping: finalSteps, input_schema: inputSchema, output_schema: outputSchema }),
        });
        res  = await fetch(`/api/admin/rules/${editing.id}/try-run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mock_payload: mockPayload }),
        });
        data = await res.json() as Record<string, unknown>;
      } else {
        res  = await fetch("/api/admin/rules/try-run-draft", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            steps_mapping: finalSteps,
            output_schema: outputSchema,
            mock_payload:  mockPayload,
          }),
        });
        data = await res.json() as Record<string, unknown>;
      }

      const result = data as TryRunResult;
      setTryRunResult(result);
      setPhase(result.success ? "result_ok" : "result_fail");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Try-run 失敗");
      setPhase("result_fail");
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const canSave = phase === "result_ok" || (editing !== null && phase === "proposed");

  return (
    <div style={S.page}>
      {/* Header */}
      <div style={S.header}>
        <div style={S.title}>Diagnostic Rules</div>
        <button style={S.btn("#3182ce")} onClick={openCreate}>+ 新增 Rule</button>
      </div>

      {/* Table */}
      <table style={S.table}>
        <thead>
          <tr>
            <th style={S.th}>名稱</th>
            <th style={S.th}>自動檢查描述</th>
            <th style={S.th}>步驟數</th>
            <th style={S.th}>觸發來源</th>
            <th style={S.th}>狀態</th>
            <th style={S.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {rules.length === 0 && (
            <tr>
              <td colSpan={6} style={{ ...S.td, color: "#a0aec0", textAlign: "center" }}>
                尚無 Diagnostic Rule
              </td>
            </tr>
          )}
          {rules.map((rule) => (
            <tr key={rule.id}>
              <td style={S.td}>
                <div style={{ fontWeight: 600 }}>{rule.name}</div>
                {rule.description && (
                  <div style={{ color: "#718096", fontSize: 12 }}>{rule.description}</div>
                )}
              </td>
              <td style={{ ...S.td, maxWidth: 260 }}>
                <div style={{ color: "#4a5568", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {rule.auto_check_description || "—"}
                </div>
              </td>
              <td style={S.td}>{rule.steps_mapping?.length ?? 0} 步</td>
              <td style={S.td}>
                {rule.trigger_patrol_id ? (() => {
                  const p = autoPatrols.find(ap => ap.id === rule.trigger_patrol_id);
                  return p ? (
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
                      background: "#ebf8ff", color: "#2b6cb0",
                      border: "1px solid #bee3f8",
                    }}>
                      🔗 {p.name}
                    </span>
                  ) : (
                    <span style={{ color: "#a0aec0", fontSize: 11 }}>id:{rule.trigger_patrol_id}</span>
                  );
                })() : (
                  <span style={{ color: "#a0aec0", fontSize: 11 }}>—</span>
                )}
              </td>
              <td style={S.td}>
                <span style={{
                  padding: "2px 8px", borderRadius: 10, fontSize: 11,
                  background: rule.is_active ? "#c6f6d5" : "#fed7d7",
                  color: rule.is_active ? "#276749" : "#c53030",
                }}>
                  {rule.is_active ? "啟用" : "停用"}
                </span>
              </td>
              <td style={S.td}>
                <button style={{ ...S.btnSm("#4a5568"), marginRight: 6 }} onClick={() => openEdit(rule)}>
                  編輯
                </button>
                <button style={S.btnSm("#e53e3e")} onClick={() => handleDelete(rule.id)}>
                  刪除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Modal */}
      {showModal && (
        <div style={S.overlay}>
          <div style={S.modal}>
            <h3 style={{ margin: "0 0 18px", fontSize: 16, fontWeight: 700 }}>
              {editing ? "編輯 Diagnostic Rule" : "新增 Diagnostic Rule"}
            </h3>

            {/* Name */}
            <div style={S.row}>
              <label style={S.label}>規則名稱 *</label>
              <input style={S.input} value={meta.name}
                onChange={e => setMeta(m => ({ ...m, name: e.target.value }))}
                placeholder="e.g. SPC OOC Tool Recurrence Check" />
            </div>

            {/* Description */}
            <div style={S.row}>
              <label style={S.label}>描述</label>
              <input style={S.input} value={meta.description}
                onChange={e => setMeta(m => ({ ...m, description: e.target.value }))}
                placeholder="簡短說明此規則的用途" />
            </div>

            {/* Auto-check description */}
            <div style={S.row}>
              <label style={S.label}>自動檢查描述 *</label>
              <textarea
                style={{ ...S.textarea, minHeight: 80 }}
                value={meta.auto_check_description}
                onChange={e => setMeta(m => ({ ...m, auto_check_description: e.target.value }))}
                placeholder="描述此規則要自動檢查什麼，例如：Tool 最近 5 次 Process 中超過 3 次 OOC 時觸發警報"
              />
              <button
                style={{
                  ...S.btn(canGenerate && phase !== "generating" ? "#6b46c1" : "#a0aec0"),
                  marginTop: 8, fontSize: 12,
                }}
                disabled={!canGenerate || phase === "generating"}
                onClick={handleGenerate}
              >
                {phase === "generating" ? "⏳ AI 設計中..." : "✨ 讓 AI 設計診斷計畫"}
              </button>
            </div>

            {/* Generation console */}
            {consoleLogs.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{
                  background: "#1a202c", borderRadius: 8, padding: "10px 14px",
                  fontFamily: "monospace", fontSize: 12, maxHeight: 180, overflowY: "auto",
                }}>
                  <div style={{ color: "#68d391", fontWeight: 600, marginBottom: 6 }}>
                    ▶ AI 生成進度
                  </div>
                  {consoleLogs.map((log, i) => (
                    <div key={i} style={{
                      color: log.ok === true ? "#68d391" : log.ok === false ? "#fc8181" : "#a0aec0",
                      marginBottom: 2, lineHeight: 1.5,
                    }}>
                      {log.text}
                    </div>
                  ))}
                  {phase === "generating" && (
                    <div style={{ color: "#f6e05e", marginTop: 4 }}>⏳ 處理中...</div>
                  )}
                </div>
              </div>
            )}

            {/* Alarm trigger binding */}
            <div style={{ ...S.row, background: "#f0f7ff", border: "1px solid #bee3f8", borderRadius: 8, padding: "12px 14px" }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#2b4c7e", marginBottom: 8 }}>
                🔗 觸發來源（當哪個 Auto-Patrol 觸發 alarm 時，執行此診斷規則）
              </div>
              <select
                value={meta.trigger_patrol_id ?? ""}
                onChange={e => setMeta(m => ({
                  ...m,
                  trigger_patrol_id: e.target.value ? parseInt(e.target.value) : null,
                }))}
                style={{ ...S.input, maxWidth: 420 }}
              >
                <option value="">— 不綁定（手動觸發）—</option>
                {autoPatrols.map(p => (
                  <option key={p.id} value={p.id}>
                    {p.name}{p.alarm_severity ? ` [${p.alarm_severity}]` : ""}
                  </option>
                ))}
              </select>
              {meta.trigger_patrol_id && (
                <div style={{ fontSize: 11, color: "#2b6cb0", marginTop: 6 }}>
                  ✅ alarm 觸發後，此診斷規則會自動執行，結果掛回 alarm
                </div>
              )}
              {!meta.trigger_patrol_id && (
                <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 6 }}>
                  不綁定時，此規則可在 Auto-Patrol 手動 try-run 中使用
                </div>
              )}
            </div>

            {/* Proposal steps */}
            {proposalSteps.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <label style={S.label}>診斷計畫（AI 設計）</label>
                <div style={{ background: "#f7fafc", borderRadius: 6, padding: 12, border: "1px solid #e2e8f0" }}>
                  <ol style={{ margin: 0, paddingLeft: 18 }}>
                    {proposalSteps.map((step, i) => (
                      <li key={i} style={{ fontSize: 13, color: "#2d3748", marginBottom: 4 }}>{step}</li>
                    ))}
                  </ol>
                </div>
                <button
                  style={{ ...S.btnSm("#4a5568"), marginTop: 6, fontSize: 12 }}
                  onClick={() => setShowCode(v => !v)}
                >
                  {showCode ? "▲ 隱藏程式碼" : "▼ 查看/編輯程式碼"}
                </button>
              </div>
            )}

            {/* Code editor */}
            {showCode && stepsMapping.length > 0 && (
              <div style={{ marginBottom: 14, border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden" }}>
                <div style={{ display: "flex", background: "#edf2f7", overflowX: "auto" as const }}>
                  {stepsMapping.map(s => (
                    <button key={s.step_id} onClick={() => setSelectedStepId(s.step_id)}
                      style={{
                        padding: "6px 14px", border: "none", cursor: "pointer", fontSize: 12,
                        background: selectedStepId === s.step_id ? "#fff" : "transparent",
                        fontWeight: selectedStepId === s.step_id ? 600 : 400,
                        color: selectedStepId === s.step_id ? "#3182ce" : "#4a5568",
                        borderBottom: selectedStepId === s.step_id ? "2px solid #3182ce" : "none",
                      }}>
                      {s.step_id}
                    </button>
                  ))}
                </div>
                {selectedStepId && (
                  <div style={{ padding: 12 }}>
                    <div style={{ fontSize: 11, color: "#718096", marginBottom: 6 }}>
                      {stepsMapping.find(s => s.step_id === selectedStepId)?.nl_segment}
                    </div>
                    <textarea
                      style={{ ...S.textarea, minHeight: 160, fontFamily: "monospace", fontSize: 12 }}
                      value={editedCode[selectedStepId] ?? ""}
                      onChange={e => {
                        setEditedCode(prev => ({ ...prev, [selectedStepId]: e.target.value }));
                        setCodeEdited(true);
                      }}
                    />
                  </div>
                )}
              </div>
            )}

            {/* Try-run mock payload */}
            {phase !== "idle" && phase !== "generating" && (
              <div style={{ marginBottom: 14, background: "#fffbeb", border: "1px solid #f6e05e", borderRadius: 8, padding: 12 }}>
                <label style={{ ...S.label, marginBottom: 8 }}>Try-Run 測試參數</label>
                {inputSchema.length > 0 ? (
                  /* Dynamic fields from input_schema */
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8, marginBottom: 10 }}>
                    {inputSchema.map(f => (
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
                      <label style={{ fontSize: 11, color: "#744210", display: "block", marginBottom: 2 }}>Equipment ID</label>
                      <input style={{ ...S.input, fontSize: 12, maxWidth: 240 }}
                        value={mockForm.equipment_id ?? ""}
                        onChange={e => setMockForm(f => ({ ...f, equipment_id: e.target.value }))} />
                    </div>
                    <details style={{ marginBottom: 8 }}>
                      <summary style={{ fontSize: 11, color: "#92610a", cursor: "pointer", userSelect: "none" as const }}>進階參數（lot_id / step / event_time）</summary>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 8 }}>
                        {[["lot_id", "Lot ID"], ["step", "Step"], ["event_time", "Event Time"]].map(([key, lbl]) => (
                          <div key={key}>
                            <label style={{ fontSize: 11, color: "#744210", display: "block", marginBottom: 2 }}>{lbl}</label>
                            <input style={{ ...S.input, fontSize: 12 }}
                              value={mockForm[key] ?? ""}
                              onChange={e => setMockForm(f => ({ ...f, [key]: e.target.value }))} />
                          </div>
                        ))}
                      </div>
                    </details>
                  </>
                )}
                <button
                  style={{ ...S.btn("#dd6b20"), marginTop: 10, fontSize: 12 }}
                  disabled={phase === "try_running"}
                  onClick={handleTryRun}
                >
                  {phase === "try_running" ? "⏳ 執行中..." : "▶ Try Run"}
                </button>
              </div>
            )}

            {/* Try-run result */}
            {tryRunResult && (
              <div style={{ marginBottom: 14 }}>
                {/* Step execution console */}
                {tryRunResult.step_results && tryRunResult.step_results.length > 0 && (
                  <div style={{
                    background: "#1a202c", borderRadius: 8, padding: 12, marginBottom: 10,
                    fontFamily: "monospace", fontSize: 12,
                  }}>
                    <div style={{ color: "#68d391", fontWeight: 600, marginBottom: 8 }}>▶ 執行紀錄</div>
                    {tryRunResult.step_results.map((sr, i) => (
                      <div key={i} style={{ marginBottom: 4, display: "flex", gap: 8, alignItems: "flex-start" }}>
                        <span>{sr.status === "ok" ? "✅" : "❌"}</span>
                        <span style={{ color: "#68d391" }}>{sr.step_id}</span>
                        <span style={{ color: "#a0aec0" }}>— {sr.nl_segment}</span>
                        {sr.error && <span style={{ color: "#fc8181" }}> {sr.error}</span>}
                      </div>
                    ))}
                  </div>
                )}

                {/* Result banner + RenderMiddleware */}
                <div style={{
                  background: tryRunResult.success ? "#f0fff4" : "#fff5f5",
                  border: `1px solid ${tryRunResult.success ? "#9ae6b4" : "#feb2b2"}`,
                  borderRadius: 8, padding: 12,
                }}>
                  <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: tryRunResult.success ? "#276749" : "#c53030" }}>
                    {tryRunResult.success ? "✅ Try-Run 成功" : "❌ Try-Run 失敗"}
                    {tryRunResult.total_elapsed_ms > 0 && (
                      <span style={{ fontWeight: 400, fontSize: 12, marginLeft: 8, color: "#718096" }}>
                        ({tryRunResult.total_elapsed_ms.toFixed(0)} ms)
                      </span>
                    )}
                  </div>
                  {tryRunResult.findings && <RenderMiddleware findings={tryRunResult.findings} outputSchema={outputSchema} charts={tryRunResult.charts} />}
                  {tryRunResult.error && (
                    <div style={{ color: "#c53030", fontSize: 12, marginTop: 4 }}>{tryRunResult.error}</div>
                  )}

                  {/* Feedback / fix panel — always shown after try-run so user can correct logic even on success */}
                  {editing?.id && (
                    <FixPanel ruleId={editing.id} errorMessage={tryRunResult.error || ""} onFixed={() => { setTryRunResult(null); }} />
                  )}
                </div>
              </div>
            )}

            {error && <div style={S.error}>{error}</div>}

            {/* Action buttons */}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
              <button style={S.btn("#a0aec0")} onClick={() => setShowModal(false)}>取消</button>
              <button
                style={S.btn(canSave ? "#38a169" : "#a0aec0")}
                disabled={!canSave}
                onClick={handleSave}
              >
                {editing ? "更新 Rule" : "儲存 Rule"}
              </button>
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
          setPhase("idle");
          setConsoleLogs(prev => [...prev, { text: "❌ 已取消生成", ok: false }]);
        }}
        onConfirm={async (answers: ClarifyAnswer[]) => {
          setClarifyOpen(false);
          // Append answers to description and re-run with skip_clarify=true
          const enriched =
            meta.auto_check_description.trim() +
            "\n\n[使用者澄清]\n" +
            answers.map(a => `- ${a.label}：${a.value}`).join("\n");
          setConsoleLogs(prev => [...prev, { text: "✓ 已收到澄清，繼續生成..." }]);
          await runGenerateStream(enriched, true);
        }}
      />
    </div>
  );
}
