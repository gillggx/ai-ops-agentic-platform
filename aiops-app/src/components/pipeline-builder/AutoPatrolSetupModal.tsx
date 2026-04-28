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
  target_scope?: string | TargetScope | null;
}

// SPEC_patrol_pipeline_wiring §1.2 — scope describes how a non-event
// trigger picks the equipment(s) to bind into pipeline.inputs.
type TargetScope =
  | { type: "event_driven" }
  | { type: "all_equipment"; fanout_cap?: number }
  | { type: "specific_equipment"; equipment_ids: string[]; fanout_cap?: number }
  | { type: "by_step"; step: string; fanout_cap?: number };

const DEFAULT_FANOUT_CAP = 20;

interface EventTypeWithAttrs {
  id: number;
  name: string;
  attributes?: string;  // JSON-encoded list of {name,type,required,description}
}

interface AttributeSpec {
  name: string;
  type: string;
  required: boolean;
  description?: string;
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
  const [eventTypes, setEventTypes] = useState<EventTypeWithAttrs[]>([]);
  const [saving, setSaving]         = useState(false);
  const [error, setError]           = useState<string | null>(null);
  // SPEC §1.2 — scope state. Only relevant when trigger.mode is schedule/once;
  // event-mode patrols always store {type:"event_driven"} server-side.
  const [scopeType, setScopeType] = useState<"all_equipment" | "specific_equipment" | "by_step">("all_equipment");
  const [scopeEquipmentIds, setScopeEquipmentIds] = useState<string>("");  // CSV "EQP-01,EQP-02"
  const [scopeStep, setScopeStep] = useState<string>("");
  const [fanoutCap, setFanoutCap] = useState<number>(DEFAULT_FANOUT_CAP);

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
      // Hydrate scope from existing patrol's target_scope
      try {
        const ts: TargetScope = typeof existingPatrol.target_scope === "string"
          ? JSON.parse(existingPatrol.target_scope || "{}")
          : (existingPatrol.target_scope as TargetScope) || { type: "event_driven" };
        if (ts.type === "specific_equipment") {
          setScopeType("specific_equipment");
          setScopeEquipmentIds((ts.equipment_ids ?? []).join(","));
          setFanoutCap(ts.fanout_cap ?? DEFAULT_FANOUT_CAP);
        } else if (ts.type === "by_step") {
          setScopeType("by_step");
          setScopeStep(ts.step ?? "");
          setFanoutCap(ts.fanout_cap ?? DEFAULT_FANOUT_CAP);
        } else if (ts.type === "all_equipment") {
          setScopeType("all_equipment");
          setFanoutCap(ts.fanout_cap ?? DEFAULT_FANOUT_CAP);
        } else {
          // event_driven — keep defaults; user can flip mode later
          setScopeType("all_equipment");
        }
      } catch {
        setScopeType("all_equipment");
      }
    } else {
      setName(`[Patrol] ${pipelineName}`.slice(0, 200));
      setDesc("");
      setTrigger(emptyTrigger());
      setSeverity("HIGH");
      setAlarmTitle(pipelineName);
      setInputBinding("{}");
      setScopeType("all_equipment");
      setScopeEquipmentIds("");
      setScopeStep("");
      setFanoutCap(DEFAULT_FANOUT_CAP);
    }
    setError(null);
  }, [open, pipelineName, existingPatrol]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Default the first event_type when loaded and nothing selected
  useEffect(() => {
    if (trigger.mode === "event" && trigger.eventTypeId == null && eventTypes.length > 0) {
      setTrigger({ ...trigger, eventTypeId: eventTypes[0].id });
    }
  }, [eventTypes, trigger]);

  // SPEC §1.3 — convention-based input_binding suggestion (Option 3 auto-fill).
  function suggestInputBinding() {
    const out: Record<string, string> = {};
    if (trigger.mode === "event" && trigger.eventTypeId != null) {
      const et = eventTypes.find(e => e.id === trigger.eventTypeId);
      const attrs: AttributeSpec[] = (() => {
        try {
          const raw = et?.attributes;
          return raw ? (JSON.parse(raw) as AttributeSpec[]) : [];
        } catch {
          return [];
        }
      })();
      const has = (n: string) => attrs.some(a => a.name === n);
      if (has("equipment_id") || has("tool_id")) {
        const src = has("equipment_id") ? "equipment_id" : "tool_id";
        out.tool_id = `$event.${src}`;
      }
      if (has("step") || has("step_id")) {
        const src = has("step") ? "step" : "step_id";
        out.step = `$event.${src}`;
      }
      if (has("lot_id")) out.lot_id = "$event.lot_id";
    } else if (trigger.mode === "schedule" || trigger.mode === "once") {
      // Loop variables — backend AutoPatrolService expands target_scope into
      // these per-iteration values.
      out.tool_id = "$loop.tool_id";
      if (scopeType === "by_step") out.step = "$loop.step";
    }
    setInputBinding(JSON.stringify(out, null, 2));
  }

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

    // SPEC §1.2 — assemble proper target_scope based on trigger mode + scope picker
    let scopeJson: TargetScope;
    if (trigger.mode === "event") {
      scopeJson = { type: "event_driven" };
    } else if (scopeType === "specific_equipment") {
      const ids = scopeEquipmentIds.split(",").map(s => s.trim()).filter(Boolean);
      if (ids.length === 0) { setError("「指定機台」需至少 1 台"); return; }
      scopeJson = { type: "specific_equipment", equipment_ids: ids, fanout_cap: fanoutCap };
    } else if (scopeType === "by_step") {
      if (!scopeStep.trim()) { setError("「指定站點」需填 step"); return; }
      scopeJson = { type: "by_step", step: scopeStep.trim(), fanout_cap: fanoutCap };
    } else {
      scopeJson = { type: "all_equipment", fanout_cap: fanoutCap };
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
        data_context: trigger.mode === "event" ? "event_driven" : "scheduled",
        target_scope: JSON.stringify(scopeJson),
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

          {/* SPEC §1.2 — scope picker only when trigger ≠ event */}
          {(trigger.mode === "schedule" || trigger.mode === "once") && (
            <Field label="目標範圍">
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }}>
                {([
                  { v: "all_equipment" as const, label: "所有機台", desc: `cron 跑時抓 simulator 全部機台 list（最多 ${fanoutCap} 台）` },
                  { v: "specific_equipment" as const, label: "指定機台", desc: "在下方填 EQP-01,EQP-02 (CSV)" },
                  { v: "by_step" as const, label: "指定站點", desc: "選 step → 抓該 step 所有機台（cap 適用）" },
                ]).map(opt => (
                  <label key={opt.v} style={{ display: "flex", alignItems: "flex-start", gap: 6, cursor: "pointer" }}>
                    <input type="radio" checked={scopeType === opt.v} onChange={() => setScopeType(opt.v)} />
                    <span>
                      <span style={{ fontWeight: 600 }}>{opt.label}</span>
                      <span style={{ color: "#718096", marginLeft: 6 }}>— {opt.desc}</span>
                    </span>
                  </label>
                ))}
                {scopeType === "specific_equipment" && (
                  <input
                    style={input}
                    value={scopeEquipmentIds}
                    onChange={e => setScopeEquipmentIds(e.target.value)}
                    placeholder="EQP-01, EQP-02, EQP-03"
                  />
                )}
                {scopeType === "by_step" && (
                  <input
                    style={input}
                    value={scopeStep}
                    onChange={e => setScopeStep(e.target.value)}
                    placeholder="STEP_001"
                  />
                )}
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 11, color: "#718096" }}>Fanout cap (上限)：</span>
                  <input
                    type="number"
                    min={1}
                    max={500}
                    style={{ ...input, width: 80, padding: "4px 8px" }}
                    value={fanoutCap}
                    onChange={e => setFanoutCap(parseInt(e.target.value || "20", 10))}
                  />
                  <span style={{ fontSize: 10, color: "#a0aec0" }}>(超過 cap 會截斷 + 寫 warning alarm)</span>
                </div>
              </div>
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
            <div style={{ display: "flex", gap: 6, marginBottom: 4 }}>
              <button
                type="button"
                onClick={suggestInputBinding}
                style={{ ...btn("ghost"), padding: "4px 10px", fontSize: 11 }}
              >
                ✨ 套用建議 binding
              </button>
              <span style={{ fontSize: 11, color: "#a0aec0", alignSelf: "center" }}>
                依 trigger + scope + event attribute 自動配（可手動微調）
              </span>
            </div>
            <textarea value={inputBinding} onChange={e => setInputBinding(e.target.value)} rows={3}
              style={{ ...input, fontFamily: "ui-monospace, monospace", fontSize: 12 }}
              placeholder='{"tool_id": "$event.equipment_id"}' />
            <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 2 }}>
              支援 <code>$event.X</code> / <code>$loop.X</code> / 字面值。Event 觸發抓 event payload；schedule/once 觸發抓 scope 展開的 loop 變數。
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
