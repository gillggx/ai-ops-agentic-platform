"use client";

import React, { useState } from "react";

// SPEC_design_intent_confirm: when the agent is in builder mode and the user's
// prompt is too ambiguous to translate into a pipeline directly (e.g. "請確認
// 該機台最後一次 OOC 的 APC 參數"), the agent calls confirm_pipeline_intent
// and the sidecar emits a `design_intent_confirm` SSE event with this shape.
// Any panel hosting an agent stream can render the card; the onPick callback
// owns the post-click flow (auto follow-up POST or input pre-fill).

// 2026-05-04: presentation expanded to 8 canonical kinds matching the
// intent_completeness backend enum; "想修改" now opens a structured form
// (with progressive-disclosure JSON fallback) instead of a raw JSON editor.

export type PresentationKind =
  | "line_chart" | "bar_chart" | "control_chart" | "heatmap"
  | "table" | "alert" | "mixed_table_alert" | "mixed_chart_alert";

export interface DesignIntentInput {
  name: string;                      // canonical: tool_id / step / lot_id / ...
  source: "user_input" | "event_payload" | "literal";
  rationale?: string;
}

export interface DesignIntentAlternative {
  summary: string;
}

// 2026-05-11 Plan-Mode-style multi-choice clarifications. When the chat
// orchestrator calls confirm_pipeline_intent, the backend's deterministic
// detectors fire on the user prompt + declared inputs and produce these
// dimension cards. LLM only fills in question/label/hint (localization).
// User picks → selections get spliced into the [intent_confirmed:<id> dim=val ...]
// follow-up prefix, which the build_pipeline_live handler parses + augments
// the goal text with deterministic guidance hints.
export interface ClarificationOption {
  value: string;
  label: string;
  hint?: string | null;
}

export interface ClarificationDimension {
  dimension: string;
  question: string;
  options: ClarificationOption[];
  default?: string | null;
  multi?: boolean;
}

export interface DesignIntentData {
  card_id: string;
  inputs: DesignIntentInput[];
  logic: string;
  presentation: PresentationKind;
  alternatives?: DesignIntentAlternative[];
  clarifications?: ClarificationDimension[];
  /** picks per dimension; populated as user clicks radio buttons. */
  selections?: Record<string, string>;
  resolved?: boolean;
}

export type DesignIntentChoice = "confirm" | "cancel";

interface Props {
  data: DesignIntentData;
  /** Original prompt the user typed, used by the host to compose the
   *  follow-up message after confirm. */
  originalPrompt: string;
  /** confirm dispatches with the (possibly user-edited) spec; cancel just
   *  bails. The host applies the spec and forwards to the build agent. */
  onPick: (choice: DesignIntentChoice, data: DesignIntentData) => void;
}

const SOURCE_LABEL: Record<DesignIntentInput["source"], string> = {
  user_input: "user 填",
  event_payload: "事件帶",
  literal: "寫死",
};

// Canonical 8-way presentation enum + display metadata. Backend's
// _normalize_presentation guarantees the value is in this set; if a stale
// row arrives with an old value, fallback resolves to mixed_chart_alert.
const PRESENT_OPTIONS: Array<{ kind: PresentationKind; icon: string; label: string; hint: string }> = [
  { kind: "line_chart",        icon: "📈", label: "Line chart",   hint: "趨勢圖（時間 vs 值）" },
  { kind: "bar_chart",         icon: "📊", label: "Bar chart",    hint: "長條圖（站點 vs 計數）" },
  { kind: "control_chart",     icon: "🎯", label: "Control chart",hint: "管制圖（含 UCL/LCL）" },
  { kind: "heatmap",           icon: "🌡", label: "Heatmap",      hint: "熱圖（雙維度密度）" },
  { kind: "table",             icon: "📋", label: "Table",        hint: "表格" },
  { kind: "alert",             icon: "🔔", label: "Alert",        hint: "告警卡片" },
  { kind: "mixed_table_alert", icon: "⚙",  label: "Table + Alert",hint: "表格 + 告警" },
  { kind: "mixed_chart_alert", icon: "⚙",  label: "Chart + Alert",hint: "圖表 + 告警" },
];

