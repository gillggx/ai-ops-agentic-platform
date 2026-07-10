"use client";

/**
 * PipelineInputsPanel — modal for declaring pipeline-level inputs.
 *
 * Inputs are referenced via `"$name"` string values in node params. At Run
 * time the executor replaces the reference with the value provided (or the
 * declared default / example).
 */

import { useState } from "react";
import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import type { PipelineInput, PipelineInputType } from "@/lib/pipeline-builder/types";

interface Props {
  open: boolean;
  onClose: () => void;
}

const TYPE_OPTIONS: PipelineInputType[] = ["string", "integer", "number", "boolean"];

export default function PipelineInputsPanel({ open, onClose }: Props) {
  const { state, actions } = useBuilder();
  const inputs = state.pipeline.inputs ?? [];
  const [newInput, setNewInput] = useState<PipelineInput>({
    name: "",
    type: "string",
    required: false,
  });
  const [nameError, setNameError] = useState<string | null>(null);

  if (!open) return null;

  const addInput = () => {
    const trimmed = newInput.name.trim();
    if (!trimmed) {
      setNameError("名稱不可為空");
      return;
    }
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(trimmed)) {
      setNameError("名稱只能字母/底線開頭，含字母/數字/底線");
      return;
    }
    if (inputs.some((i) => i.name === trimmed)) {
      setNameError(`已有名為 "${trimmed}" 的 input`);
      return;
    }
    actions.declareInput({ ...newInput, name: trimmed });
    setNewInput({ name: "", type: "string", required: false });
    setNameError(null);
  };

  return (
    <div
      data-testid="pipeline-inputs-panel"
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.35)",
        zIndex: 220,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(680px, 92vw)",
          maxHeight: "calc(100vh - 80px)",
          background: "#fff",
          borderRadius: 8,
          boxShadow: "0 16px 48px rgba(15,23,42,0.18)",
          display: "flex",
          flexDirection: "column",
          fontFamily: "Inter, system-ui, -apple-system, 'Noto Sans TC', sans-serif",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "12px 16px",
            borderBottom: "1px solid #E2E8F0",
            background: "var(--pn, #F8FAFC)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <span style={{ fontSize: 16 }}>🔣</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#0F172A" }}>Pipeline Inputs</div>
            <div style={{ fontSize: 10, color: "#64748B" }}>
              宣告變數後，node param 可填 <code style={{ background: "#F1F5F9", padding: "0 3px", borderRadius: 2 }}>$name</code> 引用
            </div>
          </div>
          <button
            data-testid="pipeline-inputs-close"
            onClick={onClose}
            style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "#94A3B8" }}
          >×</button>
        </div>

        <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
          {/* Existing inputs table */}
          {inputs.length === 0 && (
            <div
              style={{
                padding: "16px",
                color: "#94A3B8",
                fontSize: 11,
                textAlign: "center",
                background: "var(--pn, #F8FAFC)",
                borderRadius: 4,
                marginBottom: 12,
              }}
            >
              尚未宣告 input。下方表單新增第一個，或從 Inspector 按「→ 變數」自動抽出。
            </div>
          )}
          {inputs.length > 0 && (
            <table
              style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginBottom: 12 }}
            >
              <thead>
                <tr style={{ background: "var(--pn, #F8FAFC)" }}>
                  {["name", "type", "required", "default", "example", "description", ""].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: "left",
                        padding: "6px 8px",
                        borderBottom: "1px solid #E2E8F0",
                        fontSize: 10,
                        fontWeight: 600,
                        color: "#475569",
                        letterSpacing: "0.04em",
                        textTransform: "uppercase",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {inputs.map((inp) => (
                  <InputRow key={inp.name} input={inp} />
                ))}
              </tbody>
            </table>
          )}

          {/* Add-new form */}
          <div
            style={{
              border: "1px dashed #CBD5E1",
              borderRadius: 6,
              padding: 12,
              background: "#FAFBFC",
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 600, color: "#475569", marginBottom: 8, letterSpacing: "0.04em", textTransform: "uppercase" }}>
              + 新增 Input
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 120px 80px 1fr", gap: 8, alignItems: "start" }}>
              <label style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ color: "#64748B" }}>Name *</span>
                <input
                  type="text"
                  value={newInput.name}
                  onChange={(e) => { setNewInput({ ...newInput, name: e.target.value }); setNameError(null); }}
                  placeholder="tool_id"
                  style={fieldStyle}
                />
                {nameError && <span style={{ color: "#DC2626", fontSize: 10 }}>{nameError}</span>}
              </label>
              <label style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ color: "#64748B" }}>Type</span>
                <select
                  value={newInput.type}
                  onChange={(e) => setNewInput({ ...newInput, type: e.target.value as PipelineInputType })}
                  style={fieldStyle}
                >
                  {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <label style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 2, alignItems: "flex-start" }}>
                <span style={{ color: "#64748B" }}>Required</span>
                <input
                  type="checkbox"
                  checked={!!newInput.required}
                  onChange={(e) => setNewInput({ ...newInput, required: e.target.checked })}
                  style={{ marginTop: 6 }}
                />
              </label>
              <label style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ color: "#64748B" }}>Example (preview 用)</span>
                <input
                  type="text"
                  value={(newInput.example ?? "") as string}
                  onChange={(e) => setNewInput({ ...newInput, example: e.target.value })}
                  placeholder="EQP-01"
                  style={fieldStyle}
                />
              </label>
            </div>
            <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
              <input
                type="text"
                value={newInput.description ?? ""}
                onChange={(e) => setNewInput({ ...newInput, description: e.target.value })}
                placeholder="description (選填)"
                style={{ ...fieldStyle, flex: 1 }}
              />
              <button
                data-testid="pipeline-inputs-add"
                onClick={addInput}
                style={{
                  padding: "6px 16px",
                  background: "var(--p, #4F46E5)",
                  color: "#fff",
                  border: "none",
                  borderRadius: 4,
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                新增
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function InputRow({ input }: { input: PipelineInput }) {
  const { actions } = useBuilder();
  return (
    <tr data-testid={`pipeline-input-row-${input.name}`}>
      <td style={cellStyle}>
        <code style={{ fontFamily: "ui-monospace, monospace", color: "#3730A3" }}>${input.name}</code>
      </td>
      <td style={cellStyle}>
        <select
          value={input.type}
          onChange={(e) => actions.updateInput(input.name, { type: e.target.value as PipelineInputType })}
          style={{ ...fieldStyle, width: 90 }}
        >
          {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </td>
      <td style={cellStyle}>
        <input
          type="checkbox"
          checked={!!input.required}
          onChange={(e) => actions.updateInput(input.name, { required: e.target.checked })}
        />
      </td>
      <td style={cellStyle}>
        <input
          type="text"
          value={(input.default ?? "") as string}
          onChange={(e) => actions.updateInput(input.name, { default: e.target.value || null })}
          placeholder="—"
          style={{ ...fieldStyle, width: 90 }}
        />
      </td>
      <td style={cellStyle}>
        <input
          type="text"
          value={(input.example ?? "") as string}
          onChange={(e) => actions.updateInput(input.name, { example: e.target.value || null })}
          placeholder="—"
          style={{ ...fieldStyle, width: 90 }}
        />
      </td>
      <td style={cellStyle}>
        <input
          type="text"
          value={input.description ?? ""}
          onChange={(e) => actions.updateInput(input.name, { description: e.target.value })}
          placeholder="—"
          style={{ ...fieldStyle, width: "100%" }}
        />
      </td>
      <td style={cellStyle}>
        <button
          onClick={() => actions.removeInput(input.name)}
          title="刪除"
          style={{
            background: "none",
            border: "none",
            color: "#DC2626",
            cursor: "pointer",
            fontSize: 14,
            padding: 2,
          }}
        >
          ✕
        </button>
      </td>
    </tr>
  );
}

const fieldStyle: React.CSSProperties = {
  padding: "4px 8px",
  fontSize: 12,
  border: "1px solid #CBD5E1",
  borderRadius: 3,
  outline: "none",
  fontFamily: "inherit",
  background: "#fff",
};

const cellStyle: React.CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid #F1F5F9",
  verticalAlign: "middle",
};
