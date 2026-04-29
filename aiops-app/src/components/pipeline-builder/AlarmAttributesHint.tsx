"use client";

/**
 * AlarmAttributesHint — read-only reference card for the alarm fields
 * available to auto_check pipelines.
 *
 * Surfaces the canonical list so a publisher knows which keys their
 * pipeline can declare as inputs (auto-injected by name) and which keys
 * a {@code match_filter} clause may reference. Mirrors the runtime
 * payload built by EventDispatchService.alarmToPayload on the Java side.
 */

export interface AlarmAttribute {
  name: string;
  type: string;
  description: string;
  required: boolean;
}

export const ALARM_ATTRIBUTES: AlarmAttribute[] = [
  {
    name: "equipment_id",
    type: "string",
    required: true,
    description: "alarm 發生在哪台機台（也以 tool_id 別名暴露）",
  },
  {
    name: "lot_id",
    type: "string",
    required: true,
    description: "alarm 對應批次",
  },
  {
    name: "step",
    type: "string",
    required: false,
    description: "製程站點，例如 STEP_001（部分 alarm 才有）",
  },
  {
    name: "severity",
    type: "string",
    required: true,
    description: "嚴重度 — LOW / MEDIUM / HIGH / CRITICAL",
  },
  {
    name: "trigger_event",
    type: "string",
    required: true,
    description: "觸發類型字串（用於 binding；e.g. 'spc.ooc'）",
  },
  {
    name: "event_time",
    type: "string",
    required: false,
    description: "alarm 時間 (ISO-8601)",
  },
  {
    name: "title",
    type: "string",
    required: true,
    description: "alarm 標題（人類可讀）",
  },
  {
    name: "summary",
    type: "string",
    required: false,
    description: "alarm 摘要文字（含 evidence 預覽）",
  },
];

interface Props {
  /** Default false — collapsible to avoid stealing modal real estate. */
  defaultOpen?: boolean;
}

export default function AlarmAttributesHint({ defaultOpen = false }: Props) {
  return (
    <details
      open={defaultOpen}
      style={{
        background: "#f1f5f9",
        border: "1px solid #cbd5e0",
        borderRadius: 6,
        padding: "8px 12px",
        fontSize: 12,
        marginBottom: 14,
      }}
    >
      <summary
        style={{
          fontWeight: 600,
          color: "#334155",
          cursor: "pointer",
          listStyle: "none",
        }}
      >
        💡 Alarm 可用屬性（auto_check pipeline 可從這些欄位拿值）
      </summary>
      <div style={{ marginTop: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #cbd5e0", color: "#64748b" }}>
              <th style={th}>名稱</th>
              <th style={th}>型別</th>
              <th style={th}>必填</th>
              <th style={{ ...th, width: "60%" }}>說明</th>
            </tr>
          </thead>
          <tbody>
            {ALARM_ATTRIBUTES.map((a) => (
              <tr key={a.name} style={{ borderBottom: "1px solid #e2e8f0" }}>
                <td style={tdMono}>{a.name}</td>
                <td style={td}>{a.type}</td>
                <td style={td}>{a.required ? "✓" : "—"}</td>
                <td style={td}>{a.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: 8, color: "#64748b", lineHeight: 1.6 }}>
          • Pipeline 宣告 input 名稱跟上表對齊就會在 runtime 自動 binding。<br />
          • 「附加條件 (match_filter)」可從上表挑欄位 + 期望值來縮窄觸發。
        </div>
      </div>
    </details>
  );
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "6px 8px",
  fontWeight: 600,
};

const td: React.CSSProperties = {
  padding: "6px 8px",
  color: "#334155",
  verticalAlign: "top",
};

const tdMono: React.CSSProperties = {
  ...td,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  color: "#1e40af",
  fontWeight: 600,
};
