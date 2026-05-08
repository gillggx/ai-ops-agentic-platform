"use client";

/**
 * Phase 9-fix-3 — friendly schedule editor.
 *
 * Replaces the "0 8 * * 1" cron textbox with a preset dropdown + time
 * picker so non-engineer users can author / edit personal-rule
 * schedules. The component still emits a 5-field cron string up to its
 * parent (so backend / executor / docs all stay unchanged).
 *
 * Power users can flip to "自訂 cron" — the same expressions work, and
 * presets that don't round-trip cleanly fall back to advanced
 * automatically.
 */

import { useEffect, useMemo, useState } from "react";

type Mode = "daily" | "weekly" | "weekday" | "monthly" | "hourly" | "advanced";

interface Props {
  /** Cron string ("0 8 * * 1") — controlled by parent. */
  value: string;
  onChange: (cron: string) => void;
  /** Compact (one-line) vs full (with preview). Default: full. */
  compact?: boolean;
}

const WEEKDAY_LABELS = ["週日", "週一", "週二", "週三", "週四", "週五", "週六"];

/** Parse a cron back into UI state. Falls back to "advanced" if exotic. */
function parseCron(cron: string): { mode: Mode; hour: number; minute: number; dow: number; dom: number } {
  const fields = cron.trim().split(/\s+/);
  const fallback = { mode: "advanced" as Mode, hour: 8, minute: 0, dow: 1, dom: 1 };
  if (fields.length !== 5) return fallback;
  const [m, h, dom, mon, dow] = fields;
  const mi = parseInt(m, 10);
  const hi = parseInt(h, 10);
  if (Number.isNaN(mi) || Number.isNaN(hi)) return fallback;
  if (mon !== "*") return fallback;

  // Hourly: 0 * * * *
  if (m !== "*" && h === "*" && dom === "*" && dow === "*") {
    return { mode: "hourly", hour: 0, minute: mi, dow: 1, dom: 1 };
  }
  // Daily: m h * * *
  if (dom === "*" && dow === "*") {
    return { mode: "daily", hour: hi, minute: mi, dow: 1, dom: 1 };
  }
  // Weekly (single day): m h * * d
  if (dom === "*" && /^[0-6]$/.test(dow)) {
    return { mode: "weekly", hour: hi, minute: mi, dow: parseInt(dow, 10), dom: 1 };
  }
  // Weekday (Mon-Fri): m h * * 1-5
  if (dom === "*" && dow === "1-5") {
    return { mode: "weekday", hour: hi, minute: mi, dow: 1, dom: 1 };
  }
  // Monthly: m h d * *
  if (/^\d+$/.test(dom) && dow === "*") {
    return { mode: "monthly", hour: hi, minute: mi, dow: 1, dom: parseInt(dom, 10) };
  }
  return fallback;
}

function buildCron(mode: Mode, hour: number, minute: number, dow: number, dom: number, raw: string): string {
  const m = String(minute);
  const h = String(hour);
  switch (mode) {
    case "hourly":  return `${m} * * * *`;
    case "daily":   return `${m} ${h} * * *`;
    case "weekly":  return `${m} ${h} * * ${dow}`;
    case "weekday": return `${m} ${h} * * 1-5`;
    case "monthly": return `${m} ${h} ${dom} * *`;
    case "advanced": return raw;
  }
}

function describe(mode: Mode, hour: number, minute: number, dow: number, dom: number): string {
  const t = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  switch (mode) {
    case "hourly":  return `每小時的第 ${minute} 分`;
    case "daily":   return `每天 ${t}`;
    case "weekly":  return `每${WEEKDAY_LABELS[dow]} ${t}`;
    case "weekday": return `每週一到五 ${t}`;
    case "monthly": return `每月 ${dom} 號 ${t}`;
    case "advanced": return "自訂 cron 表達式";
  }
}

