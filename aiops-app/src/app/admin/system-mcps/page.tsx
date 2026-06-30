"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import McpResultView from "@/components/admin/McpResultView";
import { T, card, secTitle, secHint, flabel, inp as tinp, btn as tbtn, pill } from "@/components/admin/mcpTheme";

// ── Description sections ────────────────────────────────────────────────────
// MCP descriptions follow a `== Section ==` convention (all 9 system MCPs do).
// Parse into sections for the preview rows + modal; serialize back to a single
// text field on save. Round-trip safe: a doc with no headers becomes one
// untitled section and serializes back to exactly its text.

interface DescSection { title: string; body: string; }

function parseDescriptionSections(text: string): DescSection[] {
  const raw = text ?? "";
  const re = /^==\s*(.+?)\s*==\s*$/gm;
  const marks: { title: string; start: number; bodyStart: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw)) !== null) {
    marks.push({ title: m[1], start: m.index, bodyStart: m.index + m[0].length });
  }
  if (marks.length === 0) return [{ title: "", body: raw.trim() }];
  const sections: DescSection[] = [];
  const preamble = raw.slice(0, marks[0].start).trim();
  if (preamble) sections.push({ title: "", body: preamble });
  marks.forEach((mk, i) => {
    const end = i + 1 < marks.length ? marks[i + 1].start : raw.length;
    sections.push({ title: mk.title, body: raw.slice(mk.bodyStart, end).trim() });
  });
  return sections;
}

function serializeDescriptionSections(sections: DescSection[]): string {
  return sections
    .map(s => (s.title ? `== ${s.title} ==\n${s.body}`.trim() : s.body.trim()))
    .filter(Boolean)
    .join("\n\n");
}

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
  input_schema: { fields?: SchemaField[] } | string | null;
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
  // V54 — derivative toggles + drafts
  producesBlock: boolean;
  producesSkill: boolean;
  blockDraft: BlockDraft | null;
  skillDraft: SkillDraft | null;
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
  // Detail GET returns input_schema as a JSON string (DB TEXT column serialized
  // by Jackson as a String DTO field); the list endpoint sends an object or
  // nothing. Accept both so inputs render regardless of source.
  let obj: Record<string, unknown>;
  if (typeof input_schema === "string") {
    try { obj = JSON.parse(input_schema) as Record<string, unknown>; }
    catch { return []; }
  } else {
    obj = input_schema as Record<string, unknown>;
  }
  const fields = obj.fields;
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
    ? { bg: "#fffaf0", border: "#feebc8", fg: "#9c4221", icon: "[!]" }
    : { bg: "#f0fff4", border: "#c6f6d5", fg: "#22543d", icon: "[ok]" };

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
            ↻ 重新生成
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
                  {committingRegen ? "更新中..." : "[ok] 確認覆寫"}
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

// ── Presentational helpers (design 1a) ─────────────────────────────────────

function FormBlock({ title, hint, action, children }: {
  title: string; hint?: string; action?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div style={card}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span style={secTitle}>{title}</span>
          {hint && <span style={secHint}>{hint}</span>}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function Field({ label, required, style, children }: {
  label: string; required?: boolean; style?: React.CSSProperties; children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 12, ...style }}>
      <label style={flabel}>{label}{required && <span style={{ color: T.danger }}> *</span>}</label>
      {children}
    </div>
  );
}

