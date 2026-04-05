"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { McpChartRenderer } from "@/components/McpChartRenderer";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SchemaField { name: string; type: string; description: string; required?: boolean }
interface MCPDef {
  id: number;
  name: string;
  description: string;
  mcp_type: "system" | "custom";
  system_mcp_id: number | null;
  processing_intent: string;
  processing_script: string | null;
  sample_output: Record<string, unknown> | null;
  input_schema: { fields?: SchemaField[] } | null;
  api_config: { endpoint_url?: string; method?: string } | null;
  prefer_over_system: boolean;
  updated_at: string;
}

interface TryRunResult {
  success: boolean;
  script: string;
  output_data: Record<string, unknown>;
  summary: string;
  error?: string;
  error_analysis?: string;
  error_type?: string;
  suggested_prompt?: string;
  llm_elapsed_s: number;
  sandbox_elapsed_s: number;
  output_records: number;
}

interface IntentCheckResult {
  is_clear: boolean;
  questions: string[];
  suggested_prompt: string;
}

// ── API ───────────────────────────────────────────────────────────────────────

const PROXY = "/api/admin/automation";

async function apiFetch(method: string, path: string, body?: unknown) {
  const r = await fetch(`${PROXY}/${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d?.detail ?? d?.message ?? "請求失敗");
  return d.data ?? d;
}

// ── Styles ────────────────────────────────────────────────────────────────────

const inp: React.CSSProperties = {
  width: "100%", padding: "8px 12px", borderRadius: 6, fontSize: 13,
  border: "1px solid #e2e8f0", color: "#1a202c", outline: "none",
  boxSizing: "border-box", background: "#fff",
};
const sel: React.CSSProperties = { ...inp };

function btnStyle(variant: "primary" | "secondary" | "danger" | "ghost"): React.CSSProperties {
  return {
    padding: "8px 16px", borderRadius: 6, fontSize: 13, cursor: "pointer",
    fontWeight: variant === "primary" ? 600 : 400,
    border: variant === "secondary" ? "1px solid #e2e8f0"
          : variant === "danger"    ? "1px solid #fed7d7"
          : variant === "ghost"     ? "1px solid #e2e8f0"
          : "none",
    background: variant === "primary" ? "#3182ce"
              : variant === "danger"  ? "#fff5f5"
              : "#fff",
    color: variant === "primary" ? "#fff"
         : variant === "danger"  ? "#c53030"
         : "#4a5568",
  };
}

// ── MCP Picker ────────────────────────────────────────────────────────────────

const MCP_TAGS: Record<string, string[]> = {
  // 軌跡
  get_lot_trajectory:        ["軌跡"],
  get_tool_trajectory:       ["軌跡"],
  get_tool_step_trajectory:  ["軌跡"],
  get_object_history:        ["軌跡"],
  get_object_snapshot_history: ["軌跡"],
  // SPC
  get_step_spc_chart:        ["SPC"],
  search_ooc_events:         ["SPC"],
  get_process_context:       ["SPC", "DC"],
  get_ocap:                  ["SPC"],
  get_fdc_uchart:            ["SPC"],
  // DC
  get_baseline_stats:        ["DC"],
  get_dc_timeseries:         ["DC"],
  get_step_dc_timeseries:    ["DC"],
  get_equipment_constants:   ["DC"],
  query_object_timeseries:   ["DC", "SPC"],
  // 系統
  get_simulation_status:     ["系統"],
  list_lots:                 ["系統"],
  list_tools:                ["系統"],
  list_recent_events:        ["系統"],
  get_tools_status_overview: ["系統"],
};

const TAG_ICONS: Record<string, string> = {
  "SPC": "📊", "DC": "🌡", "軌跡": "🔍", "系統": "⚙",
};

const CATEGORIES = ["全部", "SPC", "DC", "軌跡", "系統"];

function getMcpTags(name: string): string[] {
  return MCP_TAGS[name] ?? ["系統"];
}

function McpPicker({
  systemMcps, selected, onSelect,
}: {
  systemMcps: MCPDef[];
  selected: number | "";
  onSelect: (id: number | "") => void;
}) {
  const [search, setSearch] = useState("");
  const [cat, setCat]       = useState("全部");

  const filtered = systemMcps.filter(m => {
    const tags = getMcpTags(m.name);
    const matchCat = cat === "全部" || tags.includes(cat);
    const q = search.toLowerCase();
    const matchQ = !q || m.name.toLowerCase().includes(q) || m.description.toLowerCase().includes(q);
    return matchCat && matchQ;
  });

  return (
    <div>
      {/* Search + tabs */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="🔍 搜尋 MCP 名稱或說明..."
          style={{ ...inp, fontSize: 12 }}
        />
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {CATEGORIES.map(c => (
            <button key={c} onClick={() => setCat(c)} style={{
              padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 600,
              cursor: "pointer", border: "none",
              background: cat === c ? "#3182ce" : "#edf2f7",
              color: cat === c ? "#fff" : "#4a5568",
              transition: "all 0.15s",
            }}>{c}</button>
          ))}
        </div>
      </div>

      {/* Card grid */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr",
        gap: 8, maxHeight: 320, overflowY: "auto",
        paddingRight: 2,
      }}>
        {filtered.length === 0 && (
          <div style={{ gridColumn: "1/-1", textAlign: "center", color: "#a0aec0", fontSize: 13, padding: "20px 0" }}>
            找不到符合的 MCP
          </div>
        )}
        {filtered.map(m => {
          const tags = getMcpTags(m.name);
          const isSelected = selected === m.id;
          const icon = TAG_ICONS[tags[0]] ?? "📦";
          // first line of description only
          const shortDesc = m.description.split("\n")[0].replace(/^【[^】]*】/, "").trim();
          return (
            <button key={m.id} onClick={() => onSelect(isSelected ? "" : m.id)} style={{
              textAlign: "left", cursor: "pointer", padding: "10px 12px",
              borderRadius: 8, border: `2px solid ${isSelected ? "#3182ce" : "#e2e8f0"}`,
              background: isSelected ? "#ebf8ff" : "#fff",
              transition: "all 0.15s",
              display: "flex", flexDirection: "column", gap: 4,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 16 }}>{icon}</span>
                <span style={{
                  fontSize: 12, fontWeight: 700,
                  color: isSelected ? "#2b6cb0" : "#1a202c",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  minWidth: 0, flex: 1, display: "block",
                }}>{m.name}</span>
              </div>
              <div style={{ fontSize: 11, color: "#718096", lineHeight: 1.4,
                overflow: "hidden", height: "2.8em",
              }}>{shortDesc}</div>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {tags.map(t => (
                  <span key={t} style={{
                    fontSize: 10, fontWeight: 600, padding: "1px 6px", borderRadius: 10,
                    background: "#edf2f7", color: "#4a5568",
                  }}>{t}</span>
                ))}
              </div>
            </button>
          );
        })}
      </div>

      {/* Selected detail */}
      {selected !== "" && (() => {
        const m = systemMcps.find(x => x.id === selected);
        if (!m) return null;
        return (
          <div style={{
            marginTop: 10, background: "#ebf8ff", border: "1px solid #bee3f8",
            borderRadius: 8, padding: 12,
          }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#2b6cb0", marginBottom: 4 }}>
              ✓ 已選：{m.name}
            </div>
            <div style={{ fontSize: 11, color: "#2c5282", whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
              {m.description}
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ── Step indicator ────────────────────────────────────────────────────────────

function StepBar({ current }: { current: number }) {
  const steps = ["資料源", "加工意圖", "生成腳本", "儲存"];
  return (
    <div style={{ display: "flex", alignItems: "center", marginBottom: 24 }}>
      {steps.map((label, i) => {
        const n = i + 1;
        const done = n < current;
        const active = n === current;
        return (
          <div key={n} style={{ display: "flex", alignItems: "center", flex: n < steps.length ? 1 : undefined }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div style={{
                width: 28, height: 28, borderRadius: "50%", display: "flex",
                alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700,
                background: done ? "#48bb78" : active ? "#3182ce" : "#e2e8f0",
                color: done || active ? "#fff" : "#a0aec0",
              }}>{done ? "✓" : n}</div>
              <div style={{ fontSize: 10, marginTop: 4, color: active ? "#3182ce" : "#718096", whiteSpace: "nowrap" }}>{label}</div>
            </div>
            {n < steps.length && (
              <div style={{ flex: 1, height: 2, background: done ? "#48bb78" : "#e2e8f0", margin: "0 4px", marginBottom: 16 }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function SamplePreview({ data }: { data: unknown }) {
  const text = JSON.stringify(data, null, 2);
  const preview = text.length > 1200 ? text.slice(0, 1200) + "\n…(truncated)" : text;
  return (
    <pre style={{
      background: "#1a202c", color: "#e2e8f0", padding: 12, borderRadius: 8,
      fontSize: 11, overflowX: "auto", maxHeight: 220, overflowY: "auto",
      fontFamily: "ui-monospace, monospace", lineHeight: 1.5, margin: 0,
    }}>{preview}</pre>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#a0aec0", textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 12 }}>{label}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>{children}</div>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#4a5568", marginBottom: 4 }}>
        {label}{required && <span style={{ color: "#e53e3e" }}> *</span>}
      </label>
      {children}
    </div>
  );
}

function NavRow({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, paddingTop: 8 }}>{children}</div>;
}

function ErrBox({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ background: "#fff5f5", border: "1px solid #fed7d7", borderRadius: 6, padding: "8px 12px", fontSize: 12, color: "#c53030", ...style }}>
      {children}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: 16, fontSize: 13 }}>
      <span style={{ color: "#718096", width: 80, flexShrink: 0 }}>{label}</span>
      <span style={{ color: "#1a202c" }}>{value}</span>
    </div>
  );
}

function Spinner() {
  return (
    <>
      <style>{`@keyframes aiops-spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{
        width: 18, height: 18, borderRadius: "50%",
        border: "2px solid #bee3f8", borderTopColor: "#3182ce",
        animation: "aiops-spin 0.8s linear infinite", flexShrink: 0,
      }} />
    </>
  );
}

