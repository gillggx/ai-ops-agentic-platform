"use client";

/**
 * AutoPatrolScopePicker — radio + dependent inputs for an auto-patrol's
 * non-event target_scope. Used by both the kind+trigger wizard
 * (admin/pipeline-builder/new) and the inline AutoPatrolSetupModal.
 *
 * SPEC_patrol_pipeline_wiring §1.2 — only relevant when trigger.mode is
 * "schedule" or "once". Event-mode patrols don't need a picker; their scope
 * is implicitly {type: "event_driven"} and resolved from the alarm payload.
 */

import { useEffect, useState } from "react";

export type TargetScope =
  | { type: "event_driven" }
  | { type: "all_equipment"; fanout_cap: number }
  | { type: "specific_equipment"; equipment_ids: string[]; fanout_cap: number }
  | { type: "by_step"; step: string; fanout_cap: number };

/** A scope this picker can represent. event_driven is intentionally excluded —
 *  parents that need event_driven simply don't render the picker. */
export type PickedScope = Exclude<TargetScope, { type: "event_driven" }>;

interface Props {
  value: PickedScope;
  onChange: (next: PickedScope) => void;
}

export default function AutoPatrolScopePicker({ value, onChange }: Props) {
  // Transient string state for the CSV / step inputs — lets the user type
  // ", " or partial words without the parser collapsing them mid-edit.
  const [csvDraft, setCsvDraft] = useState(
    value.type === "specific_equipment" ? value.equipment_ids.join(", ") : "",
  );
  const [stepDraft, setStepDraft] = useState(
    value.type === "by_step" ? value.step : "",
  );

  // Re-sync drafts when scope type flips (e.g. parent reset).
  useEffect(() => {
    if (value.type === "specific_equipment") {
      setCsvDraft(value.equipment_ids.join(", "));
    } else if (value.type === "by_step") {
      setStepDraft(value.step);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.type]);

  const switchType = (next: PickedScope["type"]) => {
    const cap = value.fanout_cap;
    if (next === "all_equipment") {
      onChange({ type: "all_equipment", fanout_cap: cap });
    } else if (next === "specific_equipment") {
      const ids = csvDraft.split(",").map((s) => s.trim()).filter(Boolean);
      onChange({ type: "specific_equipment", equipment_ids: ids, fanout_cap: cap });
    } else {
      onChange({ type: "by_step", step: stepDraft, fanout_cap: cap });
    }
  };

  const updateCsv = (raw: string) => {
    setCsvDraft(raw);
    if (value.type !== "specific_equipment") return;
    const ids = raw.split(",").map((s) => s.trim()).filter(Boolean);
    onChange({ ...value, equipment_ids: ids });
  };

  const updateStep = (raw: string) => {
    setStepDraft(raw);
    if (value.type !== "by_step") return;
    onChange({ ...value, step: raw.trim() });
  };

  const updateCap = (cap: number) => {
    onChange({ ...value, fanout_cap: cap });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }}>
      {OPTIONS(value.fanout_cap).map((opt) => (
        <label
          key={opt.v}
          style={{ display: "flex", alignItems: "flex-start", gap: 6, cursor: "pointer" }}
        >
          <input
            type="radio"
            checked={value.type === opt.v}
            onChange={() => switchType(opt.v)}
          />
          <span>
            <span style={{ fontWeight: 600 }}>{opt.label}</span>
            <span style={{ color: "#718096", marginLeft: 6 }}>— {opt.desc}</span>
          </span>
        </label>
      ))}
      {value.type === "specific_equipment" && (
        <input
          value={csvDraft}
          onChange={(e) => updateCsv(e.target.value)}
          placeholder="EQP-01, EQP-02, EQP-03"
          style={inputStyle}
        />
      )}
      {value.type === "by_step" && (
        <input
          value={stepDraft}
          onChange={(e) => updateStep(e.target.value)}
          placeholder="STEP_001"
          style={inputStyle}
        />
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 11, color: "#718096" }}>Fanout cap (上限)：</span>
        <input
          type="number"
          min={1}
          max={500}
          style={{ ...inputStyle, width: 80, padding: "4px 8px" }}
          value={value.fanout_cap}
          onChange={(e) => updateCap(parseInt(e.target.value || "20", 10))}
        />
        <span style={{ fontSize: 10, color: "#a0aec0" }}>
          (超過 cap 會截斷 + 寫 warning alarm)
        </span>
      </div>
    </div>
  );
}

const OPTIONS = (cap: number): {
  v: PickedScope["type"];
  label: string;
  desc: string;
}[] => [
  {
    v: "all_equipment",
    label: "所有機台",
    desc: `cron 跑時抓 simulator 全部機台 list（最多 ${cap} 台）`,
  },
  {
    v: "specific_equipment",
    label: "指定機台",
    desc: "在下方填 EQP-01,EQP-02 (CSV)",
  },
  {
    v: "by_step",
    label: "指定站點",
    desc: "選 step → 抓該 step 所有機台（cap 適用）",
  },
];

const inputStyle: React.CSSProperties = {
  padding: "8px 10px",
  border: "1px solid #cbd5e0",
  borderRadius: 4,
  background: "#fff",
  fontSize: 12,
};

/** Validation helper — reused by wizard's validateTrigger. */
export function validatePickedScope(s: PickedScope): string | null {
  if (s.type === "specific_equipment" && s.equipment_ids.length === 0) {
    return "「指定機台」需至少填 1 台 (CSV)";
  }
  if (s.type === "by_step" && !s.step.trim()) {
    return "「指定站點」需填 step";
  }
  if (s.fanout_cap < 1 || s.fanout_cap > 500) {
    return "Fanout cap 需在 1-500 之間";
  }
  return null;
}
