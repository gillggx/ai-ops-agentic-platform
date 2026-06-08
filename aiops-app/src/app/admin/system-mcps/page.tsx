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
  // V54 — derivative flags carried by mcp_definitions
  produces_block?: boolean;
  produces_skill?: boolean;
  block_generation_meta?: string | null;
  // P1-5/P1-6 (2026-06-04) — live derivative status; only present on
  // GET /{id} (list endpoint omits it for cost). Null when neither
  // produces_block nor produces_skill is set.
  derivative_status?: DerivativeStatus | null;
}

// Mirrors Java MCPDerivativeService.DerivativeStatus (Jackson snake_case).
interface DerivativeStatus {
  is_stale: boolean;
  last_regenerated_at: string | null;
  has_block: boolean;
  has_skill: boolean | null;
  block_id: number | null;
  block_name: string | null;
  skill_id: number | null;
  skill_slug: string | null;
}

// V54 — LLM-generated draft shapes (mirrors Java MCPDerivativeService DTOs)
interface BlockDraft {
  block_name?: string;
  description?: string;
  param_schema?: Record<string, unknown>;
  examples?: Array<Record<string, unknown>>;
  output_columns_hint?: Array<Record<string, unknown>>;
}

interface SkillDraft {
  slug?: string;
  name?: string;
  use_case?: string;
  when_to_use?: string[];
  inputs_schema?: Array<Record<string, unknown>>;
  outputs_schema?: Record<string, unknown>;
  tags?: string[];
  default_params?: Record<string, unknown>;
}

interface LintIssue {
  severity: "error" | "warn";
  field: string;
  message: string;
}

interface GenerateResponse {
  block_draft?: BlockDraft | null;
  skill_draft?: SkillDraft | null;
  lint_issues?: LintIssue[];
  llm_model?: string;
  prompt_version?: string;
  input_tokens?: number;
  output_tokens?: number;
}

interface EditForm {
  name: string;
  description: string;
  endpoint_url: string;
  method: string;
  schemaFields: SchemaField[];
  // POC skill-library — custom HTTP headers for auth (Bearer / API key).
  // Each row is one header. `value` supports ${ENV_VAR} placeholders that
  // the sidecar resolves at runtime — secrets live in sidecar env, not DB.
  headers: HeaderField[];
  // V54 — derivative toggles + drafts
  producesBlock: boolean;
  producesSkill: boolean;
  blockDraft: BlockDraft | null;
  skillDraft: SkillDraft | null;
}

