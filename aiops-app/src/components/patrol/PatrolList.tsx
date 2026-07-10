"use client";

import { useTranslations } from "next-intl";
import { formatAlarmSkipped, type PatrolItem } from "./types";
import { activeLocale } from "@/i18n/format";

interface Props {
  items: PatrolItem[];
  selected: PatrolItem | null;
  onSelect: (item: PatrolItem) => void;
}

// labelKey → messages/<locale>/patrol.json
const HEADERS = [
  { key: "time",   labelKey: "colTime" },
  { key: "event",  labelKey: "colEvent" },
  { key: "equip",  labelKey: "colEquipment" },
  { key: "skill",  labelKey: "colSkill" },
  { key: "steps",  labelKey: "colSteps" },
  { key: "result", labelKey: "colResult" },
];

export function PatrolList({ items, selected, onSelect }: Props) {
  const t = useTranslations("patrol");
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
        {t("emptyList")}
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
          <tr style={{ background: "var(--pn, #f7f8fc)" }}>
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
              }}>{t(h.labelKey)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const isActive = selected?.skill_run_id === item.skill_run_id;
            return (
              <tr
                key={item.skill_run_id}
                onClick={() => onSelect(item)}
                style={{
                  cursor: "pointer",
                  background: isActive ? "var(--pl, #ebf8ff)" : "transparent",
                  borderBottom: "1px solid #f0f4f8",
                }}
              >
                <td style={tdStyle}>{formatTime(item.triggered_at)}</td>
                <td style={tdStyle}>
                  <span style={eventChip(item.event_type)}>{item.event_type ?? "—"}</span>
                </td>
                <td style={{ ...tdStyle, fontFamily: "ui-monospace, monospace", color: "#4a5568" }}>
                  {item.equipment_id ?? "—"}
                </td>
                <td style={tdStyle}>
                  <div style={{ fontWeight: 600, color: "#1a202c" }}>
                    {item.skill_title ?? item.skill_slug ?? `skill #${item.skill_id}`}
                  </div>
                  <div style={{ fontSize: 10, color: "#a0aec0" }}>
                    {item.skill_slug ?? ""} · stage={item.skill_stage ?? "—"}
                  </div>
                </td>
                <td style={{ ...tdStyle, fontFamily: "ui-monospace, monospace" }}>
                  {item.steps_passed}/{item.steps_total}
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
  const t = useTranslations("patrol");
  if (item.alarm_id) {
    return <span style={badge("var(--p, #3182ce)", "var(--pl, #ebf8ff)")}>{t("alarmRef", { id: item.alarm_id })}</span>;
  }
  if (item.alarm_skipped_reason) {
    return <span style={badge("#9c4221", "#fffaf0")}>{formatAlarmSkipped(item.alarm_skipped_reason, t)}</span>;
  }
  if (item.status === "failed" || item.status === "error") {
    return <span style={badge("#c53030", "#fff5f5")}>{item.status}</span>;
  }
  if (item.steps_total === 0) {
    return <span style={badge("#718096", "var(--pn, #f7f8fc)")}>no-op</span>;
  }
  if (item.steps_passed > 0) {
    return <span style={badge("#22543d", "#f0fff4")}>step pass</span>;
  }
  return <span style={badge("#718096", "var(--pn, #f7f8fc)")}>{item.status}</span>;
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
    color: isOOC ? "#744210" : "var(--p, #2b6cb0)",
    background: isOOC ? "#fefcbf" : "var(--pl, #ebf8ff)",
  };
}

const tdStyle: React.CSSProperties = {
  padding: "9px 12px",
  color: "#2d3748",
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString(activeLocale(), { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
