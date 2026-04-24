"use client";

/**
 * WizardInputsStep — Step 3 of /admin/pipeline-builder/new wizard.
 *
 * Shows kind-aware suggestions as checkable cards + free-form custom input
 * add UI. At least 1 input must be declared before the "進 Builder" button
 * enables — this is a soft-block UX: user keeps full control but the wizard
 * refuses to advance with zero declarations (enforces the design intent that
 * every pipeline should have a parameter contract).
 */

import { useMemo, useState } from "react";
import type { PipelineInput, PipelineInputType } from "@/lib/pipeline-builder/types";
import {
  getInputSuggestions,
  kindInputRationale,
  kindLabel,
  suggestionToInput,
  type WizardKind,
  type WizardTriggerMode,
} from "./wizard-input-suggestions";

interface Props {
  kind: WizardKind;
  triggerMode: WizardTriggerMode;
  value: PipelineInput[];
  onChange: (next: PipelineInput[]) => void;
}

export default function WizardInputsStep({ kind, triggerMode, value, onChange }: Props) {
  const suggestions = useMemo(() => getInputSuggestions(kind, triggerMode), [kind, triggerMode]);
  const rationale = useMemo(() => kindInputRationale(kind, triggerMode), [kind, triggerMode]);

  // Custom-add row state
  const [customName, setCustomName] = useState("");
  const [customType, setCustomType] = useState<PipelineInputType>("string");
  const [customRequired, setCustomRequired] = useState(false);
  const [customDesc, setCustomDesc] = useState("");

  const pickedNames = useMemo(() => new Set(value.map((i) => i.name)), [value]);

  const togglePick = (name: string) => {
    const suggestion = suggestions.find((s) => s.name === name);
    if (!suggestion) return;
    if (pickedNames.has(name)) {
      onChange(value.filter((i) => i.name !== name));
    } else {
      onChange([...value, suggestionToInput(suggestion)]);
    }
  };

  const removeInput = (name: string) => {
    onChange(value.filter((i) => i.name !== name));
  };

  const addCustom = () => {
    const n = customName.trim();
    if (!n) return;
    if (pickedNames.has(n)) return;  // no duplicates
    const next: PipelineInput = {
      name: n,
      type: customType,
      required: customRequired,
      description: customDesc.trim() || undefined,
    };
    onChange([...value, next]);
    setCustomName("");
    setCustomType("string");
    setCustomRequired(false);
    setCustomDesc("");
  };

  return (
    <div>
      {/* Rationale banner — tells user WHY this step exists for this kind */}
      <div style={rationaleStyle}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#0369a1", marginBottom: 4 }}>
          💡 為什麼 {kindLabel(kind)} 需要定 inputs？
        </div>
        <div style={{ fontSize: 12, color: "#0369a1", lineHeight: 1.6 }}>{rationale}</div>
      </div>

      {/* Suggestions as cards */}
      <div style={{ fontSize: 12, fontWeight: 600, color: "#475569", marginBottom: 6, marginTop: 14 }}>
        常用 inputs（點卡片勾選 / 取消）
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {suggestions.map((s) => {
          const picked = pickedNames.has(s.name);
          return (
            <button
              key={s.name}
              type="button"
              onClick={() => togglePick(s.name)}
              style={cardStyle(picked, !!s.critical)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
                <span style={{ fontSize: 13 }}>{picked ? "☑" : "☐"}</span>
                <code style={{ fontSize: 12, fontWeight: 700, color: picked ? "#4338ca" : "#1a202c" }}>
                  {s.name}
                </code>
                <span style={typeChipStyle}>{s.type}</span>
                {s.required && <span style={requiredChipStyle}>required</span>}
                {s.critical && <span style={criticalChipStyle}>關鍵</span>}
              </div>
              <div style={{ fontSize: 11, color: "#64748B", lineHeight: 1.5 }}>{s.description}</div>
            </button>
          );
        })}
      </div>

      {/* Custom add */}
      <div style={{ fontSize: 12, fontWeight: 600, color: "#475569", marginTop: 18, marginBottom: 6 }}>
        自訂 input
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr auto 2fr auto", gap: 8, alignItems: "center" }}>
        <input
          type="text"
          placeholder="name（如 recipe_id）"
          value={customName}
          onChange={(e) => setCustomName(e.target.value)}
          style={inputSmStyle}
        />
        <select
          value={customType}
          onChange={(e) => setCustomType(e.target.value as PipelineInputType)}
          style={inputSmStyle}
        >
          {(["string", "integer", "number", "boolean"] as const).map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <label style={{ fontSize: 12, color: "#475569", display: "flex", alignItems: "center", gap: 4 }}>
          <input
            type="checkbox"
            checked={customRequired}
            onChange={(e) => setCustomRequired(e.target.checked)}
          />
          required
        </label>
        <input
          type="text"
          placeholder="description（選填）"
          value={customDesc}
          onChange={(e) => setCustomDesc(e.target.value)}
          style={inputSmStyle}
        />
        <button
          type="button"
          onClick={addCustom}
          disabled={!customName.trim() || pickedNames.has(customName.trim())}
          style={{
            padding: "6px 12px",
            fontSize: 12,
            fontWeight: 600,
            borderRadius: 6,
            border: "1px solid #6366f1",
            background: customName.trim() && !pickedNames.has(customName.trim()) ? "#6366f1" : "#e2e8f0",
            color: customName.trim() && !pickedNames.has(customName.trim()) ? "#fff" : "#94a3b8",
            cursor: customName.trim() && !pickedNames.has(customName.trim()) ? "pointer" : "not-allowed",
          }}
        >
          + 加入
        </button>
      </div>

      {/* Summary of selected */}
      <div style={{ marginTop: 16 }}>
        {value.length === 0 ? (
          <div style={emptyWarningStyle}>
            ⚠ 還沒宣告任何 input。請至少勾選或自訂一個，才能進 Builder。
          </div>
        ) : (
          <div style={summaryOkStyle}>
            ✓ 已宣告 <strong>{value.length}</strong> 個 input：
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
              {value.map((i) => (
                <span key={i.name} style={selectedChipStyle}>
                  <code style={{ fontSize: 11, fontWeight: 700 }}>{i.name}</code>
                  <span style={{ fontSize: 10, color: "#64748b" }}>{i.type}</span>
                  {i.required && <span style={{ fontSize: 10, color: "#dc2626" }}>*</span>}
                  <button
                    onClick={() => removeInput(i.name)}
                    style={{
                      border: "none", background: "none", cursor: "pointer",
                      color: "#94a3b8", fontSize: 12, padding: 0, marginLeft: 2,
                    }}
                    title="移除"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Wizard-level validator: at least 1 input required. */
export function validateInputs(value: PipelineInput[]): string | null {
  if (value.length === 0) return "請至少勾選或自訂一個 input";
  return null;
}

// ── styles ──────────────────────────────────────────────────────

const rationaleStyle: React.CSSProperties = {
  background: "#f0f9ff",
  border: "1px solid #bae6fd",
  borderRadius: 6,
  padding: "10px 12px",
};

function cardStyle(picked: boolean, critical: boolean): React.CSSProperties {
  return {
    padding: 10,
    borderRadius: 6,
    cursor: "pointer",
    textAlign: "left",
    border: `1.5px solid ${picked ? "#6366f1" : critical ? "#f59e0b" : "#e2e8f0"}`,
    background: picked ? "#eef2ff" : "#fff",
    transition: "border-color 120ms",
  };
}

const typeChipStyle: React.CSSProperties = {
  padding: "1px 6px",
  borderRadius: 3,
  background: "#f1f5f9",
  color: "#475569",
  fontSize: 10,
  fontWeight: 600,
};

const requiredChipStyle: React.CSSProperties = {
  padding: "1px 6px",
  borderRadius: 3,
  background: "#fef2f2",
  color: "#dc2626",
  fontSize: 10,
  fontWeight: 600,
};

const criticalChipStyle: React.CSSProperties = {
  padding: "1px 6px",
  borderRadius: 3,
  background: "#fffbeb",
  color: "#b45309",
  fontSize: 10,
  fontWeight: 700,
};

const inputSmStyle: React.CSSProperties = {
  padding: "6px 10px",
  border: "1px solid #cbd5e0",
  borderRadius: 6,
  fontSize: 12,
  color: "#2d3748",
  background: "#fff",
  boxSizing: "border-box",
  width: "100%",
};

const emptyWarningStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: 6,
  background: "#fef3c7",
  color: "#92400e",
  fontSize: 12,
  fontWeight: 600,
};

const summaryOkStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: 6,
  background: "#ecfdf5",
  color: "#065f46",
  fontSize: 12,
};

const selectedChipStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  padding: "3px 8px",
  borderRadius: 4,
  background: "#fff",
  border: "1px solid #a7f3d0",
};
