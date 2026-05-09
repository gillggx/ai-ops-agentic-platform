"use client";

/**
 * TriggerConfig — port of prototype's collapsible 3-mode trigger panel.
 *
 * Mode A: System Event — picks from SYSTEM_EVENTS list, optional payload
 *         filter expression.
 * Mode B: User-Defined — auto-generates a Rule {source, metric, op, value,
 *         window, debounce, severity}.
 * Mode C: Auto Patrol — cron expression (Every N min/hour/day) with skip
 *         conditions and Next-4-fires preview.
 */
import { useState, type ReactNode } from "react";
import { Icon } from "./atoms";
import type { TriggerConfig as TC } from "./atoms";

const SYSTEM_EVENTS = [
  { id: "OCAP_TRIGGERED",     label: "OCAP_TRIGGERED",      desc: "SPC system flags Out-of-Control Action Plan",        owner: "SPC",   color: "var(--fail)" },
  { id: "FDC_VIOLATION",      label: "FDC_VIOLATION",       desc: "Fault Detection & Classification anomaly",            owner: "FDC",   color: "var(--fail)" },
  { id: "CHAMBER_MATCH_FAIL", label: "CHAMBER_MATCH_FAIL",  desc: "Chamber matching deviation across tools",             owner: "EE",    color: "var(--warn)" },
  { id: "PM_DUE",             label: "PM_DUE",              desc: "Preventive maintenance window approaching",           owner: "EQ",    color: "var(--warn)" },
  { id: "RECIPE_DEVIATION",   label: "RECIPE_DEVIATION",    desc: "APC adjusted recipe outside guard-band",              owner: "APC",   color: "var(--warn)" },
  { id: "WAFER_SCRAP",        label: "WAFER_SCRAP",         desc: "Wafer scrap event raised by yield system",            owner: "Yield", color: "var(--fail)" },
];

const USER_OPS = [">=", ">", "=", "<", "<=", "changed", "drift"];

function summary(t: TC): { kind: string; value: string; color: string } {
  if (t.type === "system") {
    const ev = SYSTEM_EVENTS.find((e) => e.id === t.event_type);
    return { kind: "Event", value: ev?.label || "—", color: ev?.color || "var(--ink-3)" };
  }
  if (t.type === "user") {
    return { kind: "Custom", value: `when ${t.metric ?? ""} ${t.op ?? ""} ${t.value ?? ""}`.trim(), color: "var(--ai)" };
  }
  return {
    kind: "Cron",
    value: t.every != null && t.unit
      ? `every ${t.every} ${t.unit}${t.every > 1 ? "s" : ""}`
      : (t.cron ?? "—"),
    color: "var(--pass)",
  };
}

export function TriggerConfigEditor({
  trigger, setTrigger, readOnly,
}: {
  trigger: TC;
  setTrigger: (t: TC) => void;
  readOnly?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const s = summary(trigger);

  const types = [
    { id: "system" as const,   label: "System Event", color: "var(--fail)" },
    { id: "user" as const,     label: "User-Defined", color: "var(--ai)" },
    { id: "schedule" as const, label: "Auto Patrol",  color: "var(--pass)" },
  ];

  return (
    <div style={{
      marginTop: 24,
      background: "var(--surface-2)",
      border: "1px solid var(--line)", borderRadius: 10,
      overflow: "hidden",
    }}>
      <button onClick={() => !readOnly && setOpen(!open)} style={{
        all: "unset", display: "block", width: "100%",
        padding: "14px 16px", cursor: readOnly ? "default" : "pointer",
      }}>
        <div style={{
          display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr auto", gap: 16, alignItems: "center",
        }}>
          <div>
            <div className="mono" style={{ fontSize: 9.5, color: "var(--ink-3)", letterSpacing: "0.08em", marginBottom: 4 }}>
              TRIGGER · {s.kind.toUpperCase()}
            </div>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 6, height: 6, borderRadius: 999, background: s.color }}/>
              <span className="mono" style={{ fontSize: 12.5, color: "var(--ink)" }}>{s.value || "—"}</span>
            </div>
          </div>
          <div style={{ borderLeft: "1px solid var(--line)", paddingLeft: 16 }}>
            <div className="mono" style={{ fontSize: 9.5, color: "var(--ink-3)", letterSpacing: "0.08em", marginBottom: 4 }}>SCOPE</div>
            <div style={{ fontSize: 12.5 }}>
              <span className="mono">{trigger.scope || "—"}</span>
            </div>
          </div>
          <div style={{ borderLeft: "1px solid var(--line)", paddingLeft: 16 }}>
            <div className="mono" style={{ fontSize: 9.5, color: "var(--ink-3)", letterSpacing: "0.08em", marginBottom: 4 }}>SLA</div>
            <div style={{ fontSize: 12.5 }}>complete in <span className="mono">&lt; 90s</span></div>
          </div>
          <div style={{ borderLeft: "1px solid var(--line)", paddingLeft: 16 }}>
            <div className="mono" style={{ fontSize: 9.5, color: "var(--ink-3)", letterSpacing: "0.08em", marginBottom: 4 }}>EVIDENCE WINDOW</div>
            <div style={{ fontSize: 12.5 }}>last <span className="mono">5 lots</span></div>
          </div>
          {!readOnly && (
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "5px 10px", borderRadius: 6,
              border: "1px solid var(--line-strong)", background: "var(--surface)",
              color: "var(--ink-2)", fontSize: 11.5,
            }}>
              <Icon.Pencil/> {open ? "Done" : "Configure"}
            </div>
          )}
        </div>
      </button>

      {open && !readOnly && (
        <div style={{
          padding: "18px 16px", borderTop: "1px solid var(--line)",
          background: "var(--surface)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <Seg
              value={trigger.type ?? "system"}
              options={types.map((t) => ({
                id: t.id,
                label: t.label,
                icon: <span style={{ width: 6, height: 6, borderRadius: 999, background: t.color }}/>,
              }))}
              onChange={(id) => setTrigger({ ...trigger, type: id as "system" | "user" | "schedule" })}
            />
            <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
              {trigger.type === "system"   && "綁定平台已知的 system event。"}
              {trigger.type === "user"     && "由使用者自訂 metric 與條件，平台會持續監聽。"}
              {(trigger.type === "schedule" || !trigger.type) && "依固定時間間隔執行 (Auto Patrol)。"}
            </span>
          </div>
          {trigger.type === "system"   && <SystemEventConfig trigger={trigger} setTrigger={setTrigger}/>}
          {trigger.type === "user"     && <UserEventConfig   trigger={trigger} setTrigger={setTrigger}/>}
          {(trigger.type === "schedule" || !trigger.type) && <ScheduleConfig trigger={trigger} setTrigger={setTrigger}/>}
        </div>
      )}
    </div>
  );
}