interface HeaderField {
  name: string;
  value: string;
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

// POC skill-library — pack endpoint + method + auth headers into api_config.
// `headers` is sent only when at least one row has a name; empty rows are
// dropped so the DB stays clean.
function buildApiConfig(form: { endpoint_url: string; method: string; headers: HeaderField[] }): Record<string, unknown> {
  const cfg: Record<string, unknown> = {
    endpoint_url: form.endpoint_url,
    method:       form.method,
  };
  const hdr: Record<string, string> = {};
  for (const h of form.headers) {
    const k = h.name.trim();
    if (!k) continue;
    hdr[k] = h.value;  // value may carry ${ENV_VAR} placeholders
  }
  if (Object.keys(hdr).length > 0) cfg.headers = hdr;
  return cfg;
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

// ── V54 Derivative Section sub-component ─────────────────────────────────────

interface DerivativeSectionProps {
  form: EditForm;
  setForm: React.Dispatch<React.SetStateAction<EditForm>>;
  generating: boolean;
  hasLintError: boolean;
  onGenerate: () => void;
  lintIssues: LintIssue[];
  genMeta: { model?: string; promptVersion?: string; inputTokens?: number; outputTokens?: number } | null;
}

function DerivativeSection({
  form, setForm, generating, hasLintError, onGenerate, lintIssues, genMeta,
}: DerivativeSectionProps) {
  const setBlockDraft = (patch: Partial<BlockDraft>) =>
    setForm(f => ({ ...f, blockDraft: { ...(f.blockDraft ?? {}), ...patch } }));
  const setSkillDraft = (patch: Partial<SkillDraft>) =>
    setForm(f => ({ ...f, skillDraft: { ...(f.skillDraft ?? {}), ...patch } }));

  const canGenerate = (form.producesBlock || form.producesSkill) && !hasLintError && form.name.trim();

  return (
    <>
      <div style={sectionLabel}>Pipeline Builder 衍生 (V54)</div>

      {/* Toggles */}
      <div style={{ ...fieldWrap, display: "flex", flexDirection: "column", gap: 6 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer", fontSize: 12, color: "#2d3748" }}>
          <input
            type="checkbox"
            checked={form.producesBlock}
            onChange={e => setForm(f => ({ ...f, producesBlock: e.target.checked, producesSkill: e.target.checked ? f.producesSkill : false }))}
            style={{ cursor: "pointer", width: 14, height: 14 }}
          />
          連動產生一個 <b>Data Block</b>（Pipeline Builder 可用）
        </label>
        <label style={{
          display: "flex", alignItems: "center", gap: 7, fontSize: 12,
          color: form.producesBlock ? "#2d3748" : "#cbd5e0",
          cursor: form.producesBlock ? "pointer" : "not-allowed",
        }}>
          <input
            type="checkbox"
            disabled={!form.producesBlock}
            checked={form.producesSkill}
            onChange={e => setForm(f => ({ ...f, producesSkill: e.target.checked }))}
            style={{ cursor: form.producesBlock ? "pointer" : "not-allowed", width: 14, height: 14 }}
          />
          同時建立一個 <b>Published Skill</b>（含 1-block pipeline，需先勾 block）
        </label>
      </div>

      {(form.producesBlock || form.producesSkill) && (
        <>
          {/* Generate button */}
          <button
            style={{ ...btn("primary"), width: "100%", marginBottom: 10 }}
            onClick={onGenerate}
            disabled={!canGenerate || generating}
            title={hasLintError ? "Description 不足以生成 — 請先補充" : ""}
          >
            {generating ? "生成中... (Haiku 4.5)" : "從 Description 生成 Block + Skill 草稿"}
          </button>

          {/* LLM lint feedback (server-side) */}
          {lintIssues.length > 0 && (
            <div style={{ marginBottom: 10, display: "flex", flexDirection: "column", gap: 4 }}>
              {lintIssues.map((iss, idx) => (
                <div key={idx} style={{
                  fontSize: 11, padding: "5px 8px", borderRadius: 4,
                  background: iss.severity === "error" ? "#fff5f5" : "#fffaf0",
                  color:      iss.severity === "error" ? "#c53030" : "#9c4221",
                  border: `1px solid ${iss.severity === "error" ? "#fed7d7" : "#feebc8"}`,
                }}>
                  [{iss.severity}] {iss.field}: {iss.message}
                </div>
              ))}
            </div>
          )}

          {/* Audit meta */}
          {genMeta?.model && (
            <div style={{ fontSize: 10, color: "#a0aec0", marginBottom: 10, fontFamily: "ui-monospace, monospace" }}>
              model={genMeta.model} prompt={genMeta.promptVersion} tokens={genMeta.inputTokens}/{genMeta.outputTokens}
            </div>
          )}

          {/* Block Draft editor */}
          {form.producesBlock && form.blockDraft && (
            <DraftCard title="Block 草稿（可編輯）">
              <DraftField label="block_name" value={form.blockDraft.block_name ?? ""} onChange={v => setBlockDraft({ block_name: v })} />
              <DraftField label="description" multiline value={form.blockDraft.description ?? ""} onChange={v => setBlockDraft({ description: v })} />
              <DraftJsonField label="param_schema (object)" value={form.blockDraft.param_schema ?? {}} onChange={v => setBlockDraft({ param_schema: v as Record<string, unknown> })} />
              <DraftJsonField label="examples (list)" value={form.blockDraft.examples ?? []} onChange={v => setBlockDraft({ examples: v as Array<Record<string, unknown>> })} />
              <DraftJsonField label="output_columns_hint (list)" value={form.blockDraft.output_columns_hint ?? []} onChange={v => setBlockDraft({ output_columns_hint: v as Array<Record<string, unknown>> })} />
            </DraftCard>
          )}

          {/* Skill Draft editor */}
          {form.producesSkill && form.skillDraft && (
            <DraftCard title="Skill 草稿（可編輯）">
              <DraftField label="slug" value={form.skillDraft.slug ?? ""} onChange={v => setSkillDraft({ slug: v })} />
              <DraftField label="name" value={form.skillDraft.name ?? ""} onChange={v => setSkillDraft({ name: v })} />
              <DraftField label="use_case (≤ 25 words)" multiline value={form.skillDraft.use_case ?? ""} onChange={v => setSkillDraft({ use_case: v })} />
              <DraftJsonField label="when_to_use (list)" value={form.skillDraft.when_to_use ?? []} onChange={v => setSkillDraft({ when_to_use: (v as string[]) })} />
              <DraftJsonField label="inputs_schema (list)" value={form.skillDraft.inputs_schema ?? []} onChange={v => setSkillDraft({ inputs_schema: v as Array<Record<string, unknown>> })} />
              <DraftJsonField label="outputs_schema (object)" value={form.skillDraft.outputs_schema ?? {}} onChange={v => setSkillDraft({ outputs_schema: v as Record<string, unknown> })} />
              <DraftJsonField label="tags (list)" value={form.skillDraft.tags ?? []} onChange={v => setSkillDraft({ tags: v as string[] })} />
              <DraftJsonField label="default_params (object)" value={form.skillDraft.default_params ?? {}} onChange={v => setSkillDraft({ default_params: v as Record<string, unknown> })} />
            </DraftCard>
          )}

          {/* Reminder if drafts missing */}
          {((form.producesBlock && !form.blockDraft) || (form.producesSkill && !form.skillDraft)) && (
            <div style={{
              fontSize: 11, color: "#718096", padding: "8px 10px",
              background: "#f7fafc", border: "1px dashed #cbd5e0", borderRadius: 6,
              marginBottom: 14,
            }}>
              點擊上方按鈕讓 LLM 生成草稿，或勾選後留空 — 儲存時會被擋下。
            </div>
          )}
        </>
      )}
    </>
  );
}

function DraftCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: "#f7fafc", border: "1px solid #e2e8f0", borderRadius: 6,
      padding: "10px 12px", marginBottom: 10,
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "#4a5568", marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}

function DraftField({ label, value, onChange, multiline }: {
  label: string; value: string; onChange: (v: string) => void; multiline?: boolean;
}) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, color: "#a0aec0", marginBottom: 2, fontFamily: "ui-monospace, monospace" }}>{label}</div>
      {multiline ? (
        <textarea
          style={{ ...inp, minHeight: 56, fontSize: 11, fontFamily: "ui-monospace, monospace", lineHeight: 1.4 }}
          value={value}
          onChange={e => onChange(e.target.value)}
        />
      ) : (
        <input style={{ ...inp, fontSize: 11, fontFamily: "ui-monospace, monospace" }} value={value} onChange={e => onChange(e.target.value)} />
      )}
    </div>
  );
}