// Canonical input names — must match backend _CANONICAL_INPUTS so Glass
// Box's HOT blocks bind cleanly. UI surfaces them in a dropdown for the
// edit form so the user can't pick a non-canonical name.
const CANONICAL_INPUT_NAMES: Array<{ value: string; label: string }> = [
  { value: "tool_id",     label: "tool_id      機台 (EQP-XX)" },
  { value: "step",        label: "step         站點 (STEP_XXX)" },
  { value: "lot_id",      label: "lot_id       批號 (LOT-XXXX)" },
  { value: "recipe_id",   label: "recipe_id    配方 (RCP-XXX)" },
  { value: "apc_id",      label: "apc_id       APC 模型" },
  { value: "time_range",  label: "time_range   時間區間 (24h / 7d)" },
  { value: "threshold",   label: "threshold    數值門檻" },
  { value: "object_name", label: "object_name  觀測對象 (SPC/APC/...)" },
];


export function DesignIntentCard({ data, onPick }: Props) {
  const disabled = !!data.resolved;
  const [editing, setEditing] = useState(false);
  // Local edit state — when user clicks 想修改 we copy data here and the
  // form mutates this. confirm dispatches with this state; cancel reverts.
  const [draft, setDraft] = useState<DesignIntentData>(data);
  // 2026-05-11: per-dimension picks. Initialize from defaults; user clicks
  // radios to override. Submitted via onPick(confirm, data-with-selections).
  const initSel = (): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const c of (data.clarifications ?? [])) {
      if (c.default) out[c.dimension] = c.default;
    }
    return out;
  };
  const [selections, setSelections] = useState<Record<string, string>>(initSel);
  const allRequiredPicked = (data.clarifications ?? [])
    .every((c) => selections[c.dimension] !== undefined && selections[c.dimension] !== "");

  const present = PRESENT_OPTIONS.find((o) => o.kind === data.presentation)
    ?? PRESENT_OPTIONS.find((o) => o.kind === "mixed_chart_alert")!;

  const submitWithSelections = () => onPick("confirm", { ...data, selections });

  return (
    <>
      <div style={{
        width: "100%",
        border: "1px solid #cbd5e0",
        borderRadius: 8,
        padding: "14px 16px",
        background: "#f7fafc",
        fontSize: 13,
        color: "#2d3748",
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          fontWeight: 700, marginBottom: 10, color: "#1a202c",
        }}>
          <span>🛠</span>
          <span>我想為你建這條 pipeline — 你看對嗎？</span>
        </div>

        <ReadView data={data} present={present} />

        {/* 2026-05-11 Plan-Mode multi-choice clarifications */}
        {(data.clarifications?.length ?? 0) > 0 && (
          <ClarificationGroups
            clarifications={data.clarifications ?? []}
            selections={selections}
            onChange={setSelections}
            disabled={disabled}
          />
        )}

        {/* Buttons */}
        <div style={{
          display: "flex", gap: 8, marginTop: 12,
          opacity: disabled ? 0.5 : 1,
        }}>
          <button
            disabled={disabled || !allRequiredPicked}
            onClick={submitWithSelections}
            title={!allRequiredPicked ? "請先選擇所有 ◯ 選項" : ""}
            style={btnStyle((disabled || !allRequiredPicked) ? "secondary-disabled" : "primary")}
          >✅ 開始建</button>
          <button
            disabled={disabled}
            onClick={() => { setDraft(data); setEditing(true); }}
            style={btnStyle(disabled ? "secondary-disabled" : "secondary")}
          >✏️ 想修改</button>
          <button
            disabled={disabled}
            onClick={() => onPick("cancel", data)}
            style={btnStyle(disabled ? "secondary-disabled" : "secondary")}
          >❌ 取消</button>
        </div>

        {disabled && (
          <div style={{ marginTop: 8, fontSize: 11, color: "#a0aec0" }}>已選擇</div>
        )}
      </div>

      {/* 2026-05-04 v3: editor lives in a modal so the chat sidebar isn't
          cramped by the 8-radio + JSON fallback form taking 700+px. */}
      {editing && (
        <EditModal
          draft={draft}
          onChange={setDraft}
          onConfirm={() => { setEditing(false); onPick("confirm", draft); }}
          onCancel={() => { setDraft(data); setEditing(false); }}
        />
      )}
    </>
  );
}