function Seg<T extends string>({
  value, options, onChange,
}: {
  value: T;
  options: { id: T; label: string; icon?: ReactNode }[];
  onChange: (id: T) => void;
}) {
  return (
    <div style={{
      display: "inline-flex", padding: 2, borderRadius: 8,
      background: "var(--surface-2)", border: "1px solid var(--line)",
    }}>
      {options.map((o) => (
        <button key={o.id} onClick={() => onChange(o.id)}
          style={{
            display: "inline-flex", alignItems: "center", gap: 7,
            padding: "6px 12px", borderRadius: 6, border: "none",
            background: value === o.id ? "var(--surface)" : "transparent",
            color: value === o.id ? "var(--ink)" : "var(--ink-3)",
            fontSize: 12, fontWeight: 500, cursor: "pointer",
            boxShadow: value === o.id ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
          }}>
          {o.icon}{o.label}
        </button>
      ))}
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>{label}</span>
        {hint && <span style={{ fontSize: 11, color: "var(--ink-4)" }}>{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function Input({ value, onChange, placeholder, mono = false, width }: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  width?: number | string;
}) {
  return (
    <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
      className={mono ? "mono" : ""}
      style={{
        padding: "7px 10px", fontSize: mono ? 12 : 13,
        border: "1px solid var(--line-strong)", background: "var(--surface)",
        color: "var(--ink)", borderRadius: 6, outline: "none",
        fontFamily: mono ? "JetBrains Mono, ui-monospace, monospace" : "inherit",
        width: width != null ? width : "100%",
      }}/>
  );
}

function SystemEventConfig({ trigger, setTrigger }: { trigger: TC; setTrigger: (t: TC) => void }) {
  const [q, setQ] = useState("");
  const filtered = SYSTEM_EVENTS.filter((e) =>
    !q.trim() || e.label.toLowerCase().includes(q.toLowerCase()) || e.desc.toLowerCase().includes(q.toLowerCase()),
  );
  const sel = SYSTEM_EVENTS.find((e) => e.id === trigger.event_type);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 24 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field label="EVENT SOURCE" hint="平台已註冊的 system event">
          <Input value={q} onChange={setQ} placeholder="搜尋 event…  e.g. OCAP / FDC / PM"/>
        </Field>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 220, overflowY: "auto" }}>
          {filtered.map((e) => {
            const active = e.id === trigger.event_type;
            return (
              <button key={e.id} onClick={() => setTrigger({ ...trigger, event_type: e.id })}
                style={{
                  all: "unset", cursor: "pointer",
                  display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 12, alignItems: "center",
                  padding: "9px 12px", borderRadius: 6,
                  background: active ? "var(--surface-2)" : "transparent",
                  border: `1px solid ${active ? "var(--ink-2)" : "var(--line)"}`,
                }}>
                <span style={{ width: 6, height: 6, borderRadius: 999, background: e.color }}/>
                <div>
                  <div className="mono" style={{ fontSize: 12, color: "var(--ink)", fontWeight: 500 }}>{e.label}</div>
                  <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 2 }}>{e.desc}</div>
                </div>
                <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{e.owner}</span>
              </button>
            );
          })}
        </div>
        <Field label="ADDITIONAL FILTERS" hint="只在 payload 符合條件時觸發">
          <Input mono
            value={trigger.scope ?? ""}
            onChange={(v) => setTrigger({ ...trigger, scope: v })}
            placeholder="tool_id IN ('EQP-01','EQP-02')"/>
        </Field>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Field label="PAYLOAD SCHEMA" hint="event 觸發時可用的變數">
          <pre className="mono" style={{
            margin: 0, padding: 12, background: "var(--bg-soft)",
            border: "1px solid var(--line)", borderRadius: 6,
            fontSize: 11, color: "var(--ink-2)", lineHeight: 1.7, whiteSpace: "pre-wrap",
          }}>{`{
  event_id:        ${sel?.label || "—"},
  fired_at:        timestamp,
  tool_id:         string,
  lot_id:          string,
  process_id:      string,
  spc_chart:       string,
  severity:        "low"|"med"|"high",
  raw_payload:     object
}`}</pre>
        </Field>
        <div style={{ fontSize: 11.5, color: "var(--ink-3)", lineHeight: 1.5 }}>
          這些欄位會以 <span className="mono" style={{ color: "var(--ink-2)" }}>$variable</span> 形式注入到下方
          每個 step 的 pipeline 中，無需手動配線。
        </div>
      </div>
    </div>
  );
}

