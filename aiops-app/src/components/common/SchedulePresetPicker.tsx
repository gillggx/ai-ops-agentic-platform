"use client";

/**
 * SchedulePresetPicker — shared schedule picker for Auto-Patrol creation.
 *
 * Presets generate a cron expression; "daily" adds an HH:MM input. "once"
 * produces no cron but a scheduled_at ISO timestamp for one-shot execution.
 * Parent owns the raw state (`preset`, `dailyTime`, `scheduledAt`) and the
 * resulting cron string — this component is a controlled presentational
 * element with no internal schedule state, matching the existing
 * /admin/auto-patrols form pattern.
 */

import type { CSSProperties } from "react";

export type SchedulePreset = "1h" | "2h" | "4h" | "6h" | "12h" | "daily" | "once" | "custom";

export const SCHEDULE_PRESETS: Array<{ value: SchedulePreset; label: string; cron: string }> = [
  { value: "1h",     label: "每 1 小時",       cron: "0 * * * *"    },
  { value: "2h",     label: "每 2 小時",       cron: "0 */2 * * *"  },
  { value: "4h",     label: "每 4 小時",       cron: "0 */4 * * *"  },
  { value: "6h",     label: "每 6 小時",       cron: "0 */6 * * *"  },
  { value: "12h",    label: "每 12 小時",      cron: "0 */12 * * *" },
  { value: "daily",  label: "每天指定時間",    cron: ""             },
  { value: "once",   label: "一次性指定時間",  cron: ""             },
  { value: "custom", label: "自訂 cron",       cron: ""             },
];

/**
 * Convert preset + daily HH:MM into a cron expression.
 * Returns "" for `once` (uses scheduled_at instead) and `custom` (user supplies).
 */
export function cronFromPreset(preset: SchedulePreset, dailyTime: string): string {
  if (preset === "daily") {
    const [hh, mm] = dailyTime.split(":").map(Number);
    return `${mm ?? 0} ${hh ?? 8} * * *`;
  }
  if (preset === "once" || preset === "custom") return "";
  return SCHEDULE_PRESETS.find(p => p.value === preset)?.cron ?? "0 * * * *";
}

/** Derive preset from a stored cron string (reverse of cronFromPreset). */
export function presetFromCron(cron: string | null | undefined): { preset: SchedulePreset; dailyTime: string } {
  if (!cron) return { preset: "1h", dailyTime: "09:00" };
  // Match "<mm> <hh> * * *" — daily at fixed HH:MM
  const daily = /^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$/.exec(cron.trim());
  if (daily) {
    const mm = Number(daily[1]);
    const hh = Number(daily[2]);
    return { preset: "daily", dailyTime: `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}` };
  }
  const fixed = SCHEDULE_PRESETS.find(p => p.cron === cron.trim());
  if (fixed) return { preset: fixed.value, dailyTime: "09:00" };
  return { preset: "custom", dailyTime: "09:00" };
}

interface Props {
  preset: SchedulePreset;
  onPresetChange: (p: SchedulePreset) => void;

  dailyTime: string;
  onDailyTimeChange: (t: string) => void;

  /** ISO string (datetime-local format: YYYY-MM-DDTHH:MM) for `once` preset. */
  scheduledAt: string;
  onScheduledAtChange: (iso: string) => void;

  /** Raw cron expression for `custom` preset. */
  customCron: string;
  onCustomCronChange: (c: string) => void;

  /** Whether to show the resolved cron preview footer. */
  showCronPreview?: boolean;

  /** Compact button rows (3 per row) vs wide (6 per row). Modal = compact. */
  layout?: "compact" | "wide";
}

export function SchedulePresetPicker(props: Props) {
  const {
    preset, onPresetChange,
    dailyTime, onDailyTimeChange,
    scheduledAt, onScheduledAtChange,
    customCron, onCustomCronChange,
    showCronPreview = true,
    layout = "compact",
  } = props;

  const gridCols = layout === "wide" ? "repeat(4, 1fr)" : "repeat(3, 1fr)";
  const resolvedCron = preset === "custom" ? customCron : cronFromPreset(preset, dailyTime);

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: gridCols, gap: 8 }}>
        {SCHEDULE_PRESETS.map(p => (
          <button
            key={p.value}
            type="button"
            onClick={() => onPresetChange(p.value)}
            style={presetBtn(preset === p.value)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {preset === "daily" && (
        <div style={{ marginTop: 10 }}>
          <label style={subLabel}>每天執行時間（UTC）</label>
          <input
            type="time"
            value={dailyTime}
            onChange={e => onDailyTimeChange(e.target.value)}
            style={{ ...input, width: 140 }}
          />
        </div>
      )}

      {preset === "once" && (
        <div style={{ marginTop: 10 }}>
          <label style={subLabel}>指定執行時間（本機時區，僅執行一次）</label>
          <input
            type="datetime-local"
            value={scheduledAt}
            onChange={e => onScheduledAtChange(e.target.value)}
            style={{ ...input, width: 220 }}
          />
          <div style={hintText}>
            任務執行完畢後 auto-patrol 會自動 deactivate，不會重覆觸發。
          </div>
        </div>
      )}

      {preset === "custom" && (
        <div style={{ marginTop: 10 }}>
          <label style={subLabel}>Cron Expression</label>
          <input
            type="text"
            value={customCron}
            onChange={e => onCustomCronChange(e.target.value)}
            placeholder="*/5 * * * *"
            style={{ ...input, fontFamily: "ui-monospace, monospace" }}
          />
          <div style={hintText}>
            例：<code>*/5 * * * *</code> 每 5 分鐘 / <code>0 9 * * 1-5</code> 工作日 9 點
          </div>
        </div>
      )}

      {showCronPreview && preset !== "once" && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#718096" }}>
          Resolved cron: <code style={cronCode}>{resolvedCron || "(空)"}</code>
        </div>
      )}
    </div>
  );
}

// ── styles ──────────────────────────────────────────────────────

function presetBtn(active: boolean): CSSProperties {
  return {
    padding: "8px 12px",
    borderRadius: 6,
    cursor: "pointer",
    fontSize: 12,
    border: `1px solid ${active ? "#6366f1" : "#e2e8f0"}`,
    background: active ? "#eef2ff" : "#fff",
    color: active ? "#4338ca" : "#4a5568",
    fontWeight: active ? 600 : 400,
    whiteSpace: "nowrap" as const,
  };
}

const subLabel: CSSProperties = {
  display: "block",
  fontSize: 12,
  fontWeight: 600,
  color: "#4a5568",
  marginBottom: 4,
};

const input: CSSProperties = {
  padding: "7px 10px",
  border: "1px solid #cbd5e0",
  borderRadius: 6,
  fontSize: 13,
  color: "#2d3748",
  boxSizing: "border-box",
};

const hintText: CSSProperties = {
  fontSize: 11,
  color: "#a0aec0",
  marginTop: 4,
};

const cronCode: CSSProperties = {
  background: "#edf2f7",
  padding: "1px 6px",
  borderRadius: 3,
  fontSize: 11,
};