function DraftJsonField({ label, value, onChange }: {
  label: string; value: unknown; onChange: (v: unknown) => void;
}) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setText(JSON.stringify(value, null, 2));
    setErr(null);
  }, [value]);

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, color: "#a0aec0", marginBottom: 2, fontFamily: "ui-monospace, monospace" }}>{label}</div>
      <textarea
        style={{
          ...inp, minHeight: 70, fontSize: 11, fontFamily: "ui-monospace, monospace",
          lineHeight: 1.4, background: err ? "#fff5f5" : "#fff",
        }}
        value={text}
        onChange={e => {
          const v = e.target.value;
          setText(v);
          try {
            const parsed = JSON.parse(v);
            setErr(null);
            onChange(parsed);
          } catch (parseErr) {
            setErr(String(parseErr));
          }
        }}
      />
      {err && <div style={{ fontSize: 10, color: "#c53030", marginTop: 2 }}>{err}</div>}
    </div>
  );
}

// ── P1-5 / P1-6 (2026-06-04) — DerivativeBanner sub-component ────────────────

interface DerivativeBannerProps {
  status: DerivativeStatus | null;
  producesBlock: boolean;
  producesSkill: boolean;
  regenerateStage: "idle" | "review";
  generating: boolean;
  committingRegen: boolean;
  onStartRegenerate: () => void;
  onCancelRegenerate: () => void;
  onCommitRegenerate: () => void;
  lintIssues: LintIssue[];
  genMeta: { model?: string; promptVersion?: string; inputTokens?: number; outputTokens?: number } | null;
  form: EditForm;
  setForm: React.Dispatch<React.SetStateAction<EditForm>>;
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec} 秒前`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分鐘前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小時前`;
  return `${Math.floor(sec / 86400)} 天前`;
}

