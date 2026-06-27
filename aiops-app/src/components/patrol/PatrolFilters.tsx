"use client";

export interface PatrolFilterState {
  range: "1h" | "6h" | "24h";
  eventType: string | null;
  skillStage: "patrol" | "diagnose" | null;
  outcome: "any" | "alarm_emitted" | "step_passed" | "no_op" | "error";
}

interface Props {
  value: PatrolFilterState;
  onChange: (v: PatrolFilterState) => void;
}

/**
 * Inline filter row. Five controls, all server-side except for being held
 * in URL-less local state. We keep the surface narrow on purpose — Alarm
 * Center's filter set is much richer, but here the funnel + outcome chip
 * already answers most "what's going on" questions; the filters just
 * narrow scope.
 */
export function PatrolFilters({ value, onChange }: Props) {
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <FilterSelect
        label="範圍"
        value={value.range}
        onChange={(v) => onChange({ ...value, range: v as PatrolFilterState["range"] })}
        options={[
          { value: "1h",  label: "最近 1 小時" },
          { value: "6h",  label: "最近 6 小時" },
          { value: "24h", label: "最近 24 小時" },
        ]}
      />
      <FilterSelect
        label="Event Type"
        value={value.eventType ?? "__any__"}
        onChange={(v) => onChange({ ...value, eventType: v === "__any__" ? null : v })}
        options={[
          { value: "__any__", label: "全部" },
          { value: "OOC", label: "OOC" },
          { value: "ALARM", label: "ALARM" },
        ]}
      />
      <FilterSelect
        label="Stage"
        value={value.skillStage ?? "__any__"}
        onChange={(v) => onChange({
          ...value,
          skillStage: v === "__any__" ? null : (v as PatrolFilterState["skillStage"]),
        })}
        options={[
          { value: "__any__",  label: "全部" },
          { value: "patrol",   label: "patrol（會 alarm）" },
          { value: "diagnose", label: "diagnose（純診斷）" },
        ]}
      />
      <FilterSelect
        label="結果"
        value={value.outcome}
        onChange={(v) => onChange({ ...value, outcome: v as PatrolFilterState["outcome"] })}
        options={[
          { value: "any",            label: "全部" },
          { value: "alarm_emitted",  label: "有 alarm" },
          { value: "step_passed",    label: "step pass 但無 alarm" },
          { value: "no_op",          label: "no-op（空 skill）" },
          { value: "error",          label: "錯誤" },
        ]}
      />
    </div>
  );
}

function FilterSelect({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "#718096" }}>
      <span style={{ fontWeight: 600 }}>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          padding: "5px 8px",
          borderRadius: 5,
          border: "1px solid #e2e8f0",
          fontSize: 12,
          color: "#1a202c",
          background: "#fff",
          cursor: "pointer",
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}
