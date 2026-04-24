"use client";

/**
 * Phase β of Option A UX consolidation:
 * Create an Auto-Patrol binding for the current pipeline without
 * leaving the Pipeline Builder. Fields are a lean subset of the old
 * /admin/auto-patrols form — skip skill-mode, AI step generation, and
 * diagnostic rule pickers (those live on the legacy page for now).
 *
 * P2.2 — schedule picker upgraded from raw cron to SchedulePresetPicker
 * (每 N 小時 / 每天指定時間 / 一次性指定時間 / 自訂 cron).
 */
import { useEffect, useState } from "react";
import {
  SchedulePresetPicker,
  cronFromPreset,
  type SchedulePreset,
} from "@/components/common/SchedulePresetPicker";

type EventType = { id: number; name: string };

export default function AutoPatrolSetupModal({
  open, pipelineId, pipelineName, onClose, onCreated,
}: {
  open: boolean;
  pipelineId: number;
  pipelineName: string;
  onClose: () => void;
  onCreated: (patrolId: number) => void;
}) {
  const [name, setName]             = useState("");
  const [description, setDesc]      = useState("");
  const [triggerMode, setTriggerMode] = useState<"schedule" | "event" | "once">("event");
  const [preset, setPreset]         = useState<SchedulePreset>("1h");
  const [dailyTime, setDailyTime]   = useState("09:00");
  const [scheduledAt, setScheduledAt] = useState("");  // datetime-local format
  const [customCron, setCustomCron] = useState("*/5 * * * *");
  const [eventTypeId, setEventTypeId] = useState<number | null>(null);
  const [severity, setSeverity]     = useState<"LOW" | "MEDIUM" | "HIGH" | "CRITICAL">("HIGH");
  const [alarmTitle, setAlarmTitle] = useState("");
  const [inputBinding, setInputBinding] = useState("{}");
  const [eventTypes, setEventTypes] = useState<EventType[]>([]);
  const [saving, setSaving]         = useState(false);
  const [error, setError]           = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    // Load event types for the dropdown
    fetch("/api/admin/event-types", { cache: "no-store" })
      .then(r => r.json())
      .then(d => {
        const items = Array.isArray(d) ? d : (d?.data ?? []);
        setEventTypes(items as EventType[]);
        if (items.length > 0 && eventTypeId === null) setEventTypeId(items[0].id);
      })
      .catch(() => setEventTypes([]));
    // Reset form on re-open
    setName(`[Patrol] ${pipelineName}`.slice(0, 200));
    setAlarmTitle(pipelineName);
    setError(null);
  }, [open, pipelineName]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Keep triggerMode in sync with preset: picking "once" in the picker should
  // switch trigger_mode to "once" so the backend schedules a DateTrigger.
  useEffect(() => {
    if (triggerMode === "event") return;
    if (preset === "once" && triggerMode !== "once") setTriggerMode("once");
    if (preset !== "once" && triggerMode === "once") setTriggerMode("schedule");
  }, [preset, triggerMode]);

  if (!open) return null;

  async function handleSave() {
    if (!name.trim()) { setError("Patrol 名稱必填"); return; }
    if (triggerMode === "event" && eventTypeId == null) { setError("請選事件類型"); return; }

    let cronExpr: string | null = null;
    let scheduledAtIso: string | null = null;
    if (triggerMode === "schedule") {
      cronExpr = preset === "custom" ? customCron.trim() : cronFromPreset(preset, dailyTime);
      if (!cronExpr) { setError("請填入有效的 cron expression"); return; }
    } else if (triggerMode === "once") {
      if (!scheduledAt) { setError("請選指定執行時間"); return; }
      // Convert local datetime to ISO 8601 (with timezone)
      const d = new Date(scheduledAt);
      if (Number.isNaN(d.getTime())) { setError("指定時間格式無效"); return; }
      if (d.getTime() <= Date.now()) { setError("指定時間必須在未來"); return; }
      scheduledAtIso = d.toISOString();
    }

    // Validate input_binding JSON
    let inputBindingParsed: Record<string, unknown> | null = null;
    if (inputBinding.trim()) {
      try { inputBindingParsed = JSON.parse(inputBinding); }
      catch { setError("input_binding 不是有效的 JSON"); return; }
    }

    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        description: description.trim(),
        trigger_mode: triggerMode,
        cron_expr: cronExpr,
        scheduled_at: scheduledAtIso,
        event_type_id: triggerMode === "event" ? eventTypeId : null,
        execution_mode: "pipeline",
        pipeline_id: pipelineId,
        alarm_severity: severity,
        alarm_title: alarmTitle.trim() || name.trim(),
        input_binding: inputBindingParsed ? JSON.stringify(inputBindingParsed) : null,
        data_context: "event_driven",
        target_scope: JSON.stringify({ type: "event_driven" }),
        is_active: true,
      };
      const res = await fetch("/api/admin/auto-patrols", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(`HTTP ${res.status}: ${t.slice(0, 200)}`);
      }
      const body = await res.json();
      const created = body?.data ?? body;
      onCreated(created.id);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={modal} onClick={e => e.stopPropagation()}>
        <div style={header}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#1a202c" }}>🔔 Schedule as Auto-Patrol</h3>
          <button onClick={onClose} style={closeBtn}>✕</button>
        </div>

        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, fontSize: 13 }}>

          <div style={{ fontSize: 12, color: "#718096" }}>
            這個 patrol 會定期執行 Pipeline <code style={{ background: "#edf2f7", padding: "2px 6px", borderRadius: 3 }}>#{pipelineId} {pipelineName}</code>，觸發警報時寫入 alarms。
          </div>

          <Field label="Patrol 名稱 *">
            <input value={name} onChange={e => setName(e.target.value)} style={input} />
          </Field>

          <Field label="描述">
            <input value={description} onChange={e => setDesc(e.target.value)} style={input}
              placeholder="(可選，說明這個 patrol 做什麼)" />
          </Field>

          <Field label="觸發模式">
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {([
                { v: "event",    l: "事件觸發 (例如 OOC)" },
                { v: "schedule", l: "排程觸發" },
                { v: "once",     l: "一次性指定時間" },
              ] as const).map(m => (
                <label key={m.v} style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                  <input
                    type="radio"
                    checked={triggerMode === m.v}
                    onChange={() => {
                      setTriggerMode(m.v);
                      if (m.v === "once") setPreset("once");
                      else if (m.v === "schedule" && preset === "once") setPreset("1h");
                    }}
                  />
                  {m.l}
                </label>
              ))}
            </div>
          </Field>

          {triggerMode === "event" && (
            <Field label="事件類型">
              <select value={eventTypeId ?? ""} onChange={e => setEventTypeId(Number(e.target.value))} style={input}>
                {eventTypes.map(et => <option key={et.id} value={et.id}>{et.name}</option>)}
              </select>
            </Field>
          )}
          {(triggerMode === "schedule" || triggerMode === "once") && (
            <Field label={triggerMode === "once" ? "指定時間" : "排程設定"}>
              <SchedulePresetPicker
                preset={preset}
                onPresetChange={(p) => {
                  setPreset(p);
                  if (p === "once") setTriggerMode("once");
                  else if (triggerMode === "once") setTriggerMode("schedule");
                }}
                dailyTime={dailyTime}
                onDailyTimeChange={setDailyTime}
                scheduledAt={scheduledAt}
                onScheduledAtChange={setScheduledAt}
                customCron={customCron}
                onCustomCronChange={setCustomCron}
                layout="compact"
              />
            </Field>
          )}

          <Field label="告警嚴重度">
            <select value={severity} onChange={e => setSeverity(e.target.value as typeof severity)} style={input}>
              {(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const).map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>

          <Field label="告警標題">
            <input value={alarmTitle} onChange={e => setAlarmTitle(e.target.value)} style={input}
              placeholder="(預設：patrol 名稱)" />
          </Field>

          <Field label="Input Binding (JSON)">
            <textarea value={inputBinding} onChange={e => setInputBinding(e.target.value)} rows={3}
              style={{ ...input, fontFamily: "ui-monospace, monospace", fontSize: 12 }}
              placeholder='{"tool_id": "$event.equipment_id"}' />
            <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 2 }}>
              觸發時怎麼把 event payload 對應到 pipeline inputs。可留 <code>{"{}"}</code>（空），后端會 auto-fallback tool_id=equipment_id。
            </div>
          </Field>

          {error && <div style={{ background: "#fff1f0", color: "#cf1322", padding: 10, borderRadius: 6, fontSize: 12 }}>{error}</div>}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
            <button onClick={onClose} style={btn("ghost")} disabled={saving}>取消</button>
            <button onClick={handleSave} style={btn("primary")} disabled={saving}>
              {saving ? "建立中..." : "建立 Patrol"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: "#4a5568", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.3px" }}>{label}</div>
      {children}
    </div>
  );
}