function UserEventConfig({ trigger, setTrigger }: { trigger: TC; setTrigger: (t: TC) => void }) {
  const set = (patch: Partial<TC>) => setTrigger({ ...trigger, ...patch });
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 24 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field label="EVENT NAME" hint="此 trigger 將以此名稱被其他 skill 引用">
          <Input mono value={trigger.name ?? ""} onChange={(v) => set({ name: v })} placeholder="e.g. CD_BIAS_DRIFT"/>
        </Field>
        <Field label="WATCHED METRIC" hint="平台會持續監聽這個訊號">
          <div style={{ display: "flex", gap: 8 }}>
            <select value={trigger.source ?? "spc.xbar_chart"} onChange={(e) => set({ source: e.target.value })}
              style={{ padding: "7px 10px", fontSize: 12, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--ink)", borderRadius: 6, fontFamily: "JetBrains Mono, monospace" }}>
              <option>spc.xbar_chart</option>
              <option>fdc.tool_health</option>
              <option>apc.recipe_offset</option>
              <option>yield.bin_count</option>
            </select>
            <Input mono width={180} value={trigger.metric ?? ""} onChange={(v) => set({ metric: v })} placeholder="cd_bias"/>
          </div>
        </Field>
        <Field label="CONDITION">
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <span className="mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>when</span>
            <span className="mono" style={{ fontSize: 12, color: "var(--ink)", padding: "6px 10px", background: "var(--surface-2)", borderRadius: 6 }}>{trigger.metric || "—"}</span>
            <select value={trigger.op ?? ">="} onChange={(e) => set({ op: e.target.value })}
              style={{ padding: "7px 10px", fontSize: 12, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--ink)", borderRadius: 6, fontFamily: "JetBrains Mono, monospace" }}>
              {USER_OPS.map((o) => <option key={o}>{o}</option>)}
            </select>
            <Input mono width={120} value={trigger.value ?? ""} onChange={(v) => set({ value: v })} placeholder="3"/>
            <span className="mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>for</span>
            <Input mono width={80} value={trigger.window ?? ""} onChange={(v) => set({ window: v })} placeholder="5 lots"/>
          </div>
        </Field>
        <Field label="DEBOUNCE" hint="同一 trigger 在此期間內不會重複觸發">
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Input mono width={80} value={trigger.debounce ?? ""} onChange={(v) => set({ debounce: v })} placeholder="30m"/>
            <Seg
              value={trigger.severity ?? "med"}
              options={[
                { id: "low", label: "Low" },
                { id: "med", label: "Med" },
                { id: "high", label: "High" },
              ]}
              onChange={(id) => set({ severity: id })}
            />
          </div>
        </Field>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Field label="GENERATED RULE" hint="平台將部署為持續監聽 rule">
          <pre className="mono" style={{
            margin: 0, padding: 12, background: "var(--bg-soft)",
            border: "1px solid var(--line)", borderRadius: 6,
            fontSize: 11, color: "var(--ink-2)", lineHeight: 1.7, whiteSpace: "pre-wrap",
          }}>{`rule "${trigger.name || "UNTITLED"}" {
  source:   ${trigger.source ?? "—"}
  metric:   ${trigger.metric ?? "—"}
  when:     value ${trigger.op ?? "—"} ${trigger.value ?? "—"}
  window:   ${trigger.window ?? "—"}
  debounce: ${trigger.debounce ?? "—"}
  severity: ${trigger.severity ?? "—"}
}`}</pre>
        </Field>
      </div>
    </div>
  );
}

function ScheduleConfig({ trigger, setTrigger }: { trigger: TC; setTrigger: (t: TC) => void }) {
  const set = (patch: Partial<TC>) => setTrigger({ ...trigger, ...patch });
  const every = trigger.every ?? 4;
  const unit = trigger.unit ?? "hour";
  const skip = trigger.skip ?? [];

  const cron =
    unit === "minute" ? `*/${every} * * * *` :
    unit === "hour"   ? `0 */${every} * * *` :
                        `0 0 */${every} * *`;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 24 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field label="INTERVAL" hint="auto patrol 執行頻率">
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: "var(--ink-3)" }}>Every</span>
            <Input mono width={70} value={String(every)} onChange={(v) => set({ every: parseInt(v) || 1 })}/>
            <Seg
              value={unit}
              options={[
                { id: "minute", label: "Min" },
                { id: "hour",   label: "Hour" },
                { id: "day",    label: "Day" },
              ]}
              onChange={(id) => set({ unit: id as "minute" | "hour" | "day" })}
            />
          </div>
        </Field>
        <Field label="TIMEZONE">
          <select value={trigger.timezone ?? "Asia/Taipei (UTC+8)"} onChange={(e) => set({ timezone: e.target.value })}
            style={{ padding: "7px 10px", fontSize: 12, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--ink)", borderRadius: 6, fontFamily: "inherit" }}>
            <option>Asia/Taipei (UTC+8)</option>
            <option>Asia/Tokyo (UTC+9)</option>
            <option>UTC</option>
          </select>
        </Field>
        <Field label="SKIP CONDITIONS" hint="符合任一條件時跳過此次執行">
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {[
              { id: "tool_idle",  label: "Tool idle / down" },
              { id: "lot_locked", label: "Lot held" },
              { id: "no_change",  label: "No upstream change" },
              { id: "in_pm",      label: "Tool in PM" },
            ].map((c) => {
              const active = skip.includes(c.id);
              return (
                <button key={c.id}
                  onClick={() => set({
                    skip: active ? skip.filter((x) => x !== c.id) : [...skip, c.id],
                  })}
                  style={{
                    all: "unset", cursor: "pointer",
                    padding: "5px 10px", borderRadius: 999,
                    fontSize: 11.5,
                    background: active ? "var(--ink)" : "var(--surface)",
                    color: active ? "var(--bg)" : "var(--ink-2)",
                    border: `1px solid ${active ? "var(--ink)" : "var(--line-strong)"}`,
                  }}>
                  {active ? "✓ " : ""}{c.label}
                </button>
              );
            })}
          </div>
        </Field>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Field label="CRON EXPRESSION" hint="自動產生">
          <pre className="mono" style={{
            margin: 0, padding: 12, background: "var(--bg-soft)",
            border: "1px solid var(--line)", borderRadius: 6,
            fontSize: 12, color: "var(--ink)", letterSpacing: "0.02em",
          }}>{cron}</pre>
        </Field>
        <Field label="NEXT EXECUTIONS" hint="預覽未來 4 次觸發時間">
          <NextRunPreview every={every} unit={unit}/>
        </Field>
      </div>
    </div>
  );
}

function NextRunPreview({ every, unit }: { every: number; unit: "minute" | "hour" | "day" }) {
  const intervalMin = unit === "hour" ? every * 60 : unit === "day" ? every * 1440 : every;
  const now = new Date();
  const slots = Array.from({ length: 4 }, (_, i) => new Date(now.getTime() + intervalMin * 60_000 * (i + 1)));
  const fmt = (d: Date) => `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
      {slots.map((d, i) => (
        <div key={i} style={{
          padding: "6px 10px", background: "var(--surface)",
          border: "1px solid var(--line)", borderRadius: 6,
          fontSize: 11, color: "var(--ink-2)",
        }}>
          <span className="mono">{fmt(d)}</span>
          {i === 0 && <span style={{ marginLeft: 6, color: "var(--ai)", fontSize: 10 }}>· next</span>}
        </div>
      ))}
      <div style={{ padding: "6px 10px", fontSize: 11, color: "var(--ink-4)" }}>
        + {Math.max(0, Math.round((24 * 60) / intervalMin) - 4)} more / day
      </div>
    </div>
  );
}