// ── Description Quality Hint ─────────────────────────────────────────────────

function DescQualityHint({ desc }: { desc: string }) {
  const hints: string[] = [];
  if (desc.length < 50) hints.push("描述太短，建議至少 50 字");
  if (!/使用時機|when to use|用途|use case/i.test(desc)) hints.push("缺少「使用時機」說明");
  if (!/必填|param|step|tool_id|lot_id|step:|chart_name/i.test(desc)) hints.push("缺少必填參數說明");

  if (desc.length === 0) return null;
  if (hints.length === 0) {
    return (
      <div style={{ fontSize: 11, color: "#38a169", marginTop: 4 }}>
        ✅ 描述品質良好
      </div>
    );
  }
  return (
    <div style={{ fontSize: 11, color: "#d69e2e", marginTop: 4, display: "flex", flexDirection: "column", gap: 2 }}>
      {hints.map((h, i) => <span key={i}>⚠️ {h}</span>)}
    </div>
  );
}

// ── Drawer ────────────────────────────────────────────────────────────────────

function McpDrawer({
  editing, initialDraft, systemMcps, onClose, onSaved,
}: {
  editing: MCPDef | null;
  initialDraft?: Record<string, unknown> | null;
  systemMcps: MCPDef[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const d = initialDraft ?? {};
  const [step, setStep]                 = useState(1);
  const [name, setName]                 = useState(editing?.name ?? (d.name as string) ?? "");
  const [desc, setDesc]                 = useState(editing?.description ?? (d.description as string) ?? "");
  const [sysMcpId, setSysMcpId]         = useState<number | "">(editing?.system_mcp_id ?? (d.system_mcp_id as number) ?? "");
  const [sampleParams, setSampleParams] = useState<Record<string, string>>({});
  const [sampleData, setSampleData]     = useState<unknown>(editing?.sample_output ?? null);
  const [sampleLoading, setSampleLoading] = useState(false);
  const [sampleError, setSampleError]   = useState("");
  const [intent, setIntent]             = useState(editing?.processing_intent ?? (d.processing_intent as string) ?? "");
  const [intentCheck, setIntentCheck]   = useState<IntentCheckResult | null>(null);
  const [intentChecking, setIntentChecking] = useState(false);
  const [tryResult, setTryResult]       = useState<TryRunResult | null>(null);
  // edit mode: always start idle so user can re-run Try Run
  const [tryStatus, setTryStatus]       = useState<"idle"|"running"|"done"|"error">("idle");
  const [tryProgress, setTryProgress]   = useState("");
  const [saving, setSaving]             = useState(false);
  const [error, setError]               = useState("");
  const [similarityWarning, setSimilarityWarning] = useState<Array<{id: number; name: string; similarity: string; reason: string}>>([]);
  const [preferOverSystem, setPreferOverSystem]   = useState<boolean>(editing?.prefer_over_system ?? false);
  // Smart Try Run: track saved intent/script to skip LLM when nothing changed
  const [savedIntent, setSavedIntent]   = useState<string>(editing?.processing_intent ?? "");
  const [savedScript, setSavedScript]   = useState<string | null>(editing?.processing_script ?? null);
  const abortRef                        = useRef<AbortController | null>(null);

  const sysMcp = systemMcps.find(m => m.id === sysMcpId);
  const inputFields: SchemaField[] = sysMcp?.input_schema?.fields ?? [];

  // edit mode: auto-fetch sample if sample_output was not stored
  useEffect(() => {
    if (editing && sampleData === null && sysMcp) {
      fetchSample();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing?.id, sysMcp?.id]);

  async function fetchSample() {
    if (!sysMcp) return;
    setSampleLoading(true); setSampleError(""); setSampleData(null);
    try {
      // Build params object from input fields
      const params: Record<string, string> = {};
      for (const f of inputFields) {
        const v = sampleParams[f.name]?.trim();
        if (v) params[f.name] = v;
      }
      // Use backend proxy-fetch so CORS / cross-port issues are avoided
      const data = await apiFetch("POST", `mcp-definitions/${sysMcp.id}/sample-fetch`, params);
      setSampleData(data);
    } catch (e: unknown) {
      setSampleError(e instanceof Error ? e.message : "撈取失敗");
    } finally {
      setSampleLoading(false);
    }
  }

  async function checkIntent() {
    if (!intent.trim()) { setError("請先填寫加工意圖"); return; }
    setIntentChecking(true); setIntentCheck(null); setError("");
    try {
      const r = await apiFetch("POST", "mcp-definitions/check-intent", {
        processing_intent: intent,
        system_mcp_id: sysMcpId || null,
      });
      setIntentCheck(r as IntentCheckResult);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Intent check 失敗");
    } finally {
      setIntentChecking(false);
    }
  }

  async function runTryRun(forceRegenerate = false, overrideIntent?: string) {
    const useIntent = overrideIntent ?? intent;
    if (!useIntent.trim()) { setError("請填寫加工意圖"); return; }
    if (!sampleData)        { setError("請先撈取樣本資料（Step 1）"); return; }

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setTryStatus("running"); setTryResult(null); setError("");

    // Smart skip: if script exists and intent unchanged, run sandbox only (no LLM)
    const canSkipLLM = !forceRegenerate && !!savedScript && useIntent.trim() === savedIntent.trim() && !!editing;

    if (canSkipLLM) {
      setTryProgress("⚡ 使用已存程式碼，直接執行沙盒...");
      try {
        const result = await apiFetch("POST", `mcp-definitions/${editing!.id}/run-with-data`, { raw_data: sampleData });
        const r = result as TryRunResult;
        setTryResult(r);
        setTryStatus(r.success ? "done" : "error");
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "沙盒執行失敗");
        setTryStatus("error");
      }
      return;
    }

    setTryProgress("🧠 LLM 生成腳本中...");

    try {
      const r = await fetch(`${PROXY}/mcp-definitions/try-run-stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          processing_intent: useIntent,
          system_mcp_id: sysMcpId || null,
          sample_data: sampleData,
        }),
        signal: ctrl.signal,
      });

      const reader = r.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error("No response stream");

      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const payload = JSON.parse(line.slice(6));
            if (payload.type === "progress")    setTryProgress(payload.message);
            else if (payload.type === "done")  {
              const res = payload.result as TryRunResult;
              setTryResult(res);
              setTryStatus(res.success ? "done" : "error");
              // Update saved intent/script so next run can skip LLM
              if (res.success && res.script) { setSavedIntent(useIntent); setSavedScript(res.script); }
            }
            else if (payload.type === "error") { setError(payload.message); setTryStatus("error"); }
          } catch { /* skip malformed line */ }
        }
      }
    } catch (e: unknown) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "Try-run 失敗");
        setTryStatus("error");
      }
    }
  }

  async function save() {
    if (!name.trim()) { setError("請填寫 MCP 名稱"); return; }
    setSaving(true); setError("");
    try {
      if (editing) {
        await apiFetch("PATCH", `mcp-definitions/${editing.id}`, {
          name, description: desc,
          processing_intent: intent,
          prefer_over_system: preferOverSystem,
          ...(tryResult?.script ? {
            processing_script: tryResult.script,
            sample_output: tryResult.output_data,
          } : {}),
        });
      } else {
        const created = await apiFetch("POST", "mcp-definitions", {
          name, description: desc,
          mcp_type: "custom",
          system_mcp_id: sysMcpId || null,
          processing_intent: intent,
        }) as MCPDef;
        await apiFetch("PATCH", `mcp-definitions/${created.id}`, {
          prefer_over_system: preferOverSystem,
          ...(tryResult?.script ? {
            processing_script: tryResult.script,
            sample_output: tryResult.output_data,
          } : {}),
        });
      }
      onSaved(); onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "儲存失敗");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 200, display: "flex", justifyContent: "flex-end" }}>
      <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.3)" }} onClick={onClose} />
      <div style={{
        position: "relative", width: 640, height: "100%",
        background: "#fff", overflowY: "auto",
        boxShadow: "-4px 0 24px rgba(0,0,0,0.15)",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{
          padding: "16px 24px", borderBottom: "1px solid #e2e8f0",
          display: "flex", justifyContent: "space-between", alignItems: "center",
          position: "sticky", top: 0, background: "#fff", zIndex: 1,
        }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: "#1a202c" }}>
            {editing ? `編輯 MCP — ${editing.name}` : "新增 MCP"}
          </h2>
          <button onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer", fontSize: 22, color: "#718096" }}>×</button>
        </div>

        <div style={{ padding: 24, flex: 1 }}>
          <StepBar current={step} />

          {/* ── Step 1 ── */}
          {step === 1 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <Section label="Step 1 · 基本設定 & 資料源">
                <Field label="MCP 名稱" required>
                  <input value={name} onChange={e => setName(e.target.value)} style={inp} placeholder="e.g. APC_Drift_Summary" />
                </Field>
                <Field label="說明">
                  <textarea value={desc} onChange={e => setDesc(e.target.value)} style={{ ...inp, resize: "vertical" }} rows={3} placeholder="這個 MCP 的用途..." />
                  <DescQualityHint desc={desc} />
                </Field>
              </Section>

              <Section label="選定資料源 (System MCP)">
                <McpPicker
                  systemMcps={systemMcps}
                  selected={sysMcpId}
                  onSelect={id => { setSysMcpId(id); setSampleData(null); setSampleError(""); }}
                />

                {inputFields.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", textTransform: "uppercase" }}>撈取參數</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {inputFields.map(f => (
                        <Field key={f.name} label={`${f.name}${f.required ? " *" : ""}`}>
                          <input value={sampleParams[f.name] ?? ""} onChange={e => setSampleParams(p => ({ ...p, [f.name]: e.target.value }))} style={inp} placeholder={f.description} />
                        </Field>
                      ))}
                    </div>
                  </div>
                )}

                {sysMcp && (
                  <button onClick={fetchSample} disabled={sampleLoading} style={btnStyle("secondary")}>
                    {sampleLoading ? "⏳ 撈取中..." : "📡 撈取樣本資料"}
                  </button>
                )}
                {sampleError && <ErrBox>{sampleError}</ErrBox>}
                {sampleData !== null && (
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "#48bb78", marginBottom: 6 }}>✓ 樣本資料 (Raw Data Preview)</div>
                    <SamplePreview data={sampleData} />
                  </div>
                )}
                {sysMcpId && (
                  <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4, cursor: "pointer", fontSize: 13, color: "#2d3748" }}>
                    <input
                      type="checkbox"
                      checked={preferOverSystem}
                      onChange={e => setPreferOverSystem(e.target.checked)}
                      style={{ width: 15, height: 15, cursor: "pointer" }}
                    />
                    <span>優先呼叫此 MCP — AI 目錄中隱藏底層 System MCP</span>
                  </label>
                )}
              </Section>

              <NavRow>
                <button style={btnStyle("secondary")} onClick={onClose}>取消</button>
                <button style={btnStyle("primary")} onClick={async () => {
                  if (!name.trim()) { setError("請填寫 MCP 名稱"); return; }
                  if (!sysMcpId)    { setError("請選擇 System MCP"); return; }
                  if (!sampleData)  { setError("請先撈取樣本資料"); return; }
                  setError("");
                  // similarity check (non-blocking warning)
                  if (desc.trim().length >= 10) {
                    try {
                      const res = await apiFetch("POST", "mcp-definitions/check-similarity", {
                        name, description: desc, exclude_id: editing?.id ?? null,
                      });
                      const conflicts = res?.data?.conflicts ?? [];
                      setSimilarityWarning(conflicts);
                      if (conflicts.length > 0) return; // show warning, don't advance
                    } catch { /* ignore similarity check errors */ }
                  }
                  setSimilarityWarning([]);
                  setStep(2);
                }}>下一步 →</button>
              </NavRow>

              {similarityWarning.length > 0 && (
                <div style={{ background: "#fffbeb", border: "1px solid #f6e05e", borderRadius: 8, padding: "12px 16px", marginTop: 8 }}>
                  <div style={{ fontWeight: 600, fontSize: 12, color: "#744210", marginBottom: 6 }}>
                    ⚠️ 偵測到相似 MCP，可能造成 Agent 混淆：
                  </div>
                  {similarityWarning.map(c => (
                    <div key={c.id} style={{ fontSize: 12, color: "#744210", marginBottom: 4 }}>
                      · <strong>{c.name}</strong>（{c.similarity === "high" ? "高度相似" : "中度相似"}）— {c.reason}
                    </div>
                  ))}
                  <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                    <button style={{ ...btnStyle("secondary"), fontSize: 12 }} onClick={() => setSimilarityWarning([])}>
                      修改描述
                    </button>
                    <button style={{ ...btnStyle("primary"), fontSize: 12 }} onClick={() => { setSimilarityWarning([]); setStep(2); }}>
                      忽略，繼續建立
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Step 2 ── */}
          {step === 2 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <Section label="Step 2 · 加工意圖 (Processing Intent)">
                <p style={{ fontSize: 12, color: "#718096", margin: "0 0 8px" }}>
                  用自然語言描述 AI 應如何加工這批資料。越具體越好。
                </p>
                <Field label="加工意圖" required>
                  <textarea
                    value={intent}
                    onChange={e => { setIntent(e.target.value); setIntentCheck(null); }}
                    style={{ ...inp, resize: "vertical", minHeight: 120 }}
                    rows={6}
                    placeholder={`範例：
• 計算每台機台 APC 補償參數移動平均，偵測近 5 批的漂移趨勢，超過 ±3σ 標記 DRIFT
• 計算各站點 DC 量測值的 OOC 率，只回傳 OOC > 10% 的站點
• 把 SPC Xbar-R 數據摘要成每台機台的 Cp/Cpk 指標`}
                  />
                </Field>
                <button onClick={checkIntent} disabled={intentChecking || !intent.trim()} style={{ ...btnStyle("secondary"), alignSelf: "flex-start" }}>
                  {intentChecking ? "⏳ AI 檢查中..." : "🔍 檢查意圖清晰度"}
                </button>

                {intentCheck && (
                  <div style={{ borderRadius: 8, padding: 14, background: intentCheck.is_clear ? "#f0fff4" : "#fffbeb", border: `1px solid ${intentCheck.is_clear ? "#68d391" : "#f6e05e"}` }}>
                    <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: intentCheck.is_clear ? "#276749" : "#744210" }}>
                      {intentCheck.is_clear ? "✓ 意圖清晰，可以直接試跑" : "⚠ 建議補充以下資訊："}
                    </div>
                    {intentCheck.questions.length > 0 && (
                      <ul style={{ margin: "0 0 10px", padding: "0 0 0 18px", fontSize: 12, color: "#744210" }}>
                        {intentCheck.questions.map((q, i) => <li key={i}>{q}</li>)}
                      </ul>
                    )}
                    {intentCheck.suggested_prompt && (
                      <div>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "#2b6cb0", marginBottom: 6 }}>✨ AI 改寫建議：</div>
                        <div style={{ background: "#fff", border: "1px solid #bee3f8", borderRadius: 6, padding: 10, fontSize: 12, color: "#2d3748", whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
                          {intentCheck.suggested_prompt}
                        </div>
                        <button onClick={() => { setIntent(intentCheck.suggested_prompt); setIntentCheck(null); }} style={{ ...btnStyle("primary"), marginTop: 8, fontSize: 12, padding: "6px 14px" }}>
                          套用改寫
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </Section>

              <NavRow>
                <button style={btnStyle("secondary")} onClick={() => setStep(1)}>← 上一步</button>
                <button style={btnStyle("primary")} onClick={() => { if (!intent.trim()) { setError("請填寫加工意圖"); return; } setError(""); setStep(3); }}>
                  下一步 →
                </button>
              </NavRow>
            </div>
          )}

          {/* ── Step 3 ── */}
          {step === 3 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <Section label="Step 3 · 生成腳本 & 驗證 (Try Run)">
                <div style={{ background: "#f7f8fc", borderRadius: 8, padding: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 4 }}>加工意圖</div>
                  <div style={{ fontSize: 13, color: "#2d3748", whiteSpace: "pre-wrap" }}>{intent}</div>
                </div>

                {tryStatus === "idle" && (() => {
                  const canSkip = !!savedScript && intent.trim() === savedIntent.trim() && !!editing;
                  return (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {canSkip && (
                        <div style={{ fontSize: 12, color: "#276749", background: "#f0fff4", border: "1px solid #9ae6b4", borderRadius: 6, padding: "8px 12px" }}>
                          ⚡ 偵測到已有程式碼且意圖未變更，將直接執行沙盒（跳過 LLM）
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 8 }}>
                        <button onClick={() => runTryRun(false)} style={btnStyle("primary")}>
                          {canSkip ? "▶ 執行沙盒驗證" : "▶ 執行 Try Run（LLM 生成腳本 + 沙盒驗證）"}
                        </button>
                        {canSkip && (
                          <button onClick={() => runTryRun(true)} style={btnStyle("ghost")}>
                            🔄 強制重新生成程式碼
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })()}

                {tryStatus === "running" && (
                  <div style={{ display: "flex", alignItems: "center", gap: 12, padding: 16, background: "#ebf8ff", borderRadius: 8 }}>
                    <Spinner />
                    <span style={{ fontSize: 13, color: "#2b6cb0" }}>{tryProgress}</span>
                  </div>
                )}

                {tryResult && tryStatus === "done" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <div style={{ background: "#f0fff4", border: "1px solid #68d391", borderRadius: 8, padding: 14 }}>
                      <div style={{ fontWeight: 600, color: "#276749", marginBottom: 4 }}>✓ Try Run 通過！</div>
                      <div style={{ fontSize: 12, color: "#4a5568" }}>{tryResult.summary}</div>
                      <div style={{ fontSize: 11, color: "#718096", marginTop: 6 }}>
                        LLM: {tryResult.llm_elapsed_s.toFixed(1)}s · Sandbox: {tryResult.sandbox_elapsed_s.toFixed(1)}s · {tryResult.output_records} 筆輸出
                      </div>
                    </div>

                    {/* Chart preview — render ui_render.charts if present */}
                    {(() => {
                      const uiRender = (tryResult.output_data as Record<string, unknown>)?.ui_render as Parameters<typeof McpChartRenderer>[0]["uiRender"];
                      const dataset  = (tryResult.output_data as Record<string, unknown>)?.dataset as Record<string, unknown>[];
                      const hasChart = uiRender && ((uiRender.charts?.length ?? 0) > 0 || !!uiRender.chart_data);
                      if (!hasChart && !dataset?.length) return null;
                      return <McpChartRenderer uiRender={uiRender} dataset={dataset} />;
                    })()}

                    <details style={{ background: "#1a202c", borderRadius: 8, overflow: "hidden" }}>
                      <summary style={{ padding: "10px 14px", cursor: "pointer", fontSize: 12, color: "#a0aec0", fontWeight: 600 }}>▼ 查看生成的 processing_script</summary>
                      <pre style={{ padding: "0 14px 14px", fontSize: 11, color: "#e2e8f0", fontFamily: "ui-monospace, monospace", overflowX: "auto", lineHeight: 1.6 }}>{tryResult.script}</pre>
                    </details>
                    <details>
                      <summary style={{ padding: "8px 0", cursor: "pointer", fontSize: 12, color: "#718096", fontWeight: 600 }}>▼ 查看原始輸出 JSON</summary>
                      <SamplePreview data={tryResult.output_data} />
                    </details>
                    <button onClick={() => { setTryStatus("idle"); setTryResult(null); }} style={btnStyle("ghost")}>↩ 重新驗證</button>
                  </div>
                )}

                {tryStatus === "error" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    <div style={{ background: "#fff5f5", border: "1px solid #fed7d7", borderRadius: 8, padding: 14 }}>
                      <div style={{ fontWeight: 600, color: "#c53030", marginBottom: 4 }}>✗ Try Run 失敗</div>
                      {(tryResult?.error_analysis ?? error) && (
                        <div style={{ fontSize: 12, color: "#744210", whiteSpace: "pre-wrap" }}>{tryResult?.error_analysis ?? error}</div>
                      )}
                    </div>
                    {tryResult?.suggested_prompt && (
                      <div style={{ background: "#ebf8ff", border: "1px solid #bee3f8", borderRadius: 8, padding: 12 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "#2b6cb0", marginBottom: 6 }}>✨ AI 建議修改意圖：</div>
                        <div style={{ fontSize: 12, color: "#2d3748", whiteSpace: "pre-wrap" }}>{tryResult.suggested_prompt}</div>
                        <button onClick={() => { setIntent(tryResult.suggested_prompt!); setTryStatus("idle"); setTryResult(null); setStep(2); }} style={{ ...btnStyle("primary"), fontSize: 12, padding: "6px 14px", marginTop: 10 }}>
                          套用建議 → 修改意圖
                        </button>
                      </div>
                    )}
                    <button onClick={() => runTryRun()} style={btnStyle("secondary")}>重試 Try Run</button>
                  </div>
                )}
              </Section>

              <NavRow>
                <button style={btnStyle("secondary")} onClick={() => setStep(2)}>← 上一步</button>
                <button
                  style={{ ...btnStyle("primary"), ...(tryStatus !== "done" ? { opacity: 0.4, cursor: "not-allowed" } : {}) }}
                  disabled={tryStatus !== "done"}
                  onClick={() => { setError(""); setStep(4); }}
                >
                  下一步 →（須 Try Run 通過）
                </button>
              </NavRow>
            </div>
          )}

          {/* ── Step 4 ── */}
          {step === 4 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <Section label="Step 4 · 確認 & 儲存">
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <SummaryRow label="名稱" value={name} />
                  <SummaryRow label="說明" value={desc || "—"} />
                  <SummaryRow label="資料源" value={sysMcp?.name ?? "—"} />
                  <SummaryRow label="輸出筆數" value={tryResult?.output_records?.toString() ?? "—"} />
                  <SummaryRow label="LLM 耗時" value={tryResult ? `${tryResult.llm_elapsed_s.toFixed(1)}s` : "—"} />
                </div>
                <div style={{ marginTop: 4 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>加工意圖</div>
                  <div style={{ background: "#f7f8fc", borderRadius: 8, padding: 12, fontSize: 13, color: "#2d3748", whiteSpace: "pre-wrap" }}>{intent}</div>
                </div>
              </Section>

              <NavRow>
                <button style={btnStyle("secondary")} onClick={() => setStep(3)}>← 上一步</button>
                {editing && (
                  <button style={btnStyle("danger")} onClick={async () => {
                    if (!confirm("確定刪除這個 MCP？")) return;
                    await apiFetch("DELETE", `mcp-definitions/${editing.id}`);
                    onSaved(); onClose();
                  }}>刪除</button>
                )}
                <button style={{ ...btnStyle("primary"), ...(saving ? { opacity: 0.5 } : {}) }} disabled={saving} onClick={save}>
                  {saving ? "儲存中..." : editing ? "更新 MCP" : "建立 MCP"}
                </button>
              </NavRow>
            </div>
          )}

          {error && <ErrBox style={{ marginTop: 12 }}>{error}</ErrBox>}
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function McpBuilderPage() {
  const [systemMcps, setSystemMcps] = useState<MCPDef[]>([]);
  const [loading, setLoading]       = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const system = await apiFetch("GET", "mcp-definitions?type=system");
      setSystemMcps(Array.isArray(system) ? system : []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#1a202c" }}>System MCPs</h1>
        <p style={{ margin: "4px 0 0", fontSize: 13, color: "#718096" }}>
          唯讀：平台註冊的底層資料來源 (System MCPs)。Custom MCP 已廢棄，
          若需加工/呈現邏輯請改用 <a href="/admin/skills" style={{ color: "#4299e1" }}>Skills</a>。
        </p>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 48, color: "#718096" }}>載入中…</div>
      ) : systemMcps.length === 0 ? (
        <div style={{ background: "#fff", borderRadius: 10, padding: 56, textAlign: "center", border: "1px solid #e2e8f0" }}>
          <p style={{ color: "#718096", fontSize: 15, margin: 0 }}>尚未載入任何 System MCP</p>
        </div>
      ) : (
        <div style={{ background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f7f8fc", borderBottom: "1px solid #e2e8f0" }}>
                {["名稱", "說明", "Endpoint"].map(h => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#718096", textTransform: "uppercase", letterSpacing: "0.4px" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {systemMcps.map(mcp => (
                <tr key={mcp.id} style={{ borderBottom: "1px solid #f7f8fc" }}>
                  <td style={{ padding: "12px 16px", fontWeight: 600, color: "#1a202c" }}>{mcp.name}</td>
                  <td style={{ padding: "12px 16px", color: "#4a5568", maxWidth: 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{mcp.description || "—"}</td>
                  <td style={{ padding: "12px 16px", color: "#718096", fontSize: 11, fontFamily: "monospace" }}>
                    {(() => {
                      const raw = mcp.api_config as unknown;
                      let cfg: Record<string, unknown> = {};
                      if (typeof raw === "string") {
                        try { cfg = JSON.parse(raw); } catch { /* ignore */ }
                      } else if (raw && typeof raw === "object") {
                        cfg = raw as Record<string, unknown>;
                      }
                      return (cfg.endpoint_url as string) || "—";
                    })()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