export function ScheduleEditor({ value, onChange, compact }: Props) {
  // Parse incoming cron once on mount + when parent forces a fresh value.
  const initial = useMemo(() => parseCron(value), [value]);
  const [mode, setMode] = useState<Mode>(initial.mode);
  const [hour, setHour] = useState(initial.hour);
  const [minute, setMinute] = useState(initial.minute);
  const [dow, setDow] = useState(initial.dow);
  const [dom, setDom] = useState(initial.dom);
  const [raw, setRaw] = useState(value);

  // Re-emit cron whenever any field changes.
  useEffect(() => {
    const next = buildCron(mode, hour, minute, dow, dom, raw);
    if (next !== value) onChange(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, hour, minute, dow, dom, raw]);

  // Re-sync raw when parent value changes (e.g. switching rules).
  useEffect(() => {
    if (value !== buildCron(mode, hour, minute, dow, dom, raw)) {
      const re = parseCron(value);
      setMode(re.mode);
      setHour(re.hour);
      setMinute(re.minute);
      setDow(re.dow);
      setDom(re.dom);
      setRaw(value);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const description = describe(mode, hour, minute, dow, dom);
  const derivedCron = buildCron(mode, hour, minute, dow, dom, raw);

  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} style={selStyle}>
          <option value="daily">每天</option>
          <option value="weekly">每週某天</option>
          <option value="weekday">每週一到五</option>
          <option value="monthly">每月某一天</option>
          <option value="hourly">每小時</option>
          <option value="advanced">自訂 cron</option>
        </select>

        {mode === "weekly" && (
          <select value={dow} onChange={(e) => setDow(parseInt(e.target.value, 10))} style={selStyle}>
            {WEEKDAY_LABELS.map((lbl, i) => <option key={i} value={i}>{lbl}</option>)}
          </select>
        )}

        {mode === "monthly" && (
          <select value={dom} onChange={(e) => setDom(parseInt(e.target.value, 10))} style={selStyle}>
            {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
              <option key={d} value={d}>{d} 號</option>
            ))}
          </select>
        )}

        {mode !== "hourly" && mode !== "advanced" && (
          <>
            <select value={hour} onChange={(e) => setHour(parseInt(e.target.value, 10))} style={selStyle}>
              {Array.from({ length: 24 }, (_, i) => i).map((h) => (
                <option key={h} value={h}>{String(h).padStart(2, "0")}</option>
              ))}
            </select>
            <span style={{ color: "#94a3b8" }}>:</span>
            <select value={minute} onChange={(e) => setMinute(parseInt(e.target.value, 10))} style={selStyle}>
              {[0, 15, 30, 45].map((m) => (
                <option key={m} value={m}>{String(m).padStart(2, "0")}</option>
              ))}
            </select>
          </>
        )}

        {mode === "hourly" && (
          <>
            <span style={{ color: "#475569", fontSize: 12 }}>每小時的第</span>
            <select value={minute} onChange={(e) => setMinute(parseInt(e.target.value, 10))} style={selStyle}>
              {[0, 15, 30, 45].map((m) => (
                <option key={m} value={m}>{String(m).padStart(2, "0")}</option>
              ))}
            </select>
            <span style={{ color: "#475569", fontSize: 12 }}>分</span>
          </>
        )}

        {mode === "advanced" && (
          <input
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder="0 8 * * 1"
            style={{ ...inputStyle, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12, flex: 1, minWidth: 120 }}
          />
        )}
      </div>

      {!compact && (
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 6, display: "flex", gap: 12, flexWrap: "wrap" }}>
          <span>📖 <b>{description}</b></span>
          <span style={{ fontFamily: "ui-monospace, Menlo, monospace", color: "#94a3b8" }}>
            cron = <code>{derivedCron || "(empty)"}</code>
          </span>
        </div>
      )}
    </div>
  );
}

const selStyle: React.CSSProperties = {
  padding: "5px 8px",
  border: "1px solid #fcd34d",
  borderRadius: 4,
  fontSize: 12,
  background: "#fff",
  cursor: "pointer",
};

const inputStyle: React.CSSProperties = {
  padding: "5px 8px",
  border: "1px solid #fcd34d",
  borderRadius: 4,
  fontSize: 12,
};
