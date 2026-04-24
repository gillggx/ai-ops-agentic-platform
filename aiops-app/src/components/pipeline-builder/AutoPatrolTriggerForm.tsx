"use client";

/**
 * AutoPatrolTriggerForm — controlled form for Auto-Patrol trigger config.
 *
 * Shared between:
 *   - AutoPatrolSetupModal (post-build 🔔 button)
 *   - /admin/pipeline-builder/new step 2 (wizard)
 *   - /admin/auto-patrols legacy form (future cleanup — still inline there)
 *
 * This is a *pure form* — no modal chrome, no submit button, no API calls.
 * Parent owns state via value/onChange and decides when to POST.
 */

import { useEffect, useState } from "react";
import {
  SchedulePresetPicker,
  cronFromPreset,
  presetFromCron,
  type SchedulePreset,
} from "@/components/common/SchedulePresetPicker";

export type TriggerMode = "event" | "schedule" | "once";

/**
 * The canonical trigger payload handed to the Auto-Patrol create/update API.
 * Fields are mutually exclusive by mode — the parent (or wizard) reads `.mode`
 * and picks the matching fields.
 */
export interface AutoPatrolTriggerValue {
  mode: TriggerMode;
  /** Only for mode=event */
  eventTypeId: number | null;
  /** Only for mode=schedule — final cron expression */
  cronExpr: string;
  /** Only for mode=once — ISO 8601 UTC timestamp */
  scheduledAt: string;
}

export const emptyTrigger = (): AutoPatrolTriggerValue => ({
  mode: "event",
  eventTypeId: null,
  cronExpr: "",
  scheduledAt: "",
});

export type EventType = { id: number; name: string };

interface Props {
  value: AutoPatrolTriggerValue;
  onChange: (next: AutoPatrolTriggerValue) => void;
  /** Supply from parent — AutoPatrolTriggerForm doesn't fetch. */
  eventTypes: EventType[];
  /** Label style for the section header. Default "標準" (14px bold). */
  compact?: boolean;
}