// ── Edit modal (popup) ───────────────────────────────────────────────

function EditModal({
  draft, onChange, onConfirm, onCancel,
}: {
  draft: DesignIntentData;
  onChange: (next: DesignIntentData) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(15, 23, 42, 0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 24,
      }}
    >
      <div style={{
        width: "min(640px, 100%)",
        maxHeight: "90vh", overflowY: "auto",
        background: "#fff", borderRadius: 8,
        boxShadow: "0 20px 50px rgba(0,0,0,0.25)",
        padding: "20px 24px",
      }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 16,
        }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#1a202c" }}>
            🛠 編輯規格 — 改完按「確認修改」
          </div>
          <button
            onClick={onCancel}
            style={{
              background: "transparent", border: "none", cursor: "pointer",
              fontSize: 18, color: "#a0aec0", padding: 4,
            }}
            title="關閉"
          >✕</button>
        </div>
        <EditForm draft={draft} onChange={onChange} />
        <div style={{
          display: "flex", gap: 8, marginTop: 16,
          paddingTop: 14, borderTop: "1px solid #e2e8f0",
          justifyContent: "flex-end",
        }}>
          <button onClick={onCancel} style={btnStyle("secondary")}>↩ 取消修改</button>
          <button onClick={onConfirm} style={btnStyle("primary")}>✅ 確認修改並開始建</button>
        </div>
      </div>
    </div>
  );
}


// ── Read-mode view (default) ──────────────────────────────────────────

