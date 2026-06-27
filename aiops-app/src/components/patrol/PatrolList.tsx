"use client";

import { formatAlarmSkipped, type PatrolItem } from "./types";

interface Props {
  items: PatrolItem[];
  selected: PatrolItem | null;
  onSelect: (item: PatrolItem) => void;
}

const HEADERS = [
  { key: "time",   label: "Time" },
  { key: "event",  label: "Event" },
  { key: "equip",  label: "Equipment" },
  { key: "skill",  label: "Skill (stage)" },
  { key: "steps",  label: "Steps" },
  { key: "result", label: "Result" },
];

export function PatrolList({ items, selected, onSelect }: Props) {
  if (items.length === 0) {
    return (
      <div style={{
        background: "#fff",
        border: "1px solid #e2e8f0",
        borderRadius: 8,
        padding: "30px 20px",
        textAlign: "center",
        color: "#a0aec0",
        fontSize: 13,
      }}>
        所選範圍內沒有 skill 執行。試試放寬時間範圍或拿掉 filter。
      </div>
    );
  }

  return (
    <div style={{
      background: "#fff",
      border: "1px solid #e2e8f0",
      borderRadius: 8,
      overflow: "hidden",
    }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ background: "#f7f8fc" }}>
            {HEADERS.map((h) => (
              <th key={h.key} style={{
                padding: "9px 12px",
                textAlign: "left",
                fontWeight: 700,
                color: "#4a5568",
                borderBottom: "1px solid #e2e8f0",
                whiteSpace: "nowrap",
                fontSize: 10,
                textTransform: "uppercase",
                letterSpacing: "0.4px",
              }}>{h.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const isActive = selected?.skillRunId === item.skillRunId;
            return (
              <tr
                key={item.skillRunId}
                onClick={() => onSelect(item)}
                style={{
                  cursor: "pointer",
                  background: isActive ? "#ebf8ff" : "transparent",
                  borderBottom: "1px solid #f0f4f8",
                }}
              >
                <td style={tdStyle}>{formatTime(item.triggeredAt)}</td>
                <td style={tdStyle}>
                  <span style={eventChip(item.eventType)}>{item.eventType ?? "—"}</span>
                </td>
                <td style={{ ...tdStyle, fontFamily: "ui-monospace, monospace", color: "#4a5568" }}>
                  {item.equipmentId ?? "—"}
                </td>
                <td style={tdStyle}>
                  <div style={{ fontWeight: 600, color: "#1a202c" }}>
                    {item.skillTitle ?? item.skillSlug ?? `skill #${item.skillId}`}
                  </div>
                  <div style={{ fontSize: 10, color: "#a0aec0" }}>
                    {item.skillSlug ?? ""} · stage={item.skillStage ?? "—"}
                  </div>
                </td>
                <td style={{ ...tdStyle, fontFamily: "ui-monospace, monospace" }}>
                  {item.stepsPassed}/{item.stepsTotal}
                </td>
                <td style={tdStyle}>
                  <ResultBadge item={item} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ResultBadge({ item }: { item: PatrolItem }) {
  if (item.alarmId) {
    return <span style={badge("#3182ce", "#ebf8ff")}>Alarm #{item.alarmId}</span>;
  }
  if (item.alarmSkippedReason) {
    return <span style={badge("#9c4221", "#fffaf0")}>{formatAlarmSkipped(item.alarmSkippedReason)}</span>;
  }
  if (item.status === "failed" || item.status === "error") {
    return <span style={badge("#c53030", "#fff5f5")}>{item.status}</span>;
  }
  if (item.stepsTotal === 0) {
    return <span style={badge("#718096", "#f7f8fc")}>no-op</span>;
  }
  if (item.stepsPassed > 0) {
    return <span style={badge("#22543d", "#f0fff4")}>step pass</span>;
  }
  return <span style={badge("#718096", "#f7f8fc")}>{item.status}</span>;
}

function badge(color: string, bg: string): React.CSSProperties {
  return {
    display: "inline-block",
    fontSize: 11,
    fontWeight: 600,
    padding: "2px 8px",
    borderRadius: 4,
    color,
    background: bg,
    border: `1px solid ${color}33`,
    whiteSpace: "nowrap",
  };
}

function eventChip(eventType: string | null): React.CSSProperties {
  const isOOC = eventType === "OOC";
  return {
    display: "inline-block",
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 7px",
    borderRadius: 4,
    color: isOOC ? "#744210" : "#2b6cb0",
    background: isOOC ? "#fefcbf" : "#ebf8ff",
  };
}

const tdStyle: React.CSSProperties = {
  padding: "9px 12px",
  color: "#2d3748",
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
