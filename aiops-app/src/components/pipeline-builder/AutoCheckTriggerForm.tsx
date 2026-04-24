"use client";

/**
 * AutoCheckTriggerForm — controlled form for Auto-Check event_type binding.
 *
 * Shared between:
 *   - AutoCheckPublishModal (post-build publish step)
 *   - /admin/pipeline-builder/new step 2 (wizard, auto_check kind)
 *
 * Auto-Check pipelines fire when an alarm's `trigger_event` matches one of
 * the bound event_types. This form captures the list as a comma/newline
 * separated string (round-trip to/from string[] via helpers).
 */

export interface AutoCheckTriggerValue {
  /** Raw text from the textarea — parsed via parseEventTypes() into string[] */
  eventTypesText: string;
}

export const emptyAutoCheckTrigger = (): AutoCheckTriggerValue => ({ eventTypesText: "" });

export function parseEventTypes(text: string): string[] {
  return text
    .split(/[,\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function validateAutoCheckTrigger(v: AutoCheckTriggerValue): string | null {
  if (parseEventTypes(v.eventTypesText).length === 0) return "請至少填一個 event_type";
  return null;
}

interface Props {
  value: AutoCheckTriggerValue;
  onChange: (next: AutoCheckTriggerValue) => void;
  /** Optional suggested event_type names fetched from server. */
  suggestions?: string[];
}

export default function AutoCheckTriggerForm({ value, onChange, suggestions }: Props) {
  const parsed = parseEventTypes(value.eventTypesText);

  return (
    <div>
      <label style={labelStyle}>Event Types *</label>
      <textarea
        value={value.eventTypesText}
        onChange={(e) => onChange({ eventTypesText: e.target.value })}
        rows={3}
        placeholder="alarm.OOC, alarm.APC_drift, alarm.recipe_mismatch"
        style={{ ...inputStyle, fontFamily: "ui-monospace, monospace", fontSize: 12 }}
      />
      <div style={{ fontSize: 11, color: "#64748B", marginTop: 4 }}>
        用逗號或換行分隔。當 alarm 的 <code>trigger_event</code> 符合其中之一，這個 pipeline 自動被呼叫。
      </div>
      {suggestions && suggestions.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          <span style={{ fontSize: 11, color: "#64748B" }}>建議：</span>
          {suggestions.map((s) => {
            const picked = parsed.includes(s);
            return (
              <button
                key={s}
                type="button"
                onClick={() => {
                  if (picked) {
                    const next = parsed.filter((x) => x !== s).join(", ");
                    onChange({ eventTypesText: next });
                  } else {
                    const next = [...parsed, s].join(", ");
                    onChange({ eventTypesText: next });
                  }
                }}
                style={{
                  padding: "3px 9px", borderRadius: 10, fontSize: 11,
                  border: `1px solid ${picked ? "#7C3AED" : "#E2E8F0"}`,
                  background: picked ? "#F5F3FF" : "#fff",
                  color: picked ? "#7C3AED" : "#64748B",
                  cursor: "pointer",
                }}
              >
                {picked ? "✓ " : "+ "}{s}
              </button>
            );
          })}
        </div>
      )}
      {parsed.length > 0 && (
        <div style={{ fontSize: 11, color: "#475569", marginTop: 6 }}>
          已選 <strong>{parsed.length}</strong> 個：{parsed.join(", ")}
        </div>
      )}
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  fontWeight: 600,
  color: "#4a5568",
  marginBottom: 4,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  border: "1px solid #cbd5e0",
  borderRadius: 6,
  fontSize: 13,
  color: "#2d3748",
  background: "#fff",
  boxSizing: "border-box",
};