function ReadView({
  data, present,
}: {
  data: DesignIntentData;
  present: typeof PRESENT_OPTIONS[number];
}) {
  return (
    <>
      {/* Inputs */}
      {data.inputs.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={sectionTitleStyle}>📥 輸入</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {data.inputs.map((inp, i) => (
              <div key={i} style={{ fontSize: 12, color: "#2d3748" }}>
                <span style={{ fontFamily: "monospace", fontWeight: 600 }}>${inp.name}</span>
                <span style={{ color: "#718096", marginLeft: 6 }}>
                  ({SOURCE_LABEL[inp.source] ?? inp.source})
                </span>
                {inp.rationale && (
                  <span style={{ color: "#4a5568", marginLeft: 6 }}>— {inp.rationale}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Logic */}
      {data.logic && (
        <div style={{ marginBottom: 10 }}>
          <div style={sectionTitleStyle}>📊 邏輯</div>
          <div style={{ fontSize: 12, color: "#2d3748", lineHeight: 1.5 }}>
            {data.logic}
          </div>
        </div>
      )}

      {/* Presentation */}
      <div style={{ marginBottom: 10 }}>
        <div style={sectionTitleStyle}>📤 呈現</div>
        <div style={{ fontSize: 12, color: "#2d3748" }}>
          {present.icon} {present.label} <span style={{ color: "#a0aec0" }}>— {present.hint}</span>
        </div>
      </div>

      {/* Alternatives */}
      {(data.alternatives?.length ?? 0) > 0 && (
        <div style={{
          marginBottom: 10, padding: "8px 10px", borderRadius: 6,
          background: "#edf2f7", fontSize: 12, color: "#4a5568",
        }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>💭 你也可能想看的另一種解讀</div>
          {(data.alternatives ?? []).map((a, i) => (
            <div key={i} style={{ marginLeft: 8 }}>• {a.summary}</div>
          ))}
        </div>
      )}
    </>
  );
}


// ── Clarification radio groups (Plan-Mode multi-choice) ──────────────

function ClarificationGroups({
  clarifications, selections, onChange, disabled,
}: {
  clarifications: ClarificationDimension[];
  selections: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  disabled: boolean;
}) {
  return (
    <div style={{
      marginTop: 4, marginBottom: 10,
      padding: "10px 12px", borderRadius: 6,
      background: "#fffbea", border: "1px solid #fde68a",
    }}>
      <div style={{
        fontWeight: 600, fontSize: 12, color: "#92400e", marginBottom: 8,
      }}>
        ❓ 我有些地方不確定，請幫忙對焦：
      </div>
      {clarifications.map((c) => (
        <div key={c.dimension} style={{ marginBottom: 10 }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: "#1a202c", marginBottom: 4,
          }}>
            {c.question}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, paddingLeft: 4 }}>
            {c.options.map((opt) => {
              const checked = selections[c.dimension] === opt.value;
              return (
                <label key={opt.value} style={{
                  display: "flex", alignItems: "flex-start", gap: 6,
                  fontSize: 12, color: "#2d3748", cursor: disabled ? "default" : "pointer",
                }}>
                  <input
                    type="radio"
                    name={`dim-${c.dimension}`}
                    value={opt.value}
                    checked={checked}
                    disabled={disabled}
                    onChange={() => onChange({ ...selections, [c.dimension]: opt.value })}
                    style={{ marginTop: 3, cursor: disabled ? "default" : "pointer" }}
                  />
                  <div>
                    <div style={{ fontWeight: checked ? 600 : 400 }}>{opt.label}</div>
                    {opt.hint && (
                      <div style={{ fontSize: 11, color: "#718096" }}>{opt.hint}</div>
                    )}
                  </div>
                </label>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}


// ── Edit-mode form ────────────────────────────────────────────────────

function EditForm({
  draft, onChange,
}: {
  draft: DesignIntentData;
  onChange: (next: DesignIntentData) => void;
}) {
  const [advanced, setAdvanced] = useState(false);
  const [jsonText, setJsonText] = useState<string>(() => JSON.stringify(draft, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);

  // 表單 → state
  const updateInput = (i: number, patch: Partial<DesignIntentInput>) => {
    const next = [...draft.inputs];
    next[i] = { ...next[i], ...patch };
    onChange({ ...draft, inputs: next });
  };
  const addInput = () => {
    onChange({ ...draft, inputs: [...draft.inputs, {
      name: "tool_id", source: "user_input", rationale: "",
    }]});
  };
  const removeInput = (i: number) => {
    const next = draft.inputs.filter((_, idx) => idx !== i);
    onChange({ ...draft, inputs: next });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Inputs editor */}
      <div>
        <div style={sectionTitleStyle}>📥 輸入（每個 input 一行）</div>
        {draft.inputs.length === 0 && (
          <div style={{ fontSize: 12, color: "#a0aec0", marginBottom: 4 }}>
            尚未宣告任何 input — 按下方「+ 加 input」新增
          </div>
        )}
        {draft.inputs.map((inp, i) => (
          <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center" }}>
            <select
              value={inp.name}
              onChange={(e) => updateInput(i, { name: e.target.value })}
              style={inputStyle({ width: 220, fontFamily: "monospace" })}
            >
              {CANONICAL_INPUT_NAMES.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
              {/* Allow legacy / non-canonical names to remain selectable so we
                  don't silently drop them, but prefix with ⚠ to discourage. */}
              {!CANONICAL_INPUT_NAMES.some((c) => c.value === inp.name) && (
                <option value={inp.name}>{`⚠ ${inp.name} (non-canonical)`}</option>
              )}
            </select>
            <input
              type="text"
              value={inp.rationale ?? ""}
              onChange={(e) => updateInput(i, { rationale: e.target.value })}
              placeholder="說明（例：user 指定 EQP-07）"
              style={inputStyle({ flex: 1 })}
            />
            <button
              onClick={() => removeInput(i)}
              style={btnStyle("ghost", { padding: "4px 8px", fontSize: 11 })}
              title="移除"
            >−</button>
          </div>
        ))}
        <button onClick={addInput} style={btnStyle("ghost", { fontSize: 11, padding: "4px 8px" })}>
          + 加 input
        </button>
      </div>

      {/* Logic editor */}
      <div>
        <div style={sectionTitleStyle}>📊 邏輯（自然語言描述）</div>
        <textarea
          value={draft.logic}
          onChange={(e) => onChange({ ...draft, logic: e.target.value })}
          rows={3}
          style={inputStyle({ width: "100%", resize: "vertical", fontFamily: "inherit" })}
          placeholder="例：calculate OOC count per station in last day and check if 3+ OOCs occurred in last 5 processes"
        />
      </div>

      {/* Presentation radio */}
      <div>
        <div style={sectionTitleStyle}>📤 呈現</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
          {PRESENT_OPTIONS.map((opt) => {
            const checked = draft.presentation === opt.kind;
            return (
              <label key={opt.kind} style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "5px 8px",
                border: checked ? "1px solid #2b6cb0" : "1px solid #cbd5e0",
                background: checked ? "#ebf4ff" : "#fff",
                borderRadius: 4,
                fontSize: 12,
                cursor: "pointer",
              }}>
                <input
                  type="radio"
                  name={`presentation-${draft.card_id}`}
                  checked={checked}
                  onChange={() => onChange({ ...draft, presentation: opt.kind })}
                />
                <span>{opt.icon}</span>
                <span style={{ fontWeight: 600 }}>{opt.label}</span>
                <span style={{ color: "#a0aec0", fontSize: 11 }}>{opt.hint}</span>
              </label>
            );
          })}
        </div>
      </div>

      {/* Advanced JSON fallback for power users */}
      <details
        open={advanced}
        onToggle={(e) => setAdvanced((e.target as HTMLDetailsElement).open)}
      >
        <summary style={{
          fontSize: 11, color: "#718096", cursor: "pointer",
          marginBottom: 4, userSelect: "none",
        }}>
          進階：直接編輯 JSON
        </summary>
        <textarea
          value={jsonText}
          onChange={(e) => {
            setJsonText(e.target.value);
            try {
              const parsed = JSON.parse(e.target.value);
              setJsonError(null);
              onChange({ ...draft, ...parsed });
            } catch (err) {
              setJsonError(err instanceof Error ? err.message : "JSON parse error");
            }
          }}
          rows={10}
          style={inputStyle({
            width: "100%", fontFamily: "ui-monospace, Menlo, monospace",
            fontSize: 11, resize: "vertical",
          })}
        />
        {jsonError && (
          <div style={{ color: "#c53030", fontSize: 11 }}>JSON 錯誤：{jsonError}</div>
        )}
      </details>
    </div>
  );
}


// ── Style helpers ─────────────────────────────────────────────────────

const sectionTitleStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: "#4a5568",
  marginBottom: 4, letterSpacing: "0.3px",
};

function btnStyle(
  variant: "primary" | "secondary" | "secondary-disabled" | "ghost",
  override: React.CSSProperties = {},
): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: "8px 12px",
    border: "1px solid",
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
  };
  const variants: Record<string, React.CSSProperties> = {
    primary:    { ...base, borderColor: "#2b6cb0", background: "#2b6cb0", color: "#fff" },
    secondary:  { ...base, borderColor: "#cbd5e0", background: "#fff",   color: "#2d3748", fontWeight: 500 },
    "secondary-disabled": { ...base, borderColor: "#e2e8f0", background: "#edf2f7", color: "#a0aec0", cursor: "default" },
    ghost:      { ...base, borderColor: "transparent", background: "transparent", color: "#4a5568", fontWeight: 500 },
  };
  return { ...(variants[variant] || variants.secondary), ...override };
}

function inputStyle(extra: React.CSSProperties = {}): React.CSSProperties {
  return {
    border: "1px solid #cbd5e0",
    borderRadius: 4,
    padding: "4px 6px",
    fontSize: 12,
    color: "#2d3748",
    background: "#fff",
    ...extra,
  };
}