// ── styles ──────────────────────────────────────────────────────
const overlay: React.CSSProperties = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000,
  display: "flex", alignItems: "center", justifyContent: "center",
};
const modal: React.CSSProperties = {
  background: "#fff", borderRadius: 8, maxWidth: 560, width: "90vw", maxHeight: "90vh",
  overflow: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
};
const header: React.CSSProperties = {
  padding: "14px 20px", borderBottom: "1px solid #e2e8f0",
  display: "flex", justifyContent: "space-between", alignItems: "center", background: "#f7fafc",
};
const closeBtn: React.CSSProperties = {
  border: "none", background: "transparent", cursor: "pointer", fontSize: 16, color: "#a0aec0",
};
const input: React.CSSProperties = {
  width: "100%", padding: "8px 10px", border: "1px solid #e2e8f0", borderRadius: 6,
  fontSize: 13, outline: "none", boxSizing: "border-box",
};
function btn(kind: "primary" | "ghost"): React.CSSProperties {
  return kind === "primary" ? {
    padding: "8px 16px", background: "#1890ff", color: "#fff",
    border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer",
  } : {
    padding: "8px 16px", background: "#fff", color: "#4a5568",
    border: "1px solid #e2e8f0", borderRadius: 6, fontSize: 13, cursor: "pointer",
  };
}
