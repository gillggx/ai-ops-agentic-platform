"use client";

/**
 * PipelineRunDialog — prompts for pipeline.inputs values when required fields
 * don't yet have a value. Called when user clicks Run and the pipeline has
 * one-or-more required inputs without defaults/examples.
 */

import { useMemo, useState } from "react";
import type { PipelineInput } from "@/lib/pipeline-builder/types";

interface Props {
  open: boolean;
  inputs: PipelineInput[];
  onCancel: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
}

// Canonical example values used when the input declaration has no
// default/example set. Mirrors Java buildEventPayload._defaultForAttr +
// SkillEmbedBanner._CANONICAL_EXAMPLES so dry-run / past-event replay /
// manual payload all use the same shape. User reported the dialog asked
// them to fill 7 OOC fields by hand even after the build flow correctly
// seeded declared_inputs from event_types.attributes — root cause was
// that the seed path didn't carry `example`, and existing already-saved
// pipelines (like skill 54's pipeline 85) wouldn't pick up new examples
// without a rebuild. This fallback closes both gaps.
const CANONICAL: Record<string, string> = {
  tool_id: "EQP-01",
  equipment_id: "EQP-01",
  lot_id: "LOT-0001",
  step: "STEP_001",
  step_id: "STEP_001",
  chamber_id: "CH-1",
  recipe_id: "RECIPE-A",
  parameter: "CD_Mean",
  ooc_parameter: "CD_Mean",
  spc_chart: "spc_xbar",
  SPC_CHART: "spc_xbar",
  fault_code: "FDC_RGA_H2O_HIGH",
  severity: "warning",
  event_time: "2026-05-01T00:00:00Z",
  timestamp: "2026-05-01T00:00:00Z",
  process_timestamp: "2026-05-01T00:00:00Z",
  ooc_details: "{}",
  time_range: "24h",
  limit: "100",
};

export default function PipelineRunDialog({ open, inputs, onCancel, onSubmit }: Props) {
  const initial = useMemo(() => {
    const v: Record<string, string> = {};
    for (const inp of inputs) {
      // Priority: explicit default → explicit example → canonical for the
      // attribute name → empty (user types).
      const seed = inp.default ?? inp.example ?? CANONICAL[inp.name] ?? "";
      v[inp.name] = seed === null ? "" : String(seed);
    }
    return v;
  }, [inputs]);
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const submit = () => {
    // Validate required
    for (const inp of inputs) {
      if (inp.required && !values[inp.name]) {
        setError(`"${inp.name}" 為必填`);
        return;
      }
    }
    // Let backend do type coercion (accepts strings).
    onSubmit(values);
    setError(null);
  };

  return (
    <div
      data-testid="pipeline-run-dialog"
      onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.35)",
        zIndex: 230,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(480px, 92vw)",
          background: "#fff",
          borderRadius: 8,
          boxShadow: "0 16px 48px rgba(15,23,42,0.18)",
          fontFamily: "Inter, system-ui, -apple-system, 'Noto Sans TC', sans-serif",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #E2E8F0", background: "#F8FAFC", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16 }}>▶</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#0F172A" }}>Run Pipeline</div>
            <div style={{ fontSize: 10, color: "#64748B" }}>填入 pipeline inputs 的值</div>
          </div>
        </div>

        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
          {inputs.map((inp) => (
            <label key={inp.name} style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ color: "#475569" }}>
                <code style={{ color: "#3730A3", fontFamily: "ui-monospace, monospace" }}>${inp.name}</code>
                {inp.required && <span style={{ color: "#B91C1C" }}> *</span>}
                <span style={{ color: "#94A3B8", marginLeft: 8 }}>({inp.type})</span>
                {inp.description && <span style={{ marginLeft: 8, color: "#64748B" }}>— {inp.description}</span>}
              </span>
              <input
                data-testid={`run-dialog-input-${inp.name}`}
                type={inp.type === "integer" || inp.type === "number" ? "number" : "text"}
                value={values[inp.name] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [inp.name]: e.target.value }))}
                placeholder={inp.example != null ? String(inp.example) : ""}
                style={{
                  padding: "6px 10px",
                  fontSize: 12,
                  border: "1px solid #CBD5E1",
                  borderRadius: 3,
                  outline: "none",
                }}
              />
            </label>
          ))}
          {error && <div style={{ color: "#DC2626", fontSize: 11 }}>{error}</div>}
        </div>

        <div style={{ padding: "10px 16px", borderTop: "1px solid #E2E8F0", display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            onClick={onCancel}
            style={{
              padding: "6px 14px",
              fontSize: 12,
              background: "#fff",
              border: "1px solid #CBD5E1",
              borderRadius: 3,
              cursor: "pointer",
              color: "#475569",
            }}
          >
            取消
          </button>
          <button
            data-testid="run-dialog-submit"
            onClick={submit}
            style={{
              padding: "6px 16px",
              fontSize: 12,
              background: "#4F46E5",
              color: "#fff",
              border: "none",
              borderRadius: 3,
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            Run
          </button>
        </div>
      </div>
    </div>
  );
}
