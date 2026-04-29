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
  /** Optional active auto_patrol list. Each becomes a checkbox that maps
   *  to `auto_patrol:{id}` trigger_event token (the string written by
   *  AutoPatrolExecutor.writeAlarm when a patrol fires an alarm). */
  patrolSuggestions?: Array<{ id: number; name: string }>;
}

export default function AutoCheckTriggerForm({
  value, onChange, suggestions, patrolSuggestions,
}: Props) {
  const parsed = parseEventTypes(value.eventTypesText);

  // When suggestions are available, favour a checkbox-style picker over the
  // textarea — this is the common case and makes the "bind to alarm events"
  // semantics obvious. Textarea is still rendered below for power users to
  // free-type custom trigger_event names.
  const hasSuggestions = (suggestions?.length ?? 0) > 0;
  const hasPatrols = (patrolSuggestions?.length ?? 0) > 0;

  const togglePick = (token: string) => {
    if (parsed.includes(token)) {
      onChange({ eventTypesText: parsed.filter((x) => x !== token).join(", ") });
    } else {
      onChange({ eventTypesText: [...parsed, token].join(", ") });
    }
  };

  return (
    <div>
      <label style={labelStyle}>要綁定的 Alarm 觸發事件 *</label>
      <div style={{
        background: "#f0f9ff", border: "1px solid #bae6fd",
        borderRadius: 6, padding: "8px 10px", fontSize: 11,
        color: "#0369a1", marginBottom: 8, lineHeight: 1.6,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>💡 Auto-Check = 診斷規則</div>
        這個 pipeline 會在 <strong>Auto-Patrol 觸發 alarm 時</strong>自動被呼叫執行診斷。勾選下方想綁定的 alarm 事件（alarm 的 <code>trigger_event</code> 欄位比對）。
      </div>

      {hasSuggestions && (
        <>
          <div style={sectionTitleStyle}>📋 從事件類型 (event_types)</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
            {suggestions!.map((s) => {
              const picked = parsed.includes(s);
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => togglePick(s)}
                  style={chipStyle(picked, "#7C3AED", "#F5F3FF")}
                >
                  {picked ? "☑" : "☐"}  {s}
                </button>
              );
            })}
          </div>
        </>
      )}

      {hasPatrols && (
        <>
          <div style={sectionTitleStyle}>🔔 從現有 Auto-Patrol（綁定該 patrol 觸發的 alarm）</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
            {patrolSuggestions!.map((p) => {
              const token = `auto_patrol:${p.id}`;
              const picked = parsed.includes(token);
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => togglePick(token)}
                  style={chipStyle(picked, "#0891B2", "#ECFEFF")}
                  title={`綁定 trigger_event="${token}"`}
                >
                  {picked ? "☑" : "☐"}  Patrol #{p.id} 「{p.name}」
                </button>
              );
            })}
          </div>
        </>
      )}

      <details style={{ marginTop: 6 }}>
        <summary style={{ fontSize: 11, color: "#64748B", cursor: "pointer" }}>
          + 進階：自訂 trigger_event 字串（{hasSuggestions ? "不在上方清單的" : "沒有 event_type 建議時的"}備用輸入）
        </summary>
        <textarea
          value={value.eventTypesText}
          onChange={(e) => onChange({ eventTypesText: e.target.value })}
          rows={3}
          placeholder="alarm.OOC, alarm.APC_drift, alarm.recipe_mismatch"
          style={{ ...inputStyle, fontFamily: "ui-monospace, monospace", fontSize: 12, marginTop: 6 }}
        />
        <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 4 }}>
          用逗號或換行分隔。勾選上方建議會自動寫入這個欄位。
        </div>
      </details>

      {parsed.length > 0 && (
        <div style={{
          marginTop: 10, padding: "6px 10px", borderRadius: 6,
          background: "#ecfdf5", border: "1px solid #a7f3d0",
          fontSize: 11, color: "#065f46",
        }}>
          ✓ 已綁 <strong>{parsed.length}</strong> 個 alarm 事件：{parsed.join(", ")}
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

const sectionTitleStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  color: "#475569",
  marginTop: 6,
  marginBottom: 4,
};

function chipStyle(picked: boolean, accent: string, bg: string): React.CSSProperties {
  return {
    padding: "6px 12px",
    borderRadius: 6,
    fontSize: 12,
    border: `1px solid ${picked ? accent : "#CBD5E0"}`,
    background: picked ? bg : "#fff",
    color: picked ? accent : "#475569",
    fontWeight: picked ? 600 : 400,
    cursor: "pointer",
  };
}

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
