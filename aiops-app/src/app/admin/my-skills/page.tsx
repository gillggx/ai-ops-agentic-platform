"use client";

import { useEffect, useState, useRef } from "react";
import { ClarifyDialog, type ClarifyQuestion, type ClarifyAnswer } from "@/components/skill-builder/ClarifyDialog";
import { RenderMiddleware, type OutputSchemaField, type ChartDSL, type SkillFindings } from "@/components/operations/SkillOutputRenderer";

// ── Types ─────────────────────────────────────────────────────────────────────

type StepMapping = { step_id: string; nl_segment: string; python_code: string };
type InputField = { key: string; type: string; required: boolean; source?: string; description: string };
type OutputField = { key: string; type: string; label: string; unit?: string };

type TryRunResult = {
  success?: boolean;
  step_results?: Array<{ step_id: string; nl_segment: string; status: string; output?: unknown; error?: string }>;
  findings?: SkillFindings | null;
  charts?: ChartDSL[] | null;
  total_elapsed_ms?: number;
  error?: string;
};

type Skill = {
  id: string;
  name: string;
  description: string;
  auto_check_description: string;
  steps_mapping: StepMapping[];
  input_schema: InputField[];
  output_schema: OutputField[];
  binding_type: string;
  is_active: boolean;
  created_at: string;
};

type BuildPhase = "idle" | "generating" | "proposed" | "try_running" | "result_ok" | "result_fail";

// ── Styles ────────────────────────────────────────────────────────────────────