export default function AutoPatrolTriggerForm({ value, onChange, eventTypes, compact = false }: Props) {
  // Schedule picker state — derived from value.cronExpr on mount / prop change.
  const [preset, setPreset] = useState<SchedulePreset>("1h");
  const [dailyTime, setDailyTime] = useState("09:00");
  const [customCron, setCustomCron] = useState("*/5 * * * *");

  // datetime-local picker value for mode=once (YYYY-MM-DDTHH:MM, local timezone)
  const [scheduledAtLocal, setScheduledAtLocal] = useState("");

  // Hydrate from value on mount + when value.cronExpr / scheduledAt changes externally
  useEffect(() => {
    if (value.mode === "schedule" && value.cronExpr) {
      const { preset: p, dailyTime: dt } = presetFromCron(value.cronExpr);
      setPreset(p);
      setDailyTime(dt);
      if (p === "custom") setCustomCron(value.cronExpr);
    }
    if (value.mode === "once" && value.scheduledAt) {
      const d = new Date(value.scheduledAt);
      if (!Number.isNaN(d.getTime())) {
        const tzOffsetMs = d.getTimezoneOffset() * 60_000;
        setScheduledAtLocal(new Date(d.getTime() - tzOffsetMs).toISOString().slice(0, 16));
      }
    }
    if (value.mode === "once" && preset !== "once") setPreset("once");
    if (value.mode === "schedule" && preset === "once") setPreset("1h");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.mode, value.cronExpr, value.scheduledAt]);

  const patch = (patch: Partial<AutoPatrolTriggerValue>) => onChange({ ...value, ...patch });

  const setMode = (mode: TriggerMode) => {
    if (mode === "once") {
      setPreset("once");
      patch({ mode, cronExpr: "" });
    } else if (mode === "schedule") {
      if (preset === "once") setPreset("1h");
      const cron = preset === "custom" ? customCron : cronFromPreset(preset, dailyTime);
      patch({ mode, cronExpr: cron, scheduledAt: "" });
    } else {
      patch({ mode, cronExpr: "", scheduledAt: "" });
    }
  };

  const handlePresetChange = (p: SchedulePreset) => {
    setPreset(p);
    if (p === "once") {
      patch({ mode: "once" });
    } else {
      if (value.mode === "once") patch({ mode: "schedule" });
      const cron = p === "custom" ? customCron : cronFromPreset(p, dailyTime);
      patch({ cronExpr: cron });
    }
  };

  const handleDailyTimeChange = (t: string) => {
    setDailyTime(t);
    if (preset === "daily") patch({ cronExpr: cronFromPreset("daily", t) });
  };

  const handleCustomCronChange = (c: string) => {
    setCustomCron(c);
    if (preset === "custom") patch({ cronExpr: c });
  };

  const handleScheduledAtLocalChange = (local: string) => {
    setScheduledAtLocal(local);
    if (!local) { patch({ scheduledAt: "" }); return; }
    const d = new Date(local);
    if (!Number.isNaN(d.getTime())) patch({ scheduledAt: d.toISOString() });
  };

  const rowStyle = { marginBottom: compact ? 10 : 14 } as React.CSSProperties;

  return (
    <div>
      {/* Mode selector */}
      <div style={{ display: "flex", gap: 10, marginBottom: compact ? 10 : 14 }}>
        {([
          { m: "event" as const,    icon: "⚡", label: "事件觸發",   desc: "OOC 事件發生時立即執行" },
          { m: "schedule" as const, icon: "🕐", label: "排程觸發",   desc: "依固定週期定時執行" },
          { m: "once" as const,     icon: "📌", label: "指定時間",   desc: "一次性：跑一次後自動停用" },
        ]).map(({ m, icon, label, desc }) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            style={{
              flex: 1, padding: compact ? "8px 12px" : "10px 16px", borderRadius: 8, cursor: "pointer",
              border: `2px solid ${value.mode === m ? "#6366f1" : "#e2e8f0"}`,
              background: value.mode === m ? "#eef2ff" : "#fff",
              color: value.mode === m ? "#4338ca" : "#4a5568",
              fontWeight: value.mode === m ? 600 : 400, fontSize: 13,
              textAlign: "left",
            }}
          >
            {icon} {label}
            <div style={{ fontSize: 11, fontWeight: 400, marginTop: 3, color: "#718096" }}>{desc}</div>
          </button>
        ))}
      </div>

      {/* Event: event_type dropdown */}
      {value.mode === "event" && (
        <div style={rowStyle}>
          <label style={labelStyle}>事件類型 *</label>
          <select
            value={value.eventTypeId ?? ""}
            onChange={(e) => patch({ eventTypeId: e.target.value ? Number(e.target.value) : null })}
            style={inputStyle}
          >
            <option value="">— 選擇事件類型 —</option>
            {eventTypes.map((et) => (
              <option key={et.id} value={String(et.id)}>{et.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Schedule / Once: SchedulePresetPicker */}
      {(value.mode === "schedule" || value.mode === "once") && (
        <div style={rowStyle}>
          <label style={labelStyle}>{value.mode === "once" ? "指定時間" : "排程設定"}</label>
          <SchedulePresetPicker
            preset={preset}
            onPresetChange={handlePresetChange}
            dailyTime={dailyTime}
            onDailyTimeChange={handleDailyTimeChange}
            scheduledAt={scheduledAtLocal}
            onScheduledAtChange={handleScheduledAtLocalChange}
            customCron={customCron}
            onCustomCronChange={handleCustomCronChange}
            layout="compact"
          />
        </div>
      )}
    </div>
  );
}

/**
 * Validate a trigger value. Returns null if valid, else an error message in 中文.
 */
export function validateTrigger(v: AutoPatrolTriggerValue): string | null {
  if (v.mode === "event") {
    if (v.eventTypeId == null) return "請選擇事件類型";
  } else if (v.mode === "schedule") {
    if (!v.cronExpr.trim()) return "請填入有效的 cron expression";
  } else if (v.mode === "once") {
    if (!v.scheduledAt) return "請選指定執行時間";
    const d = new Date(v.scheduledAt);
    if (Number.isNaN(d.getTime())) return "指定時間格式無效";
    if (d.getTime() <= Date.now()) return "指定時間必須在未來";
  }
  return null;
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