function DerivativeBanner({
  status, producesBlock, producesSkill, regenerateStage,
  generating, committingRegen,
  onStartRegenerate, onCancelRegenerate, onCommitRegenerate,
  lintIssues, genMeta, form, setForm,
}: DerivativeBannerProps) {
  const setBlockDraft = (patch: Partial<BlockDraft>) =>
    setForm(f => ({ ...f, blockDraft: { ...(f.blockDraft ?? {}), ...patch } }));
  const setSkillDraft = (patch: Partial<SkillDraft>) =>
    setForm(f => ({ ...f, skillDraft: { ...(f.skillDraft ?? {}), ...patch } }));

  const isStale = Boolean(status?.is_stale);
  const hasError = lintIssues.some(i => i.severity === "error");

  // Banner palette
  const palette = isStale
    ? { bg: "#fffaf0", border: "#feebc8", fg: "#9c4221", icon: "⚠" }
    : { bg: "#f0fff4", border: "#c6f6d5", fg: "#22543d", icon: "✓" };

  const labels: string[] = [];
  if (producesBlock) labels.push("block");
  if (producesSkill) labels.push("skill");

  return (
    <div style={{
      marginBottom: 14, padding: "10px 12px",
      background: palette.bg, border: `1px solid ${palette.border}`, borderRadius: 6,
      fontSize: 12, color: palette.fg,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>
            {palette.icon} Pipeline Builder 衍生 ({labels.join(" + ")})
          </div>
          {isStale ? (
            <div>描述已變動，衍生內容可能過期。建議重新生成。</div>
          ) : (
            <div>上次生成：{formatRelativeTime(status?.last_regenerated_at ?? null)}</div>
          )}
          {status && (
            <div style={{ fontSize: 10, color: "#718096", marginTop: 3, fontFamily: "ui-monospace, monospace" }}>
              {status.block_name && `block=${status.block_name}`}
              {status.block_name && status.skill_slug && " · "}
              {status.skill_slug && `skill=${status.skill_slug}`}
            </div>
          )}
        </div>
        {regenerateStage === "idle" && (
          <button
            style={{ ...btn(isStale ? "primary" : "ghost"), padding: "6px 12px", fontSize: 12 }}
            onClick={onStartRegenerate}
            disabled={generating}
          >
            🔄 重新生成
          </button>
        )}
      </div>

      {regenerateStage === "review" && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px dashed ${palette.border}` }}>
          {generating ? (
            <div style={{ color: "#718096", fontSize: 12 }}>
              生成中... (Haiku 4.5)
            </div>
          ) : (
            <>
              {/* Lint feedback */}
              {lintIssues.length > 0 && (
                <div style={{ marginBottom: 10, display: "flex", flexDirection: "column", gap: 4 }}>
                  {lintIssues.map((iss, idx) => (
                    <div key={idx} style={{
                      fontSize: 11, padding: "5px 8px", borderRadius: 4,
                      background: iss.severity === "error" ? "#fff5f5" : "#fffaf0",
                      color:      iss.severity === "error" ? "#c53030" : "#9c4221",
                      border: `1px solid ${iss.severity === "error" ? "#fed7d7" : "#feebc8"}`,
                    }}>
                      [{iss.severity}] {iss.field}: {iss.message}
                    </div>
                  ))}
                </div>
              )}

              {genMeta?.model && (
                <div style={{ fontSize: 10, color: "#a0aec0", marginBottom: 10, fontFamily: "ui-monospace, monospace" }}>
                  model={genMeta.model} prompt={genMeta.promptVersion} tokens={genMeta.inputTokens}/{genMeta.outputTokens}
                </div>
              )}

              {producesBlock && form.blockDraft && (
                <DraftCard title="Block 草稿（覆寫現有 block，可編輯）">
                  <DraftField label="block_name" value={form.blockDraft.block_name ?? ""} onChange={v => setBlockDraft({ block_name: v })} />
                  <DraftField label="description" multiline value={form.blockDraft.description ?? ""} onChange={v => setBlockDraft({ description: v })} />
                  <DraftJsonField label="param_schema (object)" value={form.blockDraft.param_schema ?? {}} onChange={v => setBlockDraft({ param_schema: v as Record<string, unknown> })} />
                  <DraftJsonField label="examples (list)" value={form.blockDraft.examples ?? []} onChange={v => setBlockDraft({ examples: v as Array<Record<string, unknown>> })} />
                  <DraftJsonField label="output_columns_hint (list)" value={form.blockDraft.output_columns_hint ?? []} onChange={v => setBlockDraft({ output_columns_hint: v as Array<Record<string, unknown>> })} />
                </DraftCard>
              )}

              {producesSkill && form.skillDraft && (
                <DraftCard title="Skill 草稿（覆寫現有 skill，可編輯）">
                  <DraftField label="name" value={form.skillDraft.name ?? ""} onChange={v => setSkillDraft({ name: v })} />
                  <DraftField label="use_case (≤ 25 words)" multiline value={form.skillDraft.use_case ?? ""} onChange={v => setSkillDraft({ use_case: v })} />
                  <DraftJsonField label="when_to_use (list)" value={form.skillDraft.when_to_use ?? []} onChange={v => setSkillDraft({ when_to_use: (v as string[]) })} />
                  <DraftJsonField label="inputs_schema (list)" value={form.skillDraft.inputs_schema ?? []} onChange={v => setSkillDraft({ inputs_schema: v as Array<Record<string, unknown>> })} />
                  <DraftJsonField label="outputs_schema (object)" value={form.skillDraft.outputs_schema ?? {}} onChange={v => setSkillDraft({ outputs_schema: v as Record<string, unknown> })} />
                  <DraftJsonField label="tags (list)" value={form.skillDraft.tags ?? []} onChange={v => setSkillDraft({ tags: v as string[] })} />
                  <DraftJsonField label="default_params (object)" value={form.skillDraft.default_params ?? {}} onChange={v => setSkillDraft({ default_params: v as Record<string, unknown> })} />
                </DraftCard>
              )}

              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button
                  style={{ ...btn("primary"), padding: "6px 14px", fontSize: 12 }}
                  onClick={onCommitRegenerate}
                  disabled={committingRegen || hasError || !form.blockDraft}
                >
                  {committingRegen ? "更新中..." : "✓ 確認覆寫"}
                </button>
                <button
                  style={{ ...btn("ghost"), padding: "6px 14px", fontSize: 12 }}
                  onClick={onCancelRegenerate}
                  disabled={committingRegen}
                >
                  取消
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function SystemMcpAdminPage() {
  const [mcps, setMcps]     = useState<SystemMcp[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<SystemMcp | null>(null);
  const [isNew, setIsNew]   = useState(false);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState<EditForm>({
    name: "", description: "", endpoint_url: "", method: "GET", schemaFields: [], headers: [],
    producesBlock: false, producesSkill: false, blockDraft: null, skillDraft: null,
  });

  // V54 — derivative generation state
  const [generating, setGenerating] = useState(false);
  const [lintIssues, setLintIssues] = useState<LintIssue[]>([]);
  const [genMeta, setGenMeta] = useState<{ model?: string; promptVersion?: string; inputTokens?: number; outputTokens?: number } | null>(null);

  // P1-6 (2026-06-04) — regenerate flow for existing MCPs.
  // idle:    banner only, no draft panel
  // review:  LLM returned a draft (or generation is in flight); user edits + confirms
  const [regenerateStage, setRegenerateStage] = useState<"idle" | "review">("idle");
  const [committingRegen, setCommittingRegen] = useState(false);

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

  async function selectMcp(mcp: SystemMcp) {
    setSelected(mcp);
    setIsNew(false);
    setTestResult(null);
    setLintIssues([]);
    setGenMeta(null);
    setRegenerateStage("idle");
    const cfg = (mcp.api_config ?? {}) as Record<string, unknown>;
    const fields = parseSchemaFields(mcp.input_schema);
    const hdrObj = (cfg.headers ?? {}) as Record<string, string>;
    const headers: HeaderField[] = Object.entries(hdrObj).map(([k, v]) => ({
      name: k, value: String(v),
    }));
    setForm({
      name:           mcp.name,
      description:    mcp.description ?? "",
      endpoint_url:   String(cfg.endpoint_url ?? ""),
      method:         String(cfg.method ?? "GET"),
      schemaFields:   fields,
      headers,
      producesBlock:  Boolean(mcp.produces_block),
      producesSkill:  Boolean(mcp.produces_skill),
      blockDraft:     null,  // edit-mode regeneration starts from blank draft
      skillDraft:     null,
    });
    // P1-5 — list endpoint omits derivative_status (cost); hit detail GET so
    // the banner knows is_stale / last_regenerated_at.
    try {
      const res = await apiFetch("GET", `mcp-definitions/${mcp.id}`);
      const detail = (res.data ?? res) as SystemMcp | undefined;
      if (detail) setSelected(s => (s && s.id === mcp.id ? { ...s, ...detail } : s));
    } catch {
      /* non-fatal — banner just falls back to neutral state */
    }
  }

  function openNew() {
    setSelected(null);
    setIsNew(true);
    setTestResult(null);
    setLintIssues([]);
    setGenMeta(null);
    setForm({
      name: "", description: "", endpoint_url: "", method: "GET", schemaFields: [], headers: [],
      producesBlock: false, producesSkill: false, blockDraft: null, skillDraft: null,
    });
    setTestParams({});
  }

  function closePanel() {
    setSelected(null);
    setIsNew(false);
    setTestResult(null);
    setLintIssues([]);
    setGenMeta(null);
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

  // ── V54: Description lint (client-side mirror of sidecar's lint) ─────────

  const clientLint = useCallback((desc: string): LintIssue[] => {
    const issues: LintIssue[] = [];
    const text = (desc ?? "").trim();
    if (!text) {
      issues.push({ severity: "error", field: "description", message: "Description is empty." });
      return issues;
    }
    if (text.length < 200) {
      issues.push({ severity: "error", field: "description",
        message: `Description too short (${text.length} chars, need ≥ 200). LLM cannot generate usable drafts.` });
    } else if (text.length < 400) {
      issues.push({ severity: "warn", field: "description",
        message: `Description is short (${text.length} chars). LLM quality improves past 400.` });
    }
    const lower = text.toLowerCase();
    const hasReturns = /returns|return|回傳|回應|response|output/.test(lower);
    const hasUseWhen = /use when|use case|when to|when |用於|使用場景|情境/.test(lower);
    if (!hasReturns) {
      issues.push({ severity: "warn", field: "description",
        message: "Description doesn't appear to document what the MCP returns." });
    }
    if (!hasUseWhen) {
      issues.push({ severity: "warn", field: "description",
        message: "Description doesn't say WHEN to use this MCP." });
    }
    return issues;
  }, []);

  const inlineLint = clientLint(form.description);
  const hasLintError = inlineLint.some(i => i.severity === "error");
  const showDerivativeUI = form.producesBlock || form.producesSkill;

  // ── V54: Generate block + skill drafts via Java→sidecar ─────────────────

  async function handleGenerate() {
    if (hasLintError) {
      setLintIssues(inlineLint);
      return;
    }
    setGenerating(true);
    setLintIssues([]);
    const payload = {
      mcp_id:       selected?.id ?? null,
      name:         form.name,
      description:  form.description,
      input_schema: schemaFieldsToJson(form.schemaFields),
      output_schema: null,
      api_config:   buildApiConfig(form),
      want_block:   form.producesBlock,
      want_skill:   form.producesSkill,
    };
    const res = (await apiFetch("POST", "mcp-definitions/generate-derivatives", payload)) as
      { data?: GenerateResponse; error?: { message?: string } };

    const resp = res.data ?? (res as unknown as GenerateResponse);
    const issues = resp.lint_issues ?? [];
    setLintIssues(issues);
    setGenMeta({
      model:         resp.llm_model,
      promptVersion: resp.prompt_version,
      inputTokens:   resp.input_tokens,
      outputTokens:  resp.output_tokens,
    });

    const blockingError = issues.some(i => i.severity === "error");
    if (blockingError) {
      setGenerating(false);
      return;
    }
    setForm(f => ({
      ...f,
      blockDraft: form.producesBlock ? (resp.block_draft ?? f.blockDraft) : null,
      skillDraft: form.producesSkill ? (resp.skill_draft ?? f.skillDraft) : null,
    }));
    setGenerating(false);
  }

  // ── P1-6 (2026-06-04): Regenerate for existing MCP ─────────────────────

  async function handleStartRegenerate() {
    if (!selected) return;
    setGenerating(true);
    setLintIssues([]);
    setRegenerateStage("review");
    // Reuse the same proxy endpoint — sidecar treats mcp_id != null as a
    // regenerate. Returned drafts replace whatever was in form.
    const payload = {
      mcp_id:        selected.id,
      want_block:    Boolean(selected.produces_block),
      want_skill:    Boolean(selected.produces_skill),
    };
    try {
      const res = (await apiFetch("POST", "mcp-definitions/generate-derivatives", payload)) as
        { data?: GenerateResponse; error?: { message?: string } };
      const resp = res.data ?? (res as unknown as GenerateResponse);
      const issues = resp.lint_issues ?? [];
      setLintIssues(issues);
      setGenMeta({
        model:         resp.llm_model,
        promptVersion: resp.prompt_version,
        inputTokens:   resp.input_tokens,
        outputTokens:  resp.output_tokens,
      });
      setForm(f => ({
        ...f,
        blockDraft: selected.produces_block ? (resp.block_draft ?? null) : null,
        skillDraft: selected.produces_skill ? (resp.skill_draft ?? null) : null,
      }));
    } catch (e) {
      setLintIssues([{ severity: "error", field: "regenerate", message: String(e) }]);
    } finally {
      setGenerating(false);
    }
  }

  function cancelRegenerate() {
    setRegenerateStage("idle");
    setLintIssues([]);
    setGenMeta(null);
    setForm(f => ({ ...f, blockDraft: null, skillDraft: null }));
  }

  async function handleCommitRegenerate() {
    if (!selected || !form.blockDraft) return;
    setCommittingRegen(true);
    const payload: Record<string, unknown> = {
      block_draft: {
        block_name:          form.blockDraft.block_name,
        description:         form.blockDraft.description,
        param_schema:        JSON.stringify(form.blockDraft.param_schema ?? {}),
        examples:            JSON.stringify(form.blockDraft.examples ?? []),
        output_columns_hint: JSON.stringify(form.blockDraft.output_columns_hint ?? []),
      },
    };
    if (selected.produces_skill && form.skillDraft) {
      payload.skill_draft = {
        slug:           form.skillDraft.slug,
        name:           form.skillDraft.name,
        use_case:       form.skillDraft.use_case,
        when_to_use:    JSON.stringify(form.skillDraft.when_to_use ?? []),
        inputs_schema:  JSON.stringify(form.skillDraft.inputs_schema ?? []),
        outputs_schema: JSON.stringify(form.skillDraft.outputs_schema ?? {}),
        tags:           JSON.stringify(form.skillDraft.tags ?? []),
        default_params: JSON.stringify(form.skillDraft.default_params ?? {}),
      };
    }
    if (genMeta?.model) {
      payload.generation_meta = JSON.stringify({
        llm_model:           genMeta.model,
        prompt_version:      genMeta.promptVersion,
        generated_at:        new Date().toISOString(),
        last_regenerated_at: new Date().toISOString(),
      });
    }
    try {
      const res = (await apiFetch("POST",
        `mcp-definitions/${selected.id}/regenerate-derivatives`, payload)) as
        { data?: SystemMcp; error?: { message?: string } };
      const updated = res.data ?? (res as unknown as SystemMcp | undefined);
      if (updated && typeof updated.id === "number") {
        setSelected(s => (s ? { ...s, ...updated } : s));
      }
      setRegenerateStage("idle");
      setForm(f => ({ ...f, blockDraft: null, skillDraft: null }));
      setLintIssues([]);
      setGenMeta(null);
      loadList();
    } catch (e) {
      setLintIssues([{ severity: "error", field: "commit", message: String(e) }]);
    } finally {
      setCommittingRegen(false);
    }
  }

  // ── Save ─────────────────────────────────────────────────────────────────

  async function handleSave() {
    setSaving(true);
    const baseInput = {
      name:         form.name,
      description:  form.description,
      api_config:   buildApiConfig(form),
      input_schema: schemaFieldsToJson(form.schemaFields),
    };
    if (isNew) {
      // V54: when produces_block / produces_skill is true, include the
      // reviewed drafts so Java commits MCP + block + (pipeline + skill)
      // in one transaction. Drafts go in as snake_case JSON-stringified
      // sub-fields per the Java DTO contract.
      const payload: Record<string, unknown> = {
        ...baseInput,
        mcp_type:        "system",
        produces_block:  form.producesBlock,
        produces_skill:  form.producesSkill,
      };
      if (form.producesBlock && form.blockDraft) {
        payload.block_draft = {
          block_name:          form.blockDraft.block_name,
          description:         form.blockDraft.description,
          param_schema:        JSON.stringify(form.blockDraft.param_schema ?? {}),
          examples:            JSON.stringify(form.blockDraft.examples ?? []),
          output_columns_hint: JSON.stringify(form.blockDraft.output_columns_hint ?? []),
        };
      }
      if (form.producesSkill && form.skillDraft) {
        payload.skill_draft = {
          slug:           form.skillDraft.slug,
          name:           form.skillDraft.name,
          use_case:       form.skillDraft.use_case,
          when_to_use:    JSON.stringify(form.skillDraft.when_to_use ?? []),
          inputs_schema:  JSON.stringify(form.skillDraft.inputs_schema ?? []),
          outputs_schema: JSON.stringify(form.skillDraft.outputs_schema ?? {}),
          tags:           JSON.stringify(form.skillDraft.tags ?? []),
          default_params: JSON.stringify(form.skillDraft.default_params ?? {}),
        };
      }
      if (genMeta?.model) {
        payload.generation_meta = JSON.stringify({
          llm_model:      genMeta.model,
          prompt_version: genMeta.promptVersion,
          generated_at:   new Date().toISOString(),
        });
      }
      await apiFetch("POST", "mcp-definitions", payload);
    } else if (selected) {
      // Edit mode: PATCH the base fields only. Derivative regeneration
      // for existing MCPs is a separate flow (V54 spec §5 decision 2 —
      // manual regenerate only, no auto-sync).
      await apiFetch("PATCH", `mcp-definitions/${selected.id}`, baseInput);
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
              <label style={label}>
                說明
                <span style={{ marginLeft: 8, color: inlineLint.some(i => i.severity === "error") ? "#e53e3e" : "#a0aec0", fontWeight: 500 }}>
                  ({form.description.trim().length} chars)
                </span>
              </label>
              <textarea
                style={{ ...inp, minHeight: 110, fontFamily: "ui-monospace, monospace", lineHeight: 1.5, resize: "vertical" }}
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                placeholder={"完整描述此 MCP 的用途、回傳欄位與使用情境（建議 400 字以上）。\n用詞越具體，LLM 生成的 block / skill 草稿越準。"}
              />
              {/* V54: inline lint feedback — only show when derivative UI is on or there's an error */}
              {(showDerivativeUI || inlineLint.some(i => i.severity === "error")) && inlineLint.length > 0 && (
                <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                  {inlineLint.map((iss, idx) => (
                    <div key={idx} style={{
                      fontSize: 11, padding: "5px 8px", borderRadius: 4,
                      background: iss.severity === "error" ? "#fff5f5" : "#fffaf0",
                      color:      iss.severity === "error" ? "#c53030" : "#9c4221",
                      border: `1px solid ${iss.severity === "error" ? "#fed7d7" : "#feebc8"}`,
                    }}>
                      [{iss.severity}] {iss.message}
                    </div>
                  ))}
                </div>
              )}
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
                <input style={inp} value={form.endpoint_url} onChange={e => setForm(f => ({ ...f, endpoint_url: e.target.value }))} placeholder="https://api.example.com/v1/..." />
              </div>
            </div>

            {/* ── Section: Auth headers (POC) ───────────────────────────
                 Header values support ${ENV_VAR} placeholders. The sidecar
                 substitutes them at request time from python_ai_sidecar/.env
                 so secrets never sit in the DB. */}
            <div style={{ ...sectionLabel, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>HTTP Headers (optional)</span>
              <button style={btn("dim")} onClick={() => setForm(f => ({
                ...f, headers: [...f.headers, { name: "", value: "" }],
              }))}>+ 新增 header</button>
            </div>

            {form.headers.length === 0 ? (
              <div style={{
                background: "#f7f8fc", border: "1px dashed #cbd5e0",
                borderRadius: 6, padding: "10px 12px",
                color: "#a0aec0", fontSize: 11, marginBottom: 14,
                lineHeight: 1.5,
              }}>
                若 endpoint 需要 auth（Bearer / API key），點「+ 新增 header」。
                Value 可寫成 <code style={{ background: "#edf2f7", padding: "1px 4px", borderRadius: 3 }}>Bearer ${"{EXTERNAL_API_TOKEN}"}</code>
                — sidecar 會在發送時把 <code>${"{NAME}"}</code> 替換成 .env 中的環境變數。
              </div>
            ) : (
              <div style={{ marginBottom: 14 }}>
                {form.headers.map((h, idx) => (
                  <div key={idx} style={{
                    display: "grid", gridTemplateColumns: "180px 1fr 28px",
                    gap: 6, marginBottom: 6, alignItems: "center",
                  }}>
                    <input
                      style={{ ...inp, padding: "5px 8px", fontSize: 12, fontFamily: "ui-monospace, monospace" }}
                      placeholder="Authorization"
                      value={h.name}
                      onChange={e => setForm(f => {
                        const headers = [...f.headers];
                        headers[idx] = { ...headers[idx], name: e.target.value };
                        return { ...f, headers };
                      })}
                    />
                    <input
                      style={{ ...inp, padding: "5px 8px", fontSize: 12, fontFamily: "ui-monospace, monospace" }}
                      placeholder="Bearer ${EXTERNAL_API_TOKEN}"
                      value={h.value}
                      onChange={e => setForm(f => {
                        const headers = [...f.headers];
                        headers[idx] = { ...headers[idx], value: e.target.value };
                        return { ...f, headers };
                      })}
                    />
                    <button
                      style={{ ...btn("ghost"), padding: "4px 6px", fontSize: 11 }}
                      onClick={() => setForm(f => ({
                        ...f, headers: f.headers.filter((_, i) => i !== idx),
                      }))}
                      title="移除"
                    >×</button>
                  </div>
                ))}
                <div style={{ fontSize: 10, color: "#a0aec0", marginTop: 4 }}>
                  ${"{ENV_VAR}"} 會在 sidecar 端被替換成環境變數值。找不到變數 → 預先擋下，不會送出 request。
                </div>
              </div>
            )}

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

            {/* ── V54 Section: Pipeline Builder 衍生 ── */}
            {isNew && (
              <DerivativeSection
                form={form}
                setForm={setForm}
                generating={generating}
                hasLintError={hasLintError}
                onGenerate={handleGenerate}
                lintIssues={lintIssues}
                genMeta={genMeta}
              />
            )}

            {/* P1-5 / P1-6 (2026-06-04) — derivative banner: stale-aware + regenerate CTA */}
            {!isNew && selected && (selected.produces_block || selected.produces_skill) && (
              <DerivativeBanner
                status={selected.derivative_status ?? null}
                producesBlock={Boolean(selected.produces_block)}
                producesSkill={Boolean(selected.produces_skill)}
                regenerateStage={regenerateStage}
                generating={generating}
                committingRegen={committingRegen}
                onStartRegenerate={handleStartRegenerate}
                onCancelRegenerate={cancelRegenerate}
                onCommitRegenerate={handleCommitRegenerate}
                lintIssues={lintIssues}
                genMeta={genMeta}
                form={form}
                setForm={setForm}
              />
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
              <button
                style={btn("primary")}
                onClick={handleSave}
                disabled={
                  saving
                  || !form.name
                  || !form.endpoint_url
                  // V54: if a derivative is requested, the draft must exist
                  || (isNew && form.producesBlock && !form.blockDraft)
                  || (isNew && form.producesSkill && !form.skillDraft)
                }
                title={
                  isNew && form.producesBlock && !form.blockDraft
                    ? "請先生成 Block 草稿"
                    : isNew && form.producesSkill && !form.skillDraft
                    ? "請先生成 Skill 草稿"
                    : ""
                }
              >
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
