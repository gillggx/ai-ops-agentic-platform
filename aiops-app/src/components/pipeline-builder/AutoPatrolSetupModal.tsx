"use client";

/**
 * Phase β of Option A UX consolidation:
 * Create (or edit) an Auto-Patrol binding for the current pipeline without
 * leaving the Pipeline Builder. Fields are a lean subset of the old
 * /admin/auto-patrols form — skip skill-mode, AI step generation, and
 * diagnostic rule pickers (those live on the legacy page for now).
 *
 * P4.1 — trigger UI extracted to AutoPatrolTriggerForm (shared with the
 * /admin/pipeline-builder/new wizard).
 * P4.4 — supports edit mode: if an existing patrol is bound, hydrate from
 * it and PATCH instead of POST.
 */
import { useEffect, useState } from "react";
import AutoPatrolTriggerForm, {
  emptyTrigger,
  validateTrigger,
  type AutoPatrolTriggerValue,
  type EventType,
} from "./AutoPatrolTriggerForm";

interface ExistingPatrol {
  id: number;
  name: string;
  description: string;
  trigger_mode: "event" | "schedule" | "once";
  event_type_id: number | null;
  cron_expr: string | null;
  scheduled_at: string | null;
  alarm_severity: string | null;
  alarm_title: string | null;
  input_binding: Record<string, unknown> | null;
}

export default function AutoPatrolSetupModal({
  open, pipelineId, pipelineName, onClose, onCreated, existingPatrol,
}: {
  open: boolean;
  pipelineId: number;
  pipelineName: string;
  onClose: () => void;
  onCreated: (patrolId: number) => void;
  /** When set, modal opens in EDIT mode — form is prefilled, Save PATCHes. */
  existingPatrol?: ExistingPatrol | null;
}) {
  const isEdit = existingPatrol != null;

  const [name, setName]             = useState("");
  const [description, setDesc]      = useState("");
  const [trigger, setTrigger]       = useState<AutoPatrolTriggerValue>(emptyTrigger());
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
      })
      .catch(() => setEventTypes([]));
    // Hydrate form from existing patrol (edit) or defaults (create)
    if (existingPatrol) {
      setName(existingPatrol.name);
      setDesc(existingPatrol.description || "");
      setTrigger({
        mode: existingPatrol.trigger_mode,
        eventTypeId: existingPatrol.event_type_id,
        cronExpr: existingPatrol.cron_expr ?? "",
        scheduledAt: existingPatrol.scheduled_at ?? "",
      });
      setSeverity((existingPatrol.alarm_severity as typeof severity) ?? "HIGH");
      setAlarmTitle(existingPatrol.alarm_title ?? "");
      setInputBinding(JSON.stringify(existingPatrol.input_binding ?? {}, null, 2));
    } else {
      setName(`[Patrol] ${pipelineName}`.slice(0, 200));
      setDesc("");
      setTrigger(emptyTrigger());
      setSeverity("HIGH");
      setAlarmTitle(pipelineName);
      setInputBinding("{}");
    }
    setError(null);
  }, [open, pipelineName, existingPatrol]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Default the first event_type when loaded and nothing selected
  useEffect(() => {
    if (trigger.mode === "event" && trigger.eventTypeId == null && eventTypes.length > 0) {
      setTrigger({ ...trigger, eventTypeId: eventTypes[0].id });
    }
  }, [eventTypes, trigger]);

  if (!open) return null;

  async function handleSave() {
    if (!name.trim()) { setError("Patrol 名稱必填"); return; }
    const triggerError = validateTrigger(trigger);
    if (triggerError) { setError(triggerError); return; }

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
        trigger_mode: trigger.mode,
        cron_expr: trigger.mode === "schedule" ? trigger.cronExpr : null,
        scheduled_at: trigger.mode === "once" ? trigger.scheduledAt : null,
        event_type_id: trigger.mode === "event" ? trigger.eventTypeId : null,
        execution_mode: "pipeline",
        pipeline_id: pipelineId,
        alarm_severity: severity,
        alarm_title: alarmTitle.trim() || name.trim(),
        input_binding: inputBindingParsed ? JSON.stringify(inputBindingParsed) : null,
        data_context: "event_driven",
        target_scope: JSON.stringify({ type: "event_driven" }),
        is_active: true,
      };
      const url = isEdit
        ? `/api/admin/auto-patrols/${existingPatrol!.id}`
        : "/api/admin/auto-patrols";
      const method = isEdit ? "PATCH" : "POST";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(`HTTP ${res.status}: ${t.slice(0, 200)}`);
      }
      const body = await res.json();
      const saved = body?.data ?? body;
      onCreated(saved.id ?? existingPatrol?.id ?? pipelineId);
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
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#1a202c" }}>
            🔔 {isEdit ? "編輯 Auto-Patrol" : "建立 Auto-Patrol"}
          </h3>
          <button onClick={onClose} style={closeBtn}>✕</button>
        </div>

        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, fontSize: 13 }}>

          <div style={{ fontSize: 12, color: "#718096" }}>
            這個 patrol 會執行 Pipeline <code style={{ background: "#edf2f7", padding: "2px 6px", borderRadius: 3 }}>#{pipelineId} {pipelineName}</code>，觸發警報時寫入 alarms。
          </div>

          <Field label="Patrol 名稱 *">
            <input value={name} onChange={e => setName(e.target.value)} style={input} />
          </Field>

          <Field label="描述">
            <input value={description} onChange={e => setDesc(e.target.value)} style={input}
              placeholder="(可選，說明這個 patrol 做什麼)" />
          </Field>

          <Field label="觸發設定">
            <AutoPatrolTriggerForm
              value={trigger}
              onChange={setTrigger}
              eventTypes={eventTypes}
              compact
            />
          </Field>

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
              {saving ? (isEdit ? "更新中..." : "建立中...") : (isEdit ? "儲存變更" : "建立 Patrol")}
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