function DescriptionSectionsView({ sections, onOpen }: {
  sections: DescSection[]; onOpen: (idx: number) => void;
}) {
  if (sections.length === 1 && !sections[0].title && !sections[0].body) {
    return <div style={{ fontSize: 12.5, color: T.faint, padding: "4px 2px" }}>尚無說明 — 點「Expand &amp; edit」撰寫</div>;
  }
  return (
    <>
      {sections.map((s, i) => (
        <div key={i} onClick={() => onOpen(i)} className="mcp-desc-row" style={{
          display: "flex", gap: 10, padding: "9px 11px", border: `1px solid ${T.bdIn}`,
          borderRadius: 10, background: "#fff", cursor: "pointer", marginBottom: 7,
        }}>
          <div style={{ width: 3, borderRadius: 3, background: T.accentSoft, flex: "0 0 3px" }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: T.accentMid }}>
              {s.title || "說明"}
            </div>
            <div style={{ fontSize: 12.5, color: T.muted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", marginTop: 2 }}>
              {s.body.replace(/\n+/g, " · ") || "（空）"}
            </div>
          </div>
          <span style={{ fontSize: 11, fontWeight: 600, color: T.accentFaint, alignSelf: "center", whiteSpace: "nowrap" }}>Details ›</span>
        </div>
      ))}
      <div style={{ fontSize: 11.5, color: T.accentFaint, marginTop: 2 }}>ⓘ 點任一段可讀 / 編輯全文（存回 DB 仍是單一 text 欄）</div>
    </>
  );
}

function DescriptionModal({ open, sections, focused, mcpName, onFocus, onChange, onClose, onDone }: {
  open: boolean; sections: DescSection[]; focused: number; mcpName: string;
  onFocus: (i: number) => void; onChange: (i: number, body: string) => void;
  onClose: () => void; onDone: () => void;
}) {
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const chars = sections.reduce((n, s) => n + s.body.length, 0);
  useEffect(() => {
    if (!open) return;
    const el = bodyRef.current?.querySelector(`[data-sec="${focused}"]`) as HTMLElement | null;
    if (el && bodyRef.current) bodyRef.current.scrollTop = el.offsetTop - 12;
  }, [open, focused]);
  if (!open) return null;
  return (
    <div onClick={e => { if (e.target === e.currentTarget) onClose(); }} style={{
      position: "fixed", inset: 0, zIndex: 70, background: "rgba(15,23,42,.45)", backdropFilter: "blur(2px)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{
        width: "min(780px, 94vw)", maxHeight: "86vh", background: "#fff", borderRadius: 18,
        boxShadow: "0 24px 70px rgba(15,23,42,.3)", display: "flex", flexDirection: "column", overflow: "hidden",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "16px 22px", borderBottom: `1px solid ${T.hair}`, background: T.subtle2 }}>
          <span style={secTitle}>Description</span>
          <span style={{ fontFamily: T.mono, fontSize: 14, fontWeight: 600 }}>{mcpName}</span>
          <span style={{ fontFamily: T.mono, fontSize: 12, color: T.faint }}>{chars} chars</span>
          <button onClick={onClose} style={{ marginLeft: "auto", width: 32, height: 32, border: `1px solid ${T.bd}`, borderRadius: 9, background: "#fff", cursor: "pointer", fontSize: 16, color: T.muted }}>×</button>
        </div>
        <div style={{ display: "flex", gap: 8, padding: "12px 22px", borderBottom: `1px solid ${T.hair}`, flexWrap: "wrap" }}>
          {sections.map((s, i) => (
            <button key={i} onClick={() => onFocus(i)} style={{
              fontSize: 12, fontWeight: 600, borderRadius: 20, padding: "4px 12px", cursor: "pointer",
              border: `1px solid ${i === focused ? T.accentSoft : T.bdIn}`,
              background: i === focused ? T.accentBg : "#fff", color: i === focused ? T.accent : T.muted,
            }}>{s.title || "說明"}</button>
          ))}
        </div>
        <div ref={bodyRef} style={{ padding: 22, overflow: "auto", display: "flex", flexDirection: "column", gap: 18 }}>
          {sections.map((s, i) => (
            <div key={i} data-sec={i}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6, display: "flex", gap: 8, alignItems: "center", color: i === focused ? T.accent : T.muted }}>
                {s.title || "說明"}
                {i === focused && <span style={{ fontSize: 10, fontWeight: 700, color: T.accent, background: T.accentBg, borderRadius: 5, padding: "1px 6px" }}>opened here</span>}
              </div>
              <textarea value={s.body} onChange={e => onChange(i, e.target.value)} rows={s.body.length > 120 ? 6 : 3} style={{
                width: "100%", padding: "12px 14px", fontSize: 13.5, lineHeight: 1.6, color: T.labelC,
                border: `1px solid ${i === focused ? T.accentSoft : T.bdIn}`, borderRadius: 10,
                background: i === focused ? "#fafbff" : "#fff", fontFamily: T.sans, resize: "vertical", boxSizing: "border-box",
              }} />
            </div>
          ))}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 9, padding: "14px 22px", borderTop: `1px solid ${T.hair}`, background: T.subtle }}>
          <button style={tbtn("ghost")} onClick={onClose}>Cancel</button>
          <button style={tbtn("primary")} onClick={onDone}>Done</button>
        </div>
      </div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function SystemMcpAdminPage() {
  const [mcps, setMcps]     = useState<SystemMcp[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<SystemMcp | null>(null);
  // Tracks the currently-selected id for async guards (detail GET races).
  const selectedIdRef = useRef<number | null>(null);
  const [isNew, setIsNew]   = useState(false);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState<EditForm>({
    name: "", description: "", endpoint_url: "", method: "GET", schemaFields: [],
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

  // Description expand-edit modal. descDraft holds the working copy; only
  // committed back to form.description on "Done" so an un-edited open never
  // rewrites (and risks reformatting) the stored text.
  const [descModalOpen, setDescModalOpen] = useState(false);
  const [descFocused, setDescFocused] = useState(0);
  const [descDraft, setDescDraft] = useState<DescSection[]>([]);

  // Test params: auto-populated from schemaFields
  const [testParams, setTestParams] = useState<Record<string, string>>({});
  const [testRaw, setTestRaw] = useState<unknown>(undefined);
  const [testError, setTestError] = useState<string | null>(null);
  const [testLatency, setTestLatency] = useState<number | null>(null);
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
    selectedIdRef.current = mcp.id;
    setIsNew(false);
    setTestRaw(undefined); setTestError(null);
    setLintIssues([]);
    setGenMeta(null);
    setRegenerateStage("idle");
    const cfg = (mcp.api_config ?? {}) as Record<string, string>;
    const fields = parseSchemaFields(mcp.input_schema);
    setForm({
      name:           mcp.name,
      description:    mcp.description ?? "",
      endpoint_url:   cfg.endpoint_url ?? "",
      method:         cfg.method ?? "GET",
      schemaFields:   fields,
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
      if (detail) {
        setSelected(s => (s && s.id === mcp.id ? { ...s, ...detail } : s));
        // The list Summary omits input_schema and detail sends it as a JSON
        // string; re-derive the inputs from detail so the schema fields show.
        // Guard on id so a fast re-select doesn't clobber the new selection.
        setForm(f => (selectedIdRef.current === mcp.id
          ? { ...f, schemaFields: parseSchemaFields(detail.input_schema) }
          : f));
      }
    } catch {
      /* non-fatal — banner just falls back to neutral state */
    }
  }

  function openNew() {
    setSelected(null);
    selectedIdRef.current = null;
    setIsNew(true);
    setTestRaw(undefined); setTestError(null);
    setLintIssues([]);
    setGenMeta(null);
    setForm({
      name: "", description: "", endpoint_url: "", method: "GET", schemaFields: [],
      producesBlock: false, producesSkill: false, blockDraft: null, skillDraft: null,
    });
    setTestParams({});
  }

  function closePanel() {
    setSelected(null);
    selectedIdRef.current = null;
    setIsNew(false);
    setTestRaw(undefined); setTestError(null);
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
      api_config:   { endpoint_url: form.endpoint_url, method: form.method },
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
      api_config:   { endpoint_url: form.endpoint_url, method: form.method },
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
    setTestRaw(undefined);
    setTestError(null);
    const t0 = (typeof performance !== "undefined" ? performance.now() : Date.now());
    try {
      // Filter out empty string values so optional params aren't sent as ""
      const params: Record<string, string> = {};
      Object.entries(testParams).forEach(([k, v]) => { if (v.trim()) params[k] = v.trim(); });
      const res = await apiFetch("POST", `mcp-definitions/${selected.id}/sample-fetch`, params);
      // Unwrap our API envelope one level so the renderer sees the MCP payload.
      const payload = res && typeof res === "object" && "data" in res ? (res as { data: unknown }).data : res;
      setTestRaw(payload);
      setTestLatency(Math.round((typeof performance !== "undefined" ? performance.now() : Date.now()) - t0));
    } catch (e) {
      setTestError(String(e));
    }
    setTestLoading(false);
  }

  // ── Description modal ──────────────────────────────────────────────────────

  const descSections = parseDescriptionSections(form.description);

  function openDescModal(idx = 0) {
    setDescDraft(parseDescriptionSections(form.description));
    setDescFocused(idx);
    setDescModalOpen(true);
  }
  function commitDescModal() {
    setForm(f => ({ ...f, description: serializeDescriptionSections(descDraft) }));
    setDescModalOpen(false);
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const panelOpen = !!selected || isNew;

  return (
    <div style={{ fontFamily: T.sans }}>
      {/* ── List view ── */}
      {!panelOpen && (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
            <div>
              <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>System MCPs</h1>
              <p style={{ fontSize: 13, color: T.muted, margin: "4px 0 0" }}>管理底層資料來源 MCP（endpoint_url / input_schema）</p>
            </div>
            <button style={tbtn("primary")} onClick={openNew}>+ 新增 System MCP</button>
          </div>
          {loading ? (
            <div style={{ color: T.faint, fontSize: 13, padding: 24 }}>載入中...</div>
          ) : (
            <div style={{ background: T.card, borderRadius: 14, border: `1px solid ${T.bd}`, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: T.panel }}>
                    {["ID", "名稱", "Method", "Endpoint URL", ""].map(h => (
                      <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontWeight: 700, color: T.muted, borderBottom: `1px solid ${T.bd}`, whiteSpace: "nowrap", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {mcps.length === 0 && (
                    <tr><td colSpan={5} style={{ padding: "24px 14px", color: T.faint, textAlign: "center" }}>尚無 System MCP</td></tr>
                  )}
                  {mcps.map(m => {
                    const cfg = (m.api_config ?? {}) as Record<string, string>;
                    return (
                      <tr key={m.id} onClick={() => selectMcp(m)} style={{ cursor: "pointer", borderBottom: `1px solid ${T.hair}` }}>
                        <td style={{ padding: "10px 14px", color: T.faint, fontFamily: T.mono }}>{m.id}</td>
                        <td style={{ padding: "10px 14px", fontWeight: 600, fontFamily: T.mono }}>{m.name}</td>
                        <td style={{ padding: "10px 14px" }}>
                          <span style={{ fontFamily: T.mono, fontSize: 11, fontWeight: 600, color: T.typeT, background: T.typeBg, borderRadius: 6, padding: "3px 9px" }}>{cfg.method ?? "GET"}</span>
                        </td>
                        <td style={{ padding: "10px 14px", color: T.muted, fontFamily: T.mono, fontSize: 11.5, maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{cfg.endpoint_url ?? "—"}</td>
                        <td style={{ padding: "10px 14px", textAlign: "right" }}>
                          <button style={tbtn("soft")} onClick={e => { e.stopPropagation(); selectMcp(m); }}>編輯</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ── Editor card (design 1a) ── */}
      {panelOpen && (
        <div style={{ background: T.card, border: `1px solid ${T.bd}`, borderRadius: 18, boxShadow: "0 8px 30px rgba(15,23,42,.06)", overflow: "hidden", display: "flex", flexDirection: "column", height: "calc(100vh - 120px)" }}>

          {/* TOP BAR */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 22px", borderBottom: `1px solid ${T.hair}`, background: T.subtle2, gap: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
              <button style={tbtn("ghost")} onClick={closePanel}>← 返回清單</button>
              <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.faint }}>{isNew ? "新增 System MCP" : `Edit #${selected?.id}`}</span>
                <span style={{ fontFamily: T.mono, fontSize: 17, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{form.name || "（未命名）"}</span>
              </div>
              {!isNew && (
                <div style={{ display: "flex", gap: 6 }}>
                  <span style={pill("sys")}>system</span>
                  <span style={pill("vis")}>{selected?.visibility ?? "private"}</span>
                  {selected && (selected.produces_block || selected.produces_skill) && (
                    <span style={pill("ok")}><span style={{ width: 7, height: 7, borderRadius: "50%", background: T.dot }} />derivatives</span>
                  )}
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: 9 }}>
              <button
                style={tbtn("primary")}
                onClick={handleSave}
                disabled={saving || !form.name || !form.endpoint_url || (isNew && form.producesBlock && !form.blockDraft) || (isNew && form.producesSkill && !form.skillDraft)}
                title={isNew && form.producesBlock && !form.blockDraft ? "請先生成 Block 草稿" : isNew && form.producesSkill && !form.skillDraft ? "請先生成 Skill 草稿" : ""}
              >
                {saving ? "儲存中..." : isNew ? "建立" : "Save"}
              </button>
              <button style={tbtn("ghost")} onClick={closePanel}>Cancel</button>
              {!isNew && <button style={tbtn("danger")} onClick={handleDelete}>Delete</button>}
            </div>
          </div>

          {/* BODY */}
          <div style={{ display: "flex", flex: 1, minHeight: 0 }}>

            {/* LEFT — form column */}
            <div style={{ flex: "0 0 480px", background: T.subtle, borderRight: `1px solid ${T.hair}`, padding: 22, display: "flex", flexDirection: "column", gap: 18, overflow: "auto" }}>

              <FormBlock title="Basic">
                <Field label="Name" required>
                  <input style={tinp} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. get_process_context" />
                </Field>
                <div style={{ display: "flex", gap: 10 }}>
                  <Field label="Method" style={{ flex: "0 0 110px", marginBottom: 0 }}>
                    <select style={{ ...tinp, cursor: "pointer" }} value={form.method} onChange={e => setForm(f => ({ ...f, method: e.target.value }))}>
                      <option value="GET">GET</option>
                      <option value="POST">POST</option>
                    </select>
                  </Field>
                  <Field label="Endpoint URL" required style={{ flex: 1, minWidth: 0, marginBottom: 0 }}>
                    <input style={tinp} value={form.endpoint_url} onChange={e => setForm(f => ({ ...f, endpoint_url: e.target.value }))} placeholder="http://localhost:8012/api/v1/..." />
                  </Field>
                </div>
              </FormBlock>

              <FormBlock
                title="Description"
                hint={`${form.description.trim().length} chars`}
                action={<button style={tbtn("soft")} onClick={() => openDescModal(0)}>⤢ Expand &amp; edit</button>}
              >
                <DescriptionSectionsView sections={descSections} onOpen={openDescModal} />
                {(showDerivativeUI || inlineLint.some(i => i.severity === "error")) && inlineLint.length > 0 && (
                  <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
                    {inlineLint.map((iss, idx) => (
                      <div key={idx} style={{
                        fontSize: 11, padding: "5px 8px", borderRadius: 6,
                        background: iss.severity === "error" ? "#fff5f5" : T.warnBg,
                        color:      iss.severity === "error" ? T.oocT : T.warnT,
                        border: `1px solid ${iss.severity === "error" ? T.dangerBd : T.warnBd}`,
                      }}>
                        [{iss.severity}] {iss.message}
                      </div>
                    ))}
                  </div>
                )}
              </FormBlock>

              <FormBlock title="Input parameters" action={<button style={tbtn("soft")} onClick={addField}>+ Add field</button>}>
                {form.schemaFields.length === 0 ? (
                  <div style={{ background: T.panel, border: `1px dashed ${T.faint2}`, borderRadius: 10, padding: "14px 12px", color: T.faint, fontSize: 12, textAlign: "center" }}>
                    尚無參數 — 點「+ Add field」加入
                  </div>
                ) : (
                  form.schemaFields.map((field, idx) => (
                    <div key={idx} style={{ border: `1px solid ${T.bdIn}`, borderRadius: 10, background: "#fff", padding: "9px 11px", marginBottom: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                        <input style={{ ...tinp, padding: "6px 9px", fontSize: 13, flex: 1, minWidth: 0 }} placeholder="field_name" value={field.name} onChange={e => updateField(idx, { name: e.target.value })} />
                        <select
                          style={{ ...tinp, width: "auto", padding: "5px 8px", fontSize: 11.5, fontWeight: 600, color: T.typeT, background: T.typeBg, border: "none", cursor: "pointer" }}
                          value={field.type}
                          onChange={e => updateField(idx, { type: e.target.value })}
                        >
                          {["string", "number", "integer", "boolean", "array", "object"].map(t => <option key={t} value={t}>{t}</option>)}
                        </select>
                        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, fontWeight: 700, color: field.required ? T.danger : T.faint2, whiteSpace: "nowrap", cursor: "pointer" }}>
                          <input type="checkbox" checked={field.required} onChange={e => updateField(idx, { required: e.target.checked })} style={{ cursor: "pointer" }} />REQUIRED
                        </label>
                        <span onClick={() => removeField(idx)} style={{ color: T.faint2, cursor: "pointer", fontSize: 16, lineHeight: 1 }}>×</span>
                      </div>
                      <input style={{ ...tinp, padding: "5px 9px", fontSize: 11.5, color: T.muted, marginTop: 6, fontFamily: T.sans }} placeholder="欄位說明（選填）" value={field.description} onChange={e => updateField(idx, { description: e.target.value })} />
                    </div>
                  ))
                )}
              </FormBlock>

              {(isNew || (selected && (selected.produces_block || selected.produces_skill))) && (
                <FormBlock title="Derivatives (V54)" hint="block + skill 連動">
                  {isNew && (
                    <DerivativeSection
                      form={form} setForm={setForm} generating={generating} hasLintError={hasLintError}
                      onGenerate={handleGenerate} lintIssues={lintIssues} genMeta={genMeta}
                    />
                  )}
                  {!isNew && selected && (selected.produces_block || selected.produces_skill) && (
                    <DerivativeBanner
                      status={selected.derivative_status ?? null}
                      producesBlock={Boolean(selected.produces_block)}
                      producesSkill={Boolean(selected.produces_skill)}
                      regenerateStage={regenerateStage} generating={generating} committingRegen={committingRegen}
                      onStartRegenerate={handleStartRegenerate} onCancelRegenerate={cancelRegenerate} onCommitRegenerate={handleCommitRegenerate}
                      lintIssues={lintIssues} genMeta={genMeta} form={form} setForm={setForm}
                    />
                  )}
                </FormBlock>
              )}
            </div>

            {/* RIGHT — Sample Fetch tester */}
            <div style={{ flex: 1, minWidth: 0, padding: 22, display: "flex", flexDirection: "column", gap: 16 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span style={secTitle}>Sample Fetch</span><span style={secHint}>try it</span>
                </div>
                {!isNew && <button style={tbtn("primary")} onClick={handleTest} disabled={testLoading}>{testLoading ? "撈取中…" : "▶ Run"}</button>}
              </div>

              {isNew ? (
                <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: T.faint, fontSize: 13, border: `1px dashed ${T.bd}`, borderRadius: 12 }}>
                  存檔後可在此測試 Sample Fetch 並檢視資料
                </div>
              ) : (
                <>
                  {form.schemaFields.length > 0 ? (
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, background: T.subtle, border: `1px solid ${T.hair}`, borderRadius: 12, padding: 14 }}>
                      {form.schemaFields.map(field => (
                        <div key={field.name} style={{ minWidth: 0 }}>
                          <div style={{ fontFamily: T.mono, fontSize: 12, fontWeight: 600, marginBottom: 4, display: "flex", gap: 5, alignItems: "center" }}>
                            {field.name}{field.required ? <span style={{ color: T.danger }}>*</span> : <span style={{ color: T.faint2, fontWeight: 500 }}>{field.type}</span>}
                          </div>
                          <input style={{ ...tinp, padding: "8px 10px", fontSize: 13 }} placeholder={field.required ? "" : "optional"} value={testParams[field.name] ?? ""} onChange={e => setTestParams(p => ({ ...p, [field.name]: e.target.value }))} />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div style={{ fontSize: 12, color: T.faint }}>此 MCP 無定義 input 參數，將直接呼叫 endpoint。</div>
                  )}
                  <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                    <McpResultView result={testRaw} loading={testLoading} error={testError} latencyMs={testLatency} />
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      <DescriptionModal
        open={descModalOpen} sections={descDraft} focused={descFocused} mcpName={form.name || "（未命名）"}
        onFocus={setDescFocused}
        onChange={(i, body) => setDescDraft(d => d.map((s, j) => j === i ? { ...s, body } : s))}
        onClose={() => setDescModalOpen(false)} onDone={commitDescModal}
      />
    </div>
  );
}