const S = {
  page: { padding: 0 } as React.CSSProperties,
  header: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 } as React.CSSProperties,
  title: { fontSize: 20, fontWeight: 700, color: "#1a202c" } as React.CSSProperties,
  btn: (color: string): React.CSSProperties => ({
    padding: "7px 14px", borderRadius: 6, border: "none", cursor: "pointer",
    fontSize: 13, fontWeight: 500, background: color, color: "#fff",
  }),
  btnSm: (color: string): React.CSSProperties => ({
    padding: "4px 10px", borderRadius: 5, border: "none", cursor: "pointer",
    fontSize: 11, fontWeight: 500, background: color, color: "#fff",
  }),
  card: { background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, marginBottom: 10 } as React.CSSProperties,
  cardRow: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px" } as React.CSSProperties,
  label: { fontSize: 11, color: "#718096", fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.3px" },
  input: { width: "100%", padding: "7px 10px", border: "1px solid #e2e8f0", borderRadius: 6, fontSize: 13 } as React.CSSProperties,
  textarea: { width: "100%", padding: "7px 10px", border: "1px solid #e2e8f0", borderRadius: 6, fontSize: 13, fontFamily: "inherit", resize: "vertical" as const, minHeight: 60 } as React.CSSProperties,
  code: { width: "100%", padding: "8px 10px", border: "1px solid #e2e8f0", borderRadius: 6, fontSize: 11, fontFamily: "monospace", resize: "vertical" as const, minHeight: 100, background: "#f7f8fc" } as React.CSSProperties,
  console: { background: "#1a202c", color: "#a0aec0", borderRadius: 8, padding: "12px 16px", fontSize: 11, fontFamily: "monospace", maxHeight: 300, overflowY: "auto" as const, whiteSpace: "pre-wrap" as const, marginBottom: 12 },
  badge: (color: string): React.CSSProperties => ({
    display: "inline-block", padding: "2px 8px", borderRadius: 10,
    fontSize: 10, fontWeight: 600, background: `${color}15`, color, border: `1px solid ${color}40`,
  }),
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function MySkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);

  // Create / Edit modal
  const [editing, setEditing] = useState<Skill | null>(null);
  const [creating, setCreating] = useState(false);
  const [meta, setMeta] = useState({ name: "", description: "", auto_check_description: "" });
  const [steps, setSteps] = useState<StepMapping[]>([]);
  const [inputSchema, setInputSchema] = useState<InputField[]>([]);
  const [outputSchema, setOutputSchema] = useState<OutputField[]>([]);

  // Build (LLM generate)
  const [buildPhase, setBuildPhase] = useState<BuildPhase>("idle");
  const [consoleLogs, setConsoleLogs] = useState<string[]>([]);
  const consoleRef = useRef<HTMLDivElement>(null);

  // Try-run
  const [tryRunResult, setTryRunResult] = useState<TryRunResult | null>(null);

  // Clarify dialog
  const [clarifyOpen, setClarifyOpen] = useState(false);
  const [clarifyQuestions, setClarifyQuestions] = useState<ClarifyQuestion[]>([]);

  // ── Fetch ──

  async function fetchSkills() {
    setLoading(true);
    try {
      const res = await fetch("/api/admin/my-skills");
      const data = await res.json();
      setSkills(Array.isArray(data) ? data : []);
    } catch { setSkills([]); }
    setLoading(false);
  }

  useEffect(() => { fetchSkills(); }, []);

  // ── CRUD ──

  async function handleSave() {
    const body = {
      ...meta,
      steps_mapping: steps,
      input_schema: inputSchema,
      output_schema: outputSchema,
    };
    const url = editing ? `/api/admin/my-skills/${editing.id}` : "/api/admin/my-skills";
    const method = editing ? "PATCH" : "POST";
    const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (res.ok) {
      setEditing(null);
      setCreating(false);
      fetchSkills();
    } else {
      const err = await res.json().catch(() => ({}));
      alert(`儲存失敗: ${(err as Record<string,string>).error || (err as Record<string,string>).message || res.statusText}`);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("確定刪除此 Skill？")) return;
    await fetch(`/api/admin/my-skills/${id}`, { method: "DELETE" });
    fetchSkills();
  }

  // ── LLM Generate ──

  async function handleGenerate() {
    if (!meta.auto_check_description.trim()) {
      alert("請先填寫 Skill 描述");
      return;
    }
    setBuildPhase("generating");
    setConsoleLogs([]);
    setSteps([]);
    setInputSchema([]);
    setOutputSchema([]);
    await runGenerateStream(meta.auto_check_description, false);
  }

  async function runGenerateStream(description: string, skipClarify: boolean) {
    try {
      const res = await fetch("/api/admin/my-skills/generate-steps", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description, skip_clarify: skipClarify }),
      });
      if (!res.ok || !res.body) {
        setBuildPhase("idle");
        alert("生成失敗");
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "clarify_needed") {
              const qs = (ev.questions ?? []) as ClarifyQuestion[];
              setConsoleLogs(prev => [...prev, `🤔 需要確認 ${qs.length} 件事`]);
              setClarifyQuestions(qs);
              setClarifyOpen(true);
              return;
            } else if (ev.type === "log" || ev.type === "phase") {
              setConsoleLogs(prev => [...prev, ev.message || ev.text || JSON.stringify(ev)]);
            } else if (ev.type === "done" || ev.type === "result") {
              const d = ev.data || ev;
              if (d.steps_mapping) setSteps(d.steps_mapping);
              if (d.input_schema) setInputSchema(d.input_schema);
              if (d.output_schema) setOutputSchema(d.output_schema);
              setBuildPhase("proposed");
            } else if (ev.type === "error") {
              setConsoleLogs(prev => [...prev, `ERROR: ${ev.message || ev.error}`]);
              setBuildPhase("idle");
            }
          } catch { /* skip non-JSON */ }
        }
      }
      if (buildPhase === "generating") setBuildPhase("proposed");
    } catch (e) {
      setConsoleLogs(prev => [...prev, `ERROR: ${e instanceof Error ? e.message : "unknown"}`]);
      setBuildPhase("idle");
    }
  }

  // ── Try-Run Draft ──

  async function handleTryRun() {
    setBuildPhase("try_running");
    setTryRunResult(null);
    try {
      const res = await fetch("/api/admin/my-skills/try-run-draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          steps_mapping: steps,
          output_schema: outputSchema,
          mock_payload: { equipment_id: "EQP-01", lot_id: "LOT-0001", step: "STEP_020" },
        }),
      });
      const data = await res.json();
      setTryRunResult(data);
      setBuildPhase(data.success !== false ? "result_ok" : "result_fail");
    } catch {
      setBuildPhase("result_fail");
    }
  }

  // ── Open edit modal ──

  function openEdit(skill: Skill) {
    setEditing(skill);
    setCreating(false);
    setMeta({ name: skill.name, description: skill.description, auto_check_description: skill.auto_check_description });
    setSteps(skill.steps_mapping || []);
    setInputSchema(skill.input_schema || []);
    setOutputSchema(skill.output_schema || []);
    setBuildPhase("idle");
    setConsoleLogs([]);
    setTryRunResult(null);
  }

  function openCreate() {
    setCreating(true);
    setEditing(null);
    setMeta({ name: "", description: "", auto_check_description: "" });
    setSteps([]);
    setInputSchema([]);
    setOutputSchema([]);
    setBuildPhase("idle");
    setConsoleLogs([]);
    setTryRunResult(null);
  }

  // ── Bind (upgrade to Auto-Patrol / Diagnostic Rule) ──

  async function handleBind(id: string, bindingType: string) {
    const label = bindingType === "event" ? "Auto-Patrol" : bindingType === "alarm" ? "Diagnostic Rule" : "Chat Only";
    if (!confirm(`確定將此 Skill 設為 ${label}？`)) return;
    const res = await fetch(`/api/admin/my-skills/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ binding_type: bindingType }),
    });
    if (res.ok) {
      alert(`已設為 ${label}`);
      fetchSkills();
    } else {
      const err = await res.json().catch(() => ({}));
      alert(`設定失敗: ${(err as Record<string, string>).error || "unknown"}`);
    }
  }

  // ── Auto-scroll console ──
  useEffect(() => {
    consoleRef.current?.scrollTo({ top: consoleRef.current.scrollHeight });
  }, [consoleLogs]);

  const showModal = creating || editing;

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>
      <div style={S.header}>
        <div>
          <h1 style={S.title}>My Skills</h1>
          <div style={{ fontSize: 12, color: "#718096", marginTop: 2 }}>
            Agent chat 常用分析工具 — 從對話 promote 或手動建立
          </div>
        </div>
        <button style={S.btn("#2b6cb0")} onClick={openCreate}>+ 建立 Skill</button>
      </div>

      {/* ── Skill List ── */}
      {loading ? (
        <div style={{ color: "#a0aec0", padding: 40, textAlign: "center" }}>載入中...</div>
      ) : skills.length === 0 ? (
        <div style={{ color: "#a0aec0", padding: 40, textAlign: "center", background: "#fff", borderRadius: 8, border: "1px solid #e2e8f0" }}>
          尚未建立任何 Skill。可從 Agent chat 的分析結果 promote，或按上方「建立 Skill」手動新增。
        </div>
      ) : (
        skills.map(skill => (
          <div key={skill.id} style={S.card}>
            <div style={S.cardRow}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 14, color: "#1a202c" }}>{skill.name}</div>
                <div style={{ fontSize: 12, color: "#718096", marginTop: 2 }}>
                  {skill.auto_check_description || skill.description || "—"}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                  <span style={S.badge("#2b6cb0")}>{skill.steps_mapping?.length || 0} steps</span>
                  <span style={S.badge(skill.binding_type === "none" ? "#718096" : "#38a169")}>
                    {skill.binding_type === "none" ? "Chat Only" : skill.binding_type === "event" ? "Auto-Patrol" : "Diagnostic Rule"}
                  </span>
                  <span style={{ fontSize: 10, color: "#a0aec0" }}>
                    {new Date(skill.created_at).toLocaleDateString("zh-TW")}
                  </span>
                </div>
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button style={S.btnSm("#4299e1")} onClick={() => openEdit(skill)}>編輯</button>
                {skill.binding_type === "none" && (
                  <>
                    <button style={S.btnSm("#38a169")} onClick={() => handleBind(skill.id, "event")}>設為 Auto-Patrol</button>
                    <button style={S.btnSm("#805ad5")} onClick={() => handleBind(skill.id, "alarm")}>設為 Diagnostic Rule</button>
                  </>
                )}
                {skill.binding_type !== "none" && (
                  <button style={S.btnSm("#718096")} onClick={() => handleBind(skill.id, "none")}>解除綁定</button>
                )}
                <button style={S.btnSm("#e53e3e")} onClick={() => handleDelete(skill.id)}>刪除</button>
              </div>
            </div>
          </div>
        ))
      )}

      {/* ── Create / Edit Modal ── */}
      {showModal && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <div style={{
            background: "#fff", borderRadius: 12, width: 820, maxHeight: "90vh", overflow: "auto",
            padding: 24, boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h2 style={{ fontSize: 18, fontWeight: 700 }}>{editing ? "編輯 Skill" : "建立 Skill"}</h2>
              <button onClick={() => { setCreating(false); setEditing(null); }} style={{ background: "none", border: "none", fontSize: 18, cursor: "pointer", color: "#718096" }}>✕</button>
            </div>

            {/* Meta fields */}
            <div style={{ display: "grid", gap: 12, marginBottom: 16 }}>
              <div>
                <div style={S.label}>名稱</div>
                <input style={S.input} value={meta.name} onChange={e => setMeta(p => ({ ...p, name: e.target.value }))} placeholder="e.g. STEP_020 SPC 管制圖" />
              </div>
              <div>
                <div style={S.label}>描述 (Agent 從 catalog 判斷何時使用此 Skill)</div>
                <textarea style={S.textarea} value={meta.auto_check_description} onChange={e => setMeta(p => ({ ...p, auto_check_description: e.target.value }))} placeholder="e.g. 查詢指定站點的 SPC 管制圖數據，產生 X-bar chart 並標示 OOC 異常" />
              </div>
            </div>

            {/* Generate button (create mode) */}
            {!editing && steps.length === 0 && (
              <div style={{ marginBottom: 16 }}>
                <button
                  style={S.btn(buildPhase === "generating" ? "#a0aec0" : "#38a169")}
                  onClick={handleGenerate}
                  disabled={buildPhase === "generating"}
                >
                  {buildPhase === "generating" ? "生成中..." : "🤖 AI 生成 Steps"}
                </button>
              </div>
            )}

            {/* AI Console */}
            {consoleLogs.length > 0 && (
              <div ref={consoleRef} style={S.console}>
                {consoleLogs.map((log, i) => (
                  <div key={i} style={{ color: log.startsWith("ERROR") ? "#fc8181" : "#a0aec0" }}>{log}</div>
                ))}
              </div>
            )}

            {/* Steps editor */}
            {steps.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ ...S.label, marginBottom: 8 }}>Steps ({steps.length})</div>
                {steps.map((step, i) => (
                  <div key={i} style={{ marginBottom: 12, background: "#f7f8fc", borderRadius: 8, padding: 12 }}>
                    <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: "#2b6cb0" }}>#{step.step_id}</span>
                      <span style={{ fontSize: 12, color: "#4a5568" }}>{step.nl_segment}</span>
                    </div>
                    <textarea
                      style={S.code}
                      value={step.python_code}
                      onChange={e => {
                        const updated = [...steps];
                        updated[i] = { ...step, python_code: e.target.value };
                        setSteps(updated);
                      }}
                    />
                  </div>
                ))}

                {/* Try-Run + Save buttons */}
                <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                  <button
                    style={S.btn(buildPhase === "try_running" ? "#a0aec0" : "#d69e2e")}
                    onClick={handleTryRun}
                    disabled={buildPhase === "try_running"}
                  >
                    {buildPhase === "try_running" ? "測試中..." : "▶ Try-Run"}
                  </button>
                  <button style={S.btn("#2b6cb0")} onClick={handleSave}>
                    💾 儲存
                  </button>
                </div>
              </div>
            )}

            {/* Try-Run result */}
            {tryRunResult && (
              <div style={{
                marginTop: 12, padding: 12, borderRadius: 8,
                background: tryRunResult.success !== false ? "#f0fff4" : "#fff5f5",
                border: `1px solid ${tryRunResult.success !== false ? "#9ae6b4" : "#feb2b2"}`,
              }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: tryRunResult.success !== false ? "#276749" : "#9b2c2c" }}>
                  {tryRunResult.success !== false ? "✅ Try-Run 成功" : "❌ Try-Run 失敗"}
                  {tryRunResult.total_elapsed_ms !== undefined && (
                    <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 400, color: "#718096" }}>
                      ({tryRunResult.total_elapsed_ms.toFixed(0)} ms)
                    </span>
                  )}
                </div>
                {tryRunResult.findings && (
                  <RenderMiddleware
                    findings={tryRunResult.findings}
                    outputSchema={outputSchema as OutputSchemaField[]}
                    charts={tryRunResult.charts}
                  />
                )}
                {tryRunResult.error && (
                  <div style={{ color: "#c53030", fontSize: 12, marginTop: 4 }}>{tryRunResult.error}</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Inline clarification dialog */}
      <ClarifyDialog
        open={clarifyOpen}
        questions={clarifyQuestions}
        onCancel={() => {
          setClarifyOpen(false);
          setBuildPhase("idle");
          setConsoleLogs(prev => [...prev, "❌ 已取消生成"]);
        }}
        onConfirm={async (answers: ClarifyAnswer[]) => {
          setClarifyOpen(false);
          const enriched =
            meta.auto_check_description.trim() +
            "\n\n[使用者澄清]\n" +
            answers.map(a => `- ${a.label}：${a.value}`).join("\n");
          setConsoleLogs(prev => [...prev, "✓ 已收到澄清，繼續生成..."]);
          await runGenerateStream(enriched, true);
        }}
      />
    </div>
  );
}
